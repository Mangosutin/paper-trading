"""SQLite の日足価格キャッシュ。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


class PriceCache:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)

    def _ensure_table(self) -> None:
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS price_cache ("
                "ticker TEXT NOT NULL, period TEXT NOT NULL, interval TEXT NOT NULL, "
                "fetched_at TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "PRIMARY KEY (ticker, period, interval))"
            )

    def get(self, ticker: str, period: str, interval: str) -> tuple[pd.DataFrame, datetime] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT fetched_at, payload_json FROM price_cache "
                "WHERE ticker = ? AND period = ? AND interval = ?",
                (ticker, period, interval),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[1])
            frame = pd.DataFrame(payload["data"], columns=payload["columns"])
            frame.index = pd.to_datetime(payload["index"])
            fetched_at = datetime.fromisoformat(row[0])
            return frame, fetched_at
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(self, ticker: str, period: str, interval: str, frame: pd.DataFrame) -> None:
        payload = {
            "columns": [str(column) for column in frame.columns],
            "index": [stamp.isoformat() for stamp in pd.to_datetime(frame.index)],
            "data": frame.astype(object).where(pd.notna(frame), None).values.tolist(),
        }
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        with self._connect() as con:
            con.execute(
                "INSERT INTO price_cache (ticker, period, interval, fetched_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(ticker, period, interval) DO UPDATE SET "
                "fetched_at = excluded.fetched_at, payload_json = excluded.payload_json",
                (
                    ticker,
                    period,
                    interval,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    serialized,
                ),
            )
