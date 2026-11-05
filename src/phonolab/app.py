"""Application start-up: Qt setup, logging, crash reporting."""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs
from PyQt6.QtCore import QEvent, QObject, QSettings
from PyQt6.QtWidgets import QApplication, QMessageBox

from phonolab import __version__
from phonolab.core import praat_engine
from phonolab.core.settings import Preferences
from phonolab.core.sound import remove_stale_long_files
from phonolab.ui.icon import app_icon
from phonolab.ui.theme import apply_theme

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


class FileOpenFilter(QObject):
    """Opens files sent by macOS (double-click in Finder, drop on the Dock icon)."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.FileOpen:
            self.window.open_path(ev.file())
            return True
        return super().eventFilter(obj, ev)


def create_app(argv: list[str]) -> QApplication:
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("PhonoLab")
    app.setOrganizationName("PhonoLab")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    apply_theme(app, Preferences(QSettings()).theme())
    return app


def engine_info() -> int:
    """Self-check for builds: prove the bundled Praat runs. Windowed builds have no stdout, so log too."""
    try:
        result = praat_engine.run_script("writeInfoLine: 6 * 7").strip()
    except praat_engine.PraatEngineError as e:
        result = f"failed: {e}"
    line = f"{praat_engine.engine_description()}; script result: {result}"
    log.info("Engine check: %s", line)
    if sys.stdout is not None:
        print(line)
    return 0 if result == "42" else 1


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    log_file = setup_logging()
    remove_stale_long_files()
    if "--engine-info" in argv:
        return engine_info()
    _install_excepthook(log_file)
    app = create_app(argv)
    log.info("PhonoLab %s starting; measurements by %s", __version__, praat_engine.engine_description())

    from phonolab.ui import workers
    from phonolab.ui.main_window import MainWindow

    workers.warm_up()
    window = MainWindow()
    file_open_filter = FileOpenFilter(window, app)
    app.installEventFilter(file_open_filter)
    window.show()
    for path in argv[1:]:
        window.open_path(path)
    return app.exec()
