"""Application start-up: Qt setup, logging, crash reporting."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs
from PyQt6.QtWidgets import QApplication, QMessageBox

from phonolab import __version__
from phonolab.ui.theme import configure_pyqtgraph

log = logging.getLogger("phonolab")


def setup_logging() -> Path:
    log_dir = Path(platformdirs.user_log_dir("PhonoLab", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "phonolab.log"
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return log_file


def _install_excepthook(log_file: Path) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", text)
        if QApplication.instance() is not None:
            box = QMessageBox(
                QMessageBox.Icon.Critical,
                "PhonoLab error",
                f"Something went wrong: {exc}\n\nDetails were written to {log_file}.",
            )
            box.setDetailedText(text)
            box.exec()

    sys.excepthook = hook


def create_app(argv: list[str]) -> QApplication:
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("PhonoLab")
    app.setOrganizationName("PhonoLab")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    configure_pyqtgraph()
    return app


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    log_file = setup_logging()
    _install_excepthook(log_file)
    app = create_app(argv)
    log.info("PhonoLab %s starting", __version__)

    from phonolab.ui import workers
    from phonolab.ui.main_window import MainWindow

    workers.warm_up()
    window = MainWindow()
    window.show()
    for path in argv[1:]:
        window.open_path(path)
    return app.exec()
