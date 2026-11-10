from datetime import datetime

import pandas as pd

from src.trading.matcher import match_limit_order
from src.trading.models import Order, OrderStatus, OrderType, Side


def make_order(side: Side, limit_price: float) -> Order:
    return Order(
        id=1,
        ticker="AAPL",
        side=side,
        type=OrderType.LIMIT,
        quantity=10,
        limit_price=limit_price,
        status=OrderStatus.OPEN,
        created_at=datetime.now(),
    )


def test_buy_limit_matches_when_low_reaches_price():
    bar = pd.Series({"Low": 99, "High": 105})
    assert match_limit_order(make_order(Side.BUY, 100), bar)
    assert not match_limit_order(make_order(Side.BUY, 98), bar)


def test_sell_limit_matches_when_high_reaches_price():
    bar = pd.Series({"Low": 95, "High": 101})
    assert match_limit_order(make_order(Side.SELL, 100), bar)
    assert not match_limit_order(make_order(Side.SELL, 102), bar)


def test_non_limit_order_never_matches():
    order = make_order(Side.BUY, 100)
    order.type = OrderType.MARKET
    assert not match_limit_order(order, {"Low": 90, "High": 110})
