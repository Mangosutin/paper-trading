"""paper-trading のメインウィンドウ。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from src.data.cache import PriceCache
from src.data.provider import DataFetchError, MarketDataProvider, Quote
from src.trading.engine import TradingEngine
from src.trading.models import OrderType, Side, TradingError
from .chart_widget import ChartWidget
from .order_panel import OrderPanel
from .portfolio_panel import PortfolioPanel


class MainWindow(QtWidgets.QMainWindow):
    # TODO(v0.2.0): 15分足データのポーリングと資産曲線表示を追加する。
    # TODO(v0.2.0): フラットベース検出を追加する。

    def __init__(
        self,
        *,
        engine: TradingEngine,
        provider: MarketDataProvider,
        cache: PriceCache,
        config: dict[str, Any],
        project_root: Path,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.provider = provider
        self.cache = cache
        self.config = config
        self.project_root = project_root
        self.logger = logging.getLogger(__name__)
        self.current_ticker: str | None = None
        self.quotes: dict[str, Quote] = {}
        self.current_prices: dict[str, float] = {}
        self._updating_watchlist = False

        self.setWindowTitle("paper-trading - 仮想株式売買")
        self.resize(1440, 900)
        self._build_ui()
        self._build_menu()
        self._reload_watchlist()
        self.portfolio_panel.refresh(self.engine, self.current_prices, self._quote_timestamps())

        interval_ms = max(5, int(self.config.get("data", {}).get("poll_seconds", 60))) * 1000
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(interval_ms)
        self.refresh_timer.timeout.connect(self.refresh_selected)
        self.refresh_timer.start()

        if self.watchlist.count() > 0:
            self.watchlist.setCurrentRow(0)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("paper-trading")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        top.addWidget(title)
        top.addSpacing(16)
        self.quote_label = QtWidgets.QLabel(
            "価格: --（約15-20分遅延）取得時刻: --"
        )
        self.quote_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.quote_label, 1)
        self.refresh_button = QtWidgets.QPushButton("更新")
        self.refresh_button.clicked.connect(self.refresh_selected)
        top.addWidget(self.refresh_button)
        root.addLayout(top)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(main_splitter, 1)

        watch_panel = QtWidgets.QWidget()
        watch_layout = QtWidgets.QVBoxLayout(watch_panel)
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.addWidget(QtWidgets.QLabel("ウォッチリスト"))
        self.watchlist = QtWidgets.QListWidget()
        self.watchlist.currentTextChanged.connect(self._on_ticker_changed)
        watch_layout.addWidget(self.watchlist, 1)
        add_row = QtWidgets.QHBoxLayout()
        self.ticker_input = QtWidgets.QLineEdit()
        self.ticker_input.setPlaceholderText("例: MSFT")
        self.ticker_input.returnPressed.connect(self._add_ticker)
        self.add_button = QtWidgets.QPushButton("追加")
        self.add_button.clicked.connect(self._add_ticker)
        add_row.addWidget(self.ticker_input, 1)
        add_row.addWidget(self.add_button)
        watch_layout.addLayout(add_row)
        self.remove_button = QtWidgets.QPushButton("選択銘柄を削除")
        self.remove_button.clicked.connect(self._remove_ticker)
        watch_layout.addWidget(self.remove_button)
        watch_panel.setMinimumWidth(180)
        watch_panel.setMaximumWidth(260)
        main_splitter.addWidget(watch_panel)

        center_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.chart_widget = ChartWidget()
        center_splitter.addWidget(self.chart_widget)
        self.portfolio_panel = PortfolioPanel()
        center_splitter.addWidget(self.portfolio_panel)
        center_splitter.setStretchFactor(0, 4)
        center_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(center_splitter)

        self.order_panel = OrderPanel()
        self.order_panel.order_requested.connect(self._submit_order)
        self.order_panel.setMinimumWidth(220)
        self.order_panel.setMaximumWidth(280)
        main_splitter.addWidget(self.order_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([210, 1000, 240])

        self.setStatusBar(QtWidgets.QStatusBar())
        self.statusBar().showMessage("準備完了")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("ファイル")
        export_action = QtGui.QAction("取引履歴を CSV 出力", self)
        export_action.triggered.connect(self._export_history)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        exit_action = QtGui.QAction("終了", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _reload_watchlist(self, select_ticker: str | None = None) -> None:
        target = select_ticker or self.current_ticker
        self._updating_watchlist = True
        try:
            self.watchlist.clear()
            for ticker in self.engine.watchlist():
                self.watchlist.addItem(ticker)
        finally:
            self._updating_watchlist = False

        # 再選択はシグナル抑止を解除してから行い、選択銘柄の更新を確実に発火させる。
        if self.watchlist.count() == 0:
            self.current_ticker = None
            return
        matches = self.watchlist.findItems(target or "", QtCore.Qt.MatchFlag.MatchExactly)
        if matches:
            self.watchlist.setCurrentItem(matches[0])
        else:
            self.watchlist.setCurrentRow(0)

    def _add_ticker(self) -> None:
        ticker = self.ticker_input.text().strip().upper()
        if not ticker:
            return
        try:
            self.engine.add_to_watchlist(ticker)
            self.ticker_input.clear()
            self._reload_watchlist(select_ticker=ticker)
            self.statusBar().showMessage(f"{ticker} をウォッチリストに追加しました", 5000)
        except Exception as exc:
            self.logger.exception("ウォッチリスト追加に失敗: %s", ticker)
            self.statusBar().showMessage(f"追加できません: {exc}", 8000)

    def _remove_ticker(self) -> None:
        item = self.watchlist.currentItem()
        if item is None:
            return
        ticker = item.text()
        try:
            self.engine.remove_from_watchlist(ticker)
            self.current_prices.pop(ticker, None)
            self.quotes.pop(ticker, None)
            self._reload_watchlist()
            if self.watchlist.count() == 0:
                self.current_ticker = None
                self.chart_widget.set_bars(None)
                self.quote_label.setText("価格: --（約15-20分遅延）取得時刻: --")
                self.portfolio_panel.refresh(self.engine, self.current_prices, self._quote_timestamps())
            self.statusBar().showMessage(f"{ticker} を削除しました", 5000)
        except Exception as exc:
            self.logger.exception("ウォッチリスト削除に失敗: %s", ticker)
            self.statusBar().showMessage(f"削除できません: {exc}", 8000)

    def _on_ticker_changed(self, ticker: str) -> None:
        if self._updating_watchlist or not ticker:
            return
        self.current_ticker = ticker
        self.refresh_selected()

    def _quote_timestamps(self) -> dict[str, str]:
        return {
            ticker: quote.fetched_at.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
            for ticker, quote in self.quotes.items()
        }

    def _load_bars(self, ticker: str):
        period = "1y"
        interval = "1d"
        cached = self.cache.get(ticker, period, interval) if self.config.get("data", {}).get("cache_daily", True) else None
        now = datetime.now().astimezone()
        if cached is not None:
            cached_frame, cached_at = cached
            if cached_at.date() == now.date():
                return cached_frame
        try:
            bars = self.provider.get_bars(ticker, period=period, interval=interval)
            if self.config.get("data", {}).get("cache_daily", True):
                self.cache.save(ticker, period, interval, bars)
            return bars
        except DataFetchError as exc:
            if cached is not None:
                self.logger.warning("価格データ取得失敗、キャッシュを使用: %s", exc)
                self.statusBar().showMessage(f"{exc} / 保存済みデータを表示しています", 10000)
                return cached[0]
            raise

    def _refresh_quote(self, ticker: str) -> Quote | None:
        try:
            quote = self.provider.get_quote(ticker)
            self.quotes[ticker] = quote
            self.current_prices[ticker] = quote.price
            return quote
        except DataFetchError as exc:
            self.logger.warning("価格取得失敗 [%s]: %s", ticker, exc)
            if ticker == self.current_ticker:
                self.statusBar().showMessage(str(exc), 10000)
            return self.quotes.get(ticker)
        except Exception as exc:
            self.logger.exception("予期しない価格取得エラー [%s]", ticker)
            if ticker == self.current_ticker:
                self.statusBar().showMessage(f"価格取得エラー: {exc}", 10000)
            return self.quotes.get(ticker)

    def refresh_selected(self) -> None:
        ticker = self.current_ticker
        if not ticker:
            self.portfolio_panel.refresh(self.engine, self.current_prices, self._quote_timestamps())
            return
        self.refresh_button.setEnabled(False)
        try:
            bars = self._load_bars(ticker)
            self.chart_widget.set_bars(bars, ticker)
            try:
                matched = self.engine.process_bars(ticker, bars)
                if matched:
                    self.logger.info("指値約定: ticker=%s fills=%d", ticker, len(matched))
                    self.statusBar().showMessage(f"{len(matched)} 件の指値注文が約定しました", 8000)
            except Exception:
                self.logger.exception("指値注文の判定に失敗: %s", ticker)

            quote_targets = set(self.engine.watchlist())
            quote_targets.update(position.ticker for position in self.engine.positions())
            quote_targets.add(ticker)
            for symbol in sorted(quote_targets):
                self._refresh_quote(symbol)

            quote = self.quotes.get(ticker)
            if quote is not None:
                stamp = quote.fetched_at.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
                currency = f" {quote.currency}" if quote.currency else ""
                self.quote_label.setText(
                    f"価格: {quote.price:,.2f}{currency}（約15-20分遅延）取得時刻: {stamp}"
                )
            else:
                self.quote_label.setText(
                    "価格: 取得できません（約15-20分遅延）取得時刻: --"
                )
            self.portfolio_panel.refresh(self.engine, self.current_prices, self._quote_timestamps())
            if quote is not None:
                self.statusBar().showMessage(f"{ticker} を更新しました", 3000)
        except DataFetchError as exc:
            self.logger.warning("市場データ取得失敗 [%s]: %s", ticker, exc)
            self.statusBar().showMessage(str(exc), 10000)
            self.quote_label.setText("価格: 取得できません（約15-20分遅延）取得時刻: --")
        except Exception as exc:
            self.logger.exception("画面更新で予期しないエラー [%s]", ticker)
            self.statusBar().showMessage(f"更新に失敗しました: {exc}", 10000)
        finally:
            self.refresh_button.setEnabled(True)

    def _submit_order(self, side_text: str, type_text: str, quantity: int, limit_price: float) -> None:
        ticker = self.current_ticker
        if not ticker:
            self.statusBar().showMessage("先に銘柄を選択してください", 5000)
            return
        try:
            side = Side(side_text)
            order_type = OrderType(type_text)
            market_price: float | None = None
            if order_type == OrderType.MARKET:
                quote = self._refresh_quote(ticker)
                if quote is None:
                    raise TradingError("市場価格を取得できないため成行注文できません")
                market_price = quote.price
            order = self.engine.place_order(
                ticker,
                side,
                order_type,
                quantity,
                market_price=market_price,
                limit_price=limit_price if order_type == OrderType.LIMIT else None,
            )
            if order.reject_reason:
                self.statusBar().showMessage(f"注文 REJECTED: {order.reject_reason}", 10000)
                self.logger.warning("注文拒否: %s", order.reject_reason)
            elif order.status.value == "FILLED":
                self.statusBar().showMessage(
                    f"{ticker} {side.value} {quantity}株を成行約定しました", 8000
                )
            else:
                self.statusBar().showMessage(
                    f"{ticker} {side.value} {quantity}株の指値注文を受け付けました", 8000
                )
            self.portfolio_panel.refresh(self.engine, self.current_prices, self._quote_timestamps())
        except TradingError as exc:
            self.logger.warning("注文エラー [%s]: %s", ticker, exc)
            self.statusBar().showMessage(str(exc), 10000)
        except Exception as exc:
            self.logger.exception("注文処理に失敗 [%s]", ticker)
            self.statusBar().showMessage(f"注文処理に失敗しました: {exc}", 10000)

    def _export_history(self) -> None:
        try:
            path = self.engine.export_history_csv(self.project_root / "exports")
            self.statusBar().showMessage(f"CSV を出力しました: {path.name}", 8000)
            self.logger.info("取引履歴を出力: %s", path)
        except Exception as exc:
            self.logger.exception("CSV 出力に失敗")
            self.statusBar().showMessage(f"CSV 出力に失敗しました: {exc}", 10000)
