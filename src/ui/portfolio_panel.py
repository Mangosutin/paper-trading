"""口座・保有銘柄・評価損益の表示パネル。"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from src.trading.engine import TradingEngine


class PortfolioPanel(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        summary = QtWidgets.QHBoxLayout()
        self.cash_label = QtWidgets.QLabel("現金: --")
        self.equity_label = QtWidgets.QLabel("評価額: --")
        self.pnl_label = QtWidgets.QLabel("評価損益: --")
        self.total_label = QtWidgets.QLabel("総資産: --")
        for label in (self.cash_label, self.equity_label, self.pnl_label, self.total_label):
            label.setStyleSheet("font-weight: 600; padding: 3px 8px;")
            summary.addWidget(label)
        summary.addStretch(1)
        root.addLayout(summary)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["銘柄", "保有数量", "取得単価", "現在値（約15-20分遅延）", "評価額", "評価損益"]
        )
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)

    @staticmethod
    def _yen(value: float) -> str:
        return f"{value:,.2f}"

    def refresh(
        self,
        engine: TradingEngine,
        prices: dict[str, float],
        quote_timestamps: dict[str, str] | None = None,
    ) -> None:
        account = engine.account()
        positions = engine.positions()
        quote_timestamps = quote_timestamps or {}
        self.table.setRowCount(len(positions))
        market_value_total = 0.0
        unrealized_total = 0.0
        for row_index, position in enumerate(positions):
            current_price = float(prices.get(position.ticker, position.average_price))
            market_value = current_price * position.quantity
            cost_value = position.average_price * position.quantity
            unrealized = market_value - cost_value
            market_value_total += market_value
            unrealized_total += unrealized
            values = (
                position.ticker,
                f"{position.quantity:,}",
                self._yen(position.average_price),
                f"{self._yen(current_price)}\n取得: {quote_timestamps.get(position.ticker, '--')}",
                self._yen(market_value),
                self._yen(unrealized),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column == 3:
                    item.setToolTip("約15-20分遅延を含む参考価格。取得時刻はセル内に表示。")
                if column in (1, 2, 3, 4, 5):
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                    )
                self.table.setItem(row_index, column, item)

        total_assets = account.cash + market_value_total
        self.cash_label.setText(f"現金: {self._yen(account.cash)}")
        self.equity_label.setText(f"保有評価額: {self._yen(market_value_total)}")
        self.pnl_label.setText(f"評価損益: {self._yen(unrealized_total)}")
        self.total_label.setText(f"総資産: {self._yen(total_assets)}")
