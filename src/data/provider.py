"""市場データプロバイダーの抽象インターフェース。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


class DataFetchError(Exception):
    """市場データを取得できなかった理由を保持する例外。"""

    def __init__(self, reason: str, *, ticker: str | None = None) -> None:
        self.reason = str(reason)
        self.ticker = ticker
        super().__init__(self.reason)

    def __str__(self) -> str:
        return self.reason


@dataclass(slots=True)
class Quote:
    ticker: str
    price: float
    fetched_at: datetime
    currency: str = ""


class MarketDataProvider(ABC):
    """外部データソースを隠蔽する抽象基底クラス。"""

    @abstractmethod
    def get_quote(self, ticker: str) -> Quote:
        """現在取得可能な参考価格を返す。"""

    @abstractmethod
    def get_bars(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        """OHLCV の DataFrame を返す。"""
