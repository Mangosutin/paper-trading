"""売買エンジンで使用するデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"  # v0.2.0以降で自動監視を実装予定


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class Order:
    id: int | None
    ticker: str
    side: Side
    type: OrderType
    quantity: int
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.OPEN
    reject_reason: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Any) -> "Order":
        created = datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        return cls(
            id=row["id"],
            ticker=row["ticker"],
            side=Side(row["side"]),
            type=OrderType(row["type"]),
            quantity=int(row["quantity"]),
            limit_price=row["limit_price"],
            stop_price=row["stop_price"],
            status=OrderStatus(row["status"]),
            reject_reason=row["reject_reason"],
            created_at=created,
        )


@dataclass(slots=True)
class Fill:
    id: int | None
    order_id: int
    ticker: str
    side: Side
    quantity: int
    price: float
    fee: float
    timestamp: datetime


@dataclass(slots=True)
class Position:
    ticker: str
    quantity: int
    average_price: float


@dataclass(slots=True)
class Account:
    cash: float
    initial_cash: float


class TradingError(Exception):
    """注文処理または口座処理で発生したエラー。"""
