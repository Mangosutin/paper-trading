from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.trading.engine import TradingEngine
from src.trading.models import OrderStatus, OrderType, Side


@pytest.fixture

def engine(tmp_path):
    return TradingEngine(
        tmp_path / "test.db",
        initial_cash=100_000,
        enforce_lot=True,
        fee_model="zero",
        slippage_bps=0,
    )


def test_market_buy_and_sell_update_cash_and_position(engine):
    buy = engine.place_order("AAPL", Side.BUY, OrderType.MARKET, 10, market_price=100)
    assert buy.status == OrderStatus.FILLED
    assert engine.account().cash == pytest.approx(99_000)
    position = engine.get_position("AAPL")
    assert position is not None
    assert position.quantity == 10
    assert position.average_price == pytest.approx(100)

    sell = engine.place_order("AAPL", Side.SELL, OrderType.MARKET, 4, market_price=120)
    assert sell.status == OrderStatus.FILLED
    assert engine.account().cash == pytest.approx(99_480)
    position = engine.get_position("AAPL")
    assert position is not None
    assert position.quantity == 6
    # 売却後も残存株の移動平均取得単価は変わらない。
    assert position.average_price == pytest.approx(100)


def test_buy_uses_moving_average_cost(engine):
    engine.place_order("AAPL", "BUY", "MARKET", 10, market_price=100)
    engine.place_order("AAPL", "BUY", "MARKET", 10, market_price=120)
    position = engine.get_position("AAPL")
    assert position is not None
    assert position.quantity == 20
    assert position.average_price == pytest.approx(110)


def test_rejects_japanese_order_not_in_100_share_lot(engine):
    order = engine.place_order("7203.T", "BUY", "MARKET", 10, market_price=2_000)
    assert order.status == OrderStatus.REJECTED
    assert "100株単位" in (order.reject_reason or "")
    stored = engine.orders()[-1]
    assert stored.status == OrderStatus.REJECTED
    assert stored.reject_reason == order.reject_reason
    assert engine.account().cash == pytest.approx(100_000)


def test_rejects_insufficient_buying_power(engine):
    order = engine.place_order("AAPL", "BUY", "MARKET", 100, market_price=2_000)
    assert order.status == OrderStatus.REJECTED
    assert "買付余力" in (order.reject_reason or "")
    assert engine.get_position("AAPL") is None


def test_rejects_sell_over_position(engine):
    engine.place_order("AAPL", "BUY", "MARKET", 5, market_price=100)
    order = engine.place_order("AAPL", "SELL", "MARKET", 6, market_price=100)
    assert order.status == OrderStatus.REJECTED
    assert "売却可能数量" in (order.reject_reason or "")
    assert engine.get_position("AAPL").quantity == 5


def test_limit_order_fills_only_on_bar_after_order_time(engine):
    order_time = datetime.now()
    order = engine.place_order(
        "AAPL", "BUY", "LIMIT", 10, limit_price=95
    )
    assert order.status == OrderStatus.OPEN

    old_bar = pd.Series({"Open": 100, "High": 105, "Low": 90, "Close": 95})
    old_fills = engine.process_bar("AAPL", old_bar, order.created_at - timedelta(days=1))
    assert old_fills == []
    assert engine.get_position("AAPL") is None

    new_bar_time = (order.created_at or order_time) + timedelta(days=1)
    new_bar = pd.Series({"Open": 93, "High": 100, "Low": 90, "Close": 96})
    fills = engine.process_bar("AAPL", new_bar, new_bar_time)
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(93)
    assert engine.get_position("AAPL").quantity == 10
    assert engine.orders()[-1].status == OrderStatus.FILLED


def test_slippage_is_adverse_and_fee_zero(engine):
    slipped_engine = TradingEngine(
        engine.db_path.parent / "slippage.db",
        initial_cash=100_000,
        enforce_lot=False,
        fee_model="zero",
        slippage_bps=100,
    )
    slipped_engine.place_order("AAPL", "BUY", "MARKET", 1, market_price=100)
    fill = slipped_engine.fills()[0]
    assert fill.price == pytest.approx(101)
    assert fill.fee == 0
