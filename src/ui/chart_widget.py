"""ローソク足・出来高・移動平均を表示するチャート。"""

from __future__ import annotations

import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets


class CandlestickItem(pg.GraphicsObject):
    """pyqtgraph 用の簡易ローソク足描画アイテム。"""

    def __init__(self, bars: pd.DataFrame, width_seconds: float) -> None:
        super().__init__()
        self.bars = bars
        self.width_seconds = float(width_seconds)
        self.picture = QtGui.QPicture()
        self._bounds = QtCore.QRectF()
        self._generate_picture()

    def _generate_picture(self) -> None:
        painter = QtGui.QPainter(self.picture)
        try:
            if self.bars.empty:
                return
            minimum_x = float(self.bars["x"].min())
            maximum_x = float(self.bars["x"].max())
            minimum_y = float(self.bars["Low"].min())
            maximum_y = float(self.bars["High"].max())
            span_y = max(maximum_y - minimum_y, 0.01)
            body_minimum = span_y * 0.001

            for row in self.bars.itertuples(index=False):
                opening = float(row.Open)
                high = float(row.High)
                low = float(row.Low)
                close = float(row.Close)
                rising = close >= opening
                color = QtGui.QColor("#16a34a" if rising else "#dc2626")
                painter.setPen(pg.mkPen(color, width=1))
                painter.setBrush(pg.mkBrush(color))
                x = float(row.x)
                painter.drawLine(QtCore.QPointF(x, low), QtCore.QPointF(x, high))
                body_top = max(opening, close)
                body_height = max(abs(close - opening), body_minimum)
                painter.drawRect(
                    QtCore.QRectF(
                        x - self.width_seconds / 2,
                        body_top - body_height,
                        self.width_seconds,
                        body_height,
                    )
                )
            self._bounds = QtCore.QRectF(
                minimum_x - self.width_seconds,
                minimum_y - span_y * 0.02,
                max(maximum_x - minimum_x + 2 * self.width_seconds, self.width_seconds),
                span_y * 1.04,
            )
        finally:
            painter.end()

    def paint(self, painter: QtGui.QPainter, *args: object) -> None:
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self) -> QtCore.QRectF:
        return self._bounds


class VolumeItem(pg.BarGraphItem):
    """出来高バー用の薄いラッパー。"""


class ChartWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=True)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.graphics = pg.GraphicsLayoutWidget()
        self.layout.addWidget(self.graphics)

        self.price_axis = pg.DateAxisItem(orientation="bottom")
        self.price_plot = self.graphics.addPlot(row=0, col=0, axisItems={"bottom": self.price_axis})
        self.price_plot.setLabel("left", "価格")
        self.price_plot.showGrid(x=True, y=True, alpha=0.2)
        self.price_plot.addLegend(offset=(8, 8))
        self.price_plot.setMenuEnabled(False)

        self.volume_plot = self.graphics.addPlot(row=1, col=0, axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.volume_plot.setLabel("left", "出来高")
        self.volume_plot.showGrid(x=True, y=True, alpha=0.2)
        self.volume_plot.setMenuEnabled(False)
        self.volume_plot.setXLink(self.price_plot)
        self.volume_plot.setMaximumHeight(150)
        self._items: list[tuple[pg.PlotItem, object]] = []

    def set_bars(self, bars: pd.DataFrame | None, ticker: str = "") -> None:
        self._clear_items()
        if bars is None or bars.empty:
            self.price_plot.setTitle(f"{ticker} - データがありません")
            return

        frame = bars.copy()
        frame.index = pd.to_datetime(frame.index)
        frame = frame.sort_index()
        frame = frame.loc[:, [column for column in ("Open", "High", "Low", "Close", "Volume") if column in frame.columns]]
        required = {"Open", "High", "Low", "Close"}
        if not required.issubset(frame.columns):
            self.price_plot.setTitle(f"{ticker} - OHLC データが不足しています")
            return
        frame["x"] = frame.index.map(lambda stamp: stamp.timestamp())
        x_values = frame["x"].to_numpy(dtype=float)
        if len(x_values) > 1:
            spacing = float(pd.Series(x_values).diff().dropna().median())
            if spacing <= 0:
                spacing = 86_400.0
        else:
            spacing = 86_400.0
        candle_width = spacing * 0.62

        candles = CandlestickItem(frame.reset_index(drop=True), candle_width)
        self.price_plot.addItem(candles)
        self._items.append((self.price_plot, candles))

        close = pd.to_numeric(frame["Close"], errors="coerce")
        x = x_values
        sma25 = close.rolling(25, min_periods=25).mean()
        sma75 = close.rolling(75, min_periods=75).mean()
        line25 = self.price_plot.plot(x, sma25.to_numpy(), pen=pg.mkPen("#2563eb", width=1.5), name="SMA25")
        line75 = self.price_plot.plot(x, sma75.to_numpy(), pen=pg.mkPen("#a855f7", width=1.5), name="SMA75")
        self._items.extend([(self.price_plot, line25), (self.price_plot, line75)])

        volume_series = frame["Volume"] if "Volume" in frame.columns else pd.Series(0, index=frame.index)
        volume = pd.to_numeric(volume_series, errors="coerce").fillna(0).to_numpy()
        volume_item = VolumeItem(
            x=x,
            height=volume,
            width=candle_width,
            brush=pg.mkBrush(100, 140, 190, 130),
            pen=pg.mkPen(None),
        )
        self.volume_plot.addItem(volume_item)
        self._items.append((self.volume_plot, volume_item))

        self.price_plot.setTitle(f"{ticker} 日足")
        self.price_plot.setXRange(float(x[0]) - spacing, float(x[-1]) + spacing, padding=0.02)
        self.price_plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.volume_plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def _clear_items(self) -> None:
        for plot, item in self._items:
            try:
                plot.removeItem(item)
            except Exception:
                pass
        self._items.clear()
