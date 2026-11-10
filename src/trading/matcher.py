"""日足 OHLC と指値注文の約定条件を判定する。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import Order, OrderType, Side


def match_limit_order(order: Order, bar: Mapping[str, Any] | Any) -> bool:
    """指定バーの安値・高値が指値に到達したかを返す。"""
    if order.type != OrderType.LIMIT or order.limit_price is None:
        return False

    try:
        low = float(bar["Low"] if "Low" in bar else bar.low)
        high = float(bar["High"] if "High" in bar else bar.high)
    except (KeyError, AttributeError, TypeError, ValueError):
        return False

    if order.side == Side.BUY:
        return low <= float(order.limit_price)
    return high >= float(order.limit_price)


class LimitOrderMatcher:
    """エンジンから独立した指値注文マッチャー。"""

    @staticmethod
    def matches(order: Order, bar: Mapping[str, Any] | Any) -> bool:
        return match_limit_order(order, bar)
