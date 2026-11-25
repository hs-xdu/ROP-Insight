"""Application entry point."""

import sys
import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from rop_insight.ui.main_window import MainWindow
from rop_insight.services.analysis_config import load_config, ConfigError
from rop_insight.services.analysis_controller import AnalysisController
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QMessageBox
from rop_insight.inference.vascx import VascXAdapter
from rop_insight.inference.a6 import A6Adapter
from rop_insight.inference.imported_ridge import ImportedRidgeAdapter


def main():
    parser = argparse.ArgumentParser(description="ROP-Insight")
    parser.add_argument("--config", type=Path, help="分析模块 JSON 配置")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("ROP-Insight")
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "analysis.log", maxBytes=2_000_000,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger("rop_insight.analysis").addHandler(handler)
        logging.getLogger("rop_insight.analysis").setLevel(logging.INFO)
    except OSError:
        logging.basicConfig(level=logging.INFO)
    try:
        registry = {"vascx_native": VascXAdapter, "a6_shenzhen": A6Adapter, "imported_ridge": ImportedRidgeAdapter}
        controller = AnalysisController(config=load_config(args.config, registry) if args.config else None,
                                        registry=registry)
    except ConfigError as exc:
        QMessageBox.critical(None, "分析配置错误", str(exc))
        return 1
    window = MainWindow(controller=controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
