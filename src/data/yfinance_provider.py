"""yfinance を使用する市場データプロバイダー。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf

from .provider import DataFetchError, MarketDataProvider, Quote


class YFinanceProvider(MarketDataProvider):
    """Yahoo Finance の非公式データ取得手段を利用する。"""

    @staticmethod
    def _flatten_columns(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
        result = frame.copy()
        if isinstance(result.columns, pd.MultiIndex):
            level0 = result.columns.get_level_values(0)
            level1 = result.columns.get_level_values(-1)
            if ticker in level0:
                result = result[ticker]
            elif ticker in level1:
                result = result.xs(ticker, axis=1, level=-1)
            else:
                result.columns = level0
        return result

    def get_quote(self, ticker: str) -> Quote:
        symbol = str(ticker).strip().upper()
        if not symbol:
            raise DataFetchError("銘柄コードが空です")
        try:
            instrument = yf.Ticker(symbol)
            price: float | None = None
            currency = ""

            # fast_info を優先し、利用できない場合は直近の日足終値にフォールバックする。
            try:
                info: Any = instrument.fast_info
                if info:
                    price_value = info.get("last_price") if hasattr(info, "get") else None
                    if price_value is not None and pd.notna(price_value):
                        price = float(price_value)
                    currency_value = info.get("currency") if hasattr(info, "get") else None
                    currency = str(currency_value or "")
            except Exception:
                price = None

            if price is None or price <= 0:
                history = instrument.history(period="5d", interval="1d", auto_adjust=False)
                if history is None or history.empty:
                    raise DataFetchError(
                        f"{symbol}: 価格データが空でした（fast_info と直近5日の日足）",
                        ticker=symbol,
                    )
                close = pd.to_numeric(history.get("Close"), errors="coerce").dropna()
                if close.empty:
                    raise DataFetchError(f"{symbol}: 有効な終値がありません", ticker=symbol)
                price = float(close.iloc[-1])
            if price <= 0:
                raise DataFetchError(f"{symbol}: 価格が0以下です", ticker=symbol)
            return Quote(
                ticker=symbol,
                price=price,
                fetched_at=datetime.now().astimezone(),
                currency=currency,
            )
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(f"{symbol}: 価格取得に失敗しました: {exc}", ticker=symbol) from exc

    def get_bars(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        symbol = str(ticker).strip().upper()
        if not symbol:
            raise DataFetchError("銘柄コードが空です")
        try:
            frame = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
                group_by="column",
            )
            if frame is None or frame.empty:
                raise DataFetchError(
                    f"{symbol}: ローソク足データが空でした（period={period}, interval={interval}）",
                    ticker=symbol,
                )
            frame = self._flatten_columns(frame, symbol)
            required = ("Open", "High", "Low", "Close")
            missing = [column for column in required if column not in frame.columns]
            if missing:
                raise DataFetchError(
                    f"{symbol}: OHLC 列が不足しています: {', '.join(missing)}",
                    ticker=symbol,
                )
            if "Volume" not in frame.columns:
                frame["Volume"] = 0
            frame = frame.loc[:, ["Open", "High", "Low", "Close", "Volume"]].copy()
            for column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
            if frame.empty:
                raise DataFetchError(f"{symbol}: 有効な OHLC データがありません", ticker=symbol)
            frame.index = pd.to_datetime(frame.index)
            frame = frame.sort_index()
            return frame
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(
                f"{symbol}: ローソク足取得に失敗しました: {exc}", ticker=symbol
            ) from exc
