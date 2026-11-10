"""SQLite を用いた paper-trading 売買エンジン。"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .matcher import match_limit_order
from .models import (
    Account,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TradingError,
)


class TradingEngine:
    """現金・注文・約定・ポジションを管理する。"""

    def __init__(
        self,
        db_path: str | Path,
        initial_cash: float = 1_000_000,
        enforce_lot: bool = True,
        fee_model: str = "zero",
        slippage_bps: float = 0,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_cash = float(initial_cash)
        self.enforce_lot = bool(enforce_lot)
        self.fee_model = str(fee_model).lower()
        self.slippage_bps = float(slippage_bps)
        if self.initial_cash < 0:
            raise ValueError("initial_cash は0以上で指定してください")
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps は0以上で指定してください")
        if self.fee_model != "zero":
            raise ValueError(f"未対応の fee_model です: {self.fee_model}")
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cash REAL NOT NULL,
                    initial_cash REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    type TEXT NOT NULL CHECK (type IN ('MARKET', 'LIMIT', 'STOP')),
                    quantity INTEGER NOT NULL,
                    limit_price REAL,
                    stop_price REAL,
                    status TEXT NOT NULL,
                    reject_reason TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id),
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    average_price REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS price_cache (
                    ticker TEXT NOT NULL,
                    period TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (ticker, period, interval)
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    ticker TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL
                );
                """
            )
            row = con.execute("SELECT id FROM account WHERE id = 1").fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO account (id, cash, initial_cash, updated_at) VALUES (1, ?, ?, ?)",
                    (self.initial_cash, self.initial_cash, datetime.now().isoformat(timespec="seconds")),
                )
            for ticker in ("7203.T", "9984.T", "AAPL"):
                con.execute(
                    "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
                    (ticker, datetime.now().isoformat(timespec="seconds")),
                )

    @staticmethod
    def _normalize_ticker(ticker: str) -> str:
        result = str(ticker).strip().upper()
        if not result or len(result) > 32 or any(ch.isspace() for ch in result):
            raise TradingError("銘柄コードが正しくありません")
        return result

    def account(self) -> Account:
        with self._connect() as con:
            row = con.execute("SELECT cash, initial_cash FROM account WHERE id = 1").fetchone()
        return Account(cash=float(row["cash"]), initial_cash=float(row["initial_cash"]))

    def positions(self) -> list[Position]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT ticker, quantity, average_price FROM positions WHERE quantity > 0 ORDER BY ticker"
            ).fetchall()
        return [Position(r["ticker"], int(r["quantity"]), float(r["average_price"])) for r in rows]

    def get_position(self, ticker: str) -> Position | None:
        ticker = self._normalize_ticker(ticker)
        with self._connect() as con:
            row = con.execute(
                "SELECT ticker, quantity, average_price FROM positions WHERE ticker = ?",
                (ticker,),
            ).fetchone()
        if row is None or int(row["quantity"]) <= 0:
            return None
        return Position(row["ticker"], int(row["quantity"]), float(row["average_price"]))

    def orders(self, statuses: tuple[OrderStatus, ...] | None = None) -> list[Order]:
        with self._connect() as con:
            if statuses:
                values = tuple(status.value for status in statuses)
                placeholders = ",".join("?" for _ in values)
                rows = con.execute(
                    f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY id",
                    values,
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM orders ORDER BY id").fetchall()
        return [Order.from_row(row) for row in rows]

    def watchlist(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute("SELECT ticker FROM watchlist ORDER BY added_at, ticker").fetchall()
        return [row["ticker"] for row in rows]

    def add_to_watchlist(self, ticker: str) -> None:
        ticker = self._normalize_ticker(ticker)
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
                (ticker, datetime.now().isoformat(timespec="seconds")),
            )

    def remove_from_watchlist(self, ticker: str) -> None:
        ticker = self._normalize_ticker(ticker)
        with self._connect() as con:
            con.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    def _fee(self, notional: float) -> float:
        if self.fee_model == "zero":
            return 0.0
        raise TradingError(f"未対応の fee_model です: {self.fee_model}")

    def _slipped_price(self, price: float, side: Side) -> float:
        factor = self.slippage_bps / 10_000.0
        adjusted = price * (1.0 + factor if side == Side.BUY else 1.0 - factor)
        return max(0.000001, adjusted)

    @staticmethod
    def _is_japanese_ticker(ticker: str) -> bool:
        return ticker.endswith(".T")

    def _reserved_sell_quantity(self, con: sqlite3.Connection, ticker: str) -> int:
        row = con.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM orders "
            "WHERE ticker = ? AND side = 'SELL' AND status = 'OPEN'",
            (ticker,),
        ).fetchone()
        return int(row["total"])

    def _reserved_buy_cash(self, con: sqlite3.Connection) -> float:
        rows = con.execute(
            "SELECT quantity, limit_price FROM orders "
            "WHERE side = 'BUY' AND type = 'LIMIT' AND status = 'OPEN'"
        ).fetchall()
        return sum(int(row["quantity"]) * float(row["limit_price"] or 0) for row in rows)

    def place_order(
        self,
        ticker: str,
        side: Side | str,
        order_type: OrderType | str,
        quantity: int,
        *,
        market_price: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> Order:
        """注文を受け付け、成行注文は指定価格で即時約定する。"""
        ticker = self._normalize_ticker(ticker)
        try:
            side = Side(side)
            order_type = OrderType(order_type)
        except ValueError as exc:
            raise TradingError("売買方向または注文種別が正しくありません") from exc
        try:
            quantity = int(quantity)
        except (TypeError, ValueError) as exc:
            raise TradingError("数量は整数で指定してください") from exc

        reason: str | None = None
        reference_price: float | None = None
        if quantity <= 0:
            reason = "注文数量は1以上で指定してください"
        elif self.enforce_lot and self._is_japanese_ticker(ticker) and quantity % 100 != 0:
            reason = "日本株の注文数量は100株単位で指定してください"
        elif order_type == OrderType.STOP:
            reason = "STOP注文はv0.1.0では未対応です"
        elif order_type == OrderType.LIMIT:
            if limit_price is None or float(limit_price) <= 0:
                reason = "指値価格は0より大きい値を指定してください"
            else:
                reference_price = float(limit_price)
        elif order_type == OrderType.MARKET:
            if market_price is None or float(market_price) <= 0:
                reason = "成行注文には有効な市場価格が必要です"
            else:
                reference_price = self._slipped_price(float(market_price), side)

        now = datetime.now()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            cash_row = con.execute("SELECT cash FROM account WHERE id = 1").fetchone()
            cash = float(cash_row["cash"])
            position_row = con.execute(
                "SELECT quantity FROM positions WHERE ticker = ?", (ticker,)
            ).fetchone()
            held_quantity = int(position_row["quantity"]) if position_row else 0

            if reason is None and side == Side.SELL:
                available = held_quantity - self._reserved_sell_quantity(con, ticker)
                if quantity > available:
                    reason = f"売却可能数量を超えています（売却可能: {max(available, 0)}株）"
            elif reason is None and side == Side.BUY and reference_price is not None:
                estimated_notional = quantity * reference_price
                estimated_total = estimated_notional + self._fee(estimated_notional)
                available_cash = cash - self._reserved_buy_cash(con)
                if estimated_total > available_cash + 1e-8:
                    reason = (
                        f"買付余力が不足しています（必要: {estimated_total:,.2f}円、"
                        f"余力: {max(available_cash, 0):,.2f}円）"
                    )

            status = OrderStatus.REJECTED if reason else OrderStatus.OPEN
            cursor = con.execute(
                "INSERT INTO orders "
                "(ticker, side, type, quantity, limit_price, stop_price, status, reject_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticker,
                    side.value,
                    order_type.value,
                    quantity,
                    float(limit_price) if limit_price is not None else None,
                    float(stop_price) if stop_price is not None else None,
                    status.value,
                    reason,
                    now.isoformat(timespec="seconds"),
                ),
            )
            order_id = int(cursor.lastrowid)
            if reason is None and order_type == OrderType.MARKET:
                self._execute_fill(
                    con,
                    order_id=order_id,
                    ticker=ticker,
                    side=side,
                    quantity=quantity,
                    execution_price=reference_price or 0.0,
                    timestamp=now,
                )
                status = OrderStatus.FILLED
                con.execute("UPDATE orders SET status = ? WHERE id = ?", (status.value, order_id))

        return Order(
            id=order_id,
            ticker=ticker,
            side=side,
            type=order_type,
            quantity=quantity,
            limit_price=float(limit_price) if limit_price is not None else None,
            stop_price=float(stop_price) if stop_price is not None else None,
            status=status,
            reject_reason=reason,
            created_at=now,
        )

    def _execute_fill(
        self,
        con: sqlite3.Connection,
        *,
        order_id: int,
        ticker: str,
        side: Side,
        quantity: int,
        execution_price: float,
        timestamp: datetime,
    ) -> Fill:
        notional = float(quantity) * float(execution_price)
        fee = self._fee(notional)
        account_row = con.execute("SELECT cash FROM account WHERE id = 1").fetchone()
        cash = float(account_row["cash"])
        position_row = con.execute(
            "SELECT quantity, average_price FROM positions WHERE ticker = ?", (ticker,)
        ).fetchone()
        old_quantity = int(position_row["quantity"]) if position_row else 0
        old_average = float(position_row["average_price"]) if position_row else 0.0

        if side == Side.BUY:
            total_cost = notional + fee
            if total_cost > cash + 1e-8:
                raise TradingError("約定時に買付余力が不足しました")
            new_quantity = old_quantity + quantity
            new_average = (
                (old_quantity * old_average + quantity * execution_price) / new_quantity
                if new_quantity
                else 0.0
            )
            new_cash = cash - total_cost
            con.execute(
                "INSERT INTO positions (ticker, quantity, average_price) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET quantity = excluded.quantity, "
                "average_price = excluded.average_price",
                (ticker, new_quantity, new_average),
            )
        else:
            if quantity > old_quantity:
                raise TradingError("約定時に保有数量が不足しました")
            new_quantity = old_quantity - quantity
            new_average = old_average if new_quantity else 0.0
            new_cash = cash + notional - fee
            if new_quantity:
                con.execute(
                    "UPDATE positions SET quantity = ?, average_price = ? WHERE ticker = ?",
                    (new_quantity, new_average, ticker),
                )
            else:
                con.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))

        con.execute(
            "UPDATE account SET cash = ?, updated_at = ? WHERE id = 1",
            (new_cash, timestamp.isoformat(timespec="seconds")),
        )
        cursor = con.execute(
            "INSERT INTO fills (order_id, ticker, side, quantity, price, fee, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                ticker,
                side.value,
                quantity,
                execution_price,
                fee,
                timestamp.isoformat(timespec="seconds"),
            ),
        )
        return Fill(
            id=int(cursor.lastrowid),
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=execution_price,
            fee=fee,
            timestamp=timestamp,
        )

    def process_bar(self, ticker: str, bar: Any, bar_timestamp: datetime | None = None) -> list[Fill]:
        """日足バーで、注文後に始まったバーだけを使って指値を判定する。"""
        # TODO(v0.2.0): STOP 注文の自動監視・トリガー判定を実装する。
        ticker = self._normalize_ticker(ticker)
        if bar_timestamp is None:
            timestamp_value = getattr(bar, "name", None)
            if timestamp_value is not None:
                try:
                    bar_timestamp = timestamp_value.to_pydatetime()
                except AttributeError:
                    bar_timestamp = timestamp_value
            else:
                bar_timestamp = datetime.now()
        if not isinstance(bar_timestamp, datetime):
            bar_timestamp = datetime.fromisoformat(str(bar_timestamp))
        if bar_timestamp.tzinfo is not None:
            bar_timestamp = bar_timestamp.replace(tzinfo=None)

        fills: list[Fill] = []
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                "SELECT * FROM orders WHERE ticker = ? AND type = 'LIMIT' AND status = 'OPEN' "
                "ORDER BY id",
                (ticker,),
            ).fetchall()
            for row in rows:
                order = Order.from_row(row)
                if order.created_at and bar_timestamp <= order.created_at:
                    continue
                if not match_limit_order(order, bar):
                    continue
                # ギャップ時は有利な寄付価格を使い、スリッページ後も指値を超えない。
                open_price = float(bar["Open"] if "Open" in bar else bar.open)
                limit = float(order.limit_price or 0)
                base_price = min(open_price, limit) if order.side == Side.BUY else max(open_price, limit)
                slipped = self._slipped_price(base_price, order.side)
                execution_price = min(slipped, limit) if order.side == Side.BUY else max(slipped, limit)
                try:
                    fill = self._execute_fill(
                        con,
                        order_id=int(order.id or 0),
                        ticker=ticker,
                        side=order.side,
                        quantity=order.quantity,
                        execution_price=execution_price,
                        timestamp=bar_timestamp,
                    )
                except TradingError as exc:
                    con.execute(
                        "UPDATE orders SET status = ?, reject_reason = ? WHERE id = ?",
                        (OrderStatus.REJECTED.value, str(exc), order.id),
                    )
                    continue
                con.execute(
                    "UPDATE orders SET status = ? WHERE id = ?",
                    (OrderStatus.FILLED.value, order.id),
                )
                fills.append(fill)
        return fills

    def process_bars(self, ticker: str, bars: Any) -> list[Fill]:
        """DataFrame の各バーを古い順に処理する。"""
        all_fills: list[Fill] = []
        if bars is None or getattr(bars, "empty", True):
            return all_fills
        for timestamp, bar in bars.iterrows():
            try:
                bar_time = timestamp.to_pydatetime()
            except AttributeError:
                bar_time = timestamp
            all_fills.extend(self.process_bar(ticker, bar, bar_time))
        return all_fills

    def cancel_order(self, order_id: int) -> bool:
        with self._connect() as con:
            cursor = con.execute(
                "UPDATE orders SET status = ? WHERE id = ? AND status = ?",
                (OrderStatus.CANCELLED.value, int(order_id), OrderStatus.OPEN.value),
            )
        return cursor.rowcount > 0

    def fills(self) -> list[Fill]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM fills ORDER BY timestamp, id").fetchall()
        return [
            Fill(
                id=int(row["id"]),
                order_id=int(row["order_id"]),
                ticker=row["ticker"],
                side=Side(row["side"]),
                quantity=int(row["quantity"]),
                price=float(row["price"]),
                fee=float(row["fee"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    def export_history_csv(self, export_dir: str | Path) -> Path:
        """約定履歴を日時付き CSV として出力する。"""
        destination = Path(export_dir)
        destination.mkdir(parents=True, exist_ok=True)
        output_path = destination / f"trade_history_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with self._connect() as con:
            rows = con.execute(
                "SELECT f.id, f.order_id, f.timestamp, f.ticker, f.side, f.quantity, "
                "f.price, f.fee, o.type FROM fills f JOIN orders o ON o.id = f.order_id "
                "ORDER BY f.timestamp, f.id"
            ).fetchall()
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["fill_id", "order_id", "timestamp", "ticker", "side", "order_type", "quantity", "price", "fee", "gross_amount"]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["id"], row["order_id"], row["timestamp"], row["ticker"],
                        row["side"], row["type"], row["quantity"], row["price"],
                        row["fee"], row["quantity"] * row["price"],
                    ]
                )
        return output_path
