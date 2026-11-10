"""アプリケーションの組み立て。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6 import QtWidgets

from src.data.cache import PriceCache
from src.data.provider import MarketDataProvider
from src.data.yfinance_provider import YFinanceProvider
from src.trading.engine import TradingEngine
from src.ui.main_window import MainWindow


def load_config(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise RuntimeError(f"設定ファイルがありません: {config_path}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError("config.yaml のルートは YAML オブジェクトである必要があります")

    # 仕様の既定値を補完し、設定ファイルの一部省略にも対応する。
    defaults: dict[str, Any] = {
        "account": {"initial_cash": 1_000_000},
        "data": {"provider": "yfinance", "poll_seconds": 60, "cache_daily": True},
        "trading": {"enforce_lot": True, "fee_model": "zero", "slippage_bps": 0},
        "screener": {"enabled": False},
    }
    for section, values in defaults.items():
        section_data = loaded.setdefault(section, {})
        if not isinstance(section_data, dict):
            raise RuntimeError(f"config.yaml の {section} はオブジェクトである必要があります")
        for key, value in values.items():
            section_data.setdefault(key, value)
    return loaded


def create_provider(config: dict[str, Any]) -> MarketDataProvider:
    provider_name = str(config.get("data", {}).get("provider", "yfinance")).lower()
    if provider_name != "yfinance":
        raise RuntimeError(f"未対応の data.provider です: {provider_name}")
    return YFinanceProvider()


def create_main_window(project_root: Path, config: dict[str, Any]) -> MainWindow:
    db_path = project_root / "data" / "paper_trading.db"
    trading_config = config.get("trading", {})
    engine = TradingEngine(
        db_path=db_path,
        initial_cash=float(config.get("account", {}).get("initial_cash", 1_000_000)),
        enforce_lot=bool(trading_config.get("enforce_lot", True)),
        fee_model=str(trading_config.get("fee_model", "zero")),
        slippage_bps=float(trading_config.get("slippage_bps", 0)),
    )
    cache = PriceCache(db_path)
    provider = create_provider(config)
    return MainWindow(
        engine=engine,
        provider=provider,
        cache=cache,
        config=config,
        project_root=project_root,
    )


def run_application(app: QtWidgets.QApplication, project_root: Path) -> int:
    config = load_config(project_root / "config.yaml")
    window = create_main_window(project_root, config)
    window.show()
    return app.exec()
