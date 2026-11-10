"""paper-trading 起動モジュール。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6 import QtWidgets

from src import APP_VERSION
from src.app import run_application


def configure_logging(project_root: Path) -> None:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    configure_logging(project_root)
    logger = logging.getLogger(__name__)
    logger.info("paper-trading v%s starting", APP_VERSION)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("paper-trading")
    app.setApplicationVersion(APP_VERSION)
    try:
        return run_application(app, project_root)
    except Exception as exc:
        logger.exception("アプリケーションを起動できませんでした")
        QtWidgets.QMessageBox.critical(
            None,
            "起動エラー",
            f"アプリケーションを起動できませんでした。\n\n{exc}\n\n詳細は logs/app.log を確認してください。",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
