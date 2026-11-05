"""A script editor that runs Praat or Python scripts on the current sound."""

from __future__ import annotations

import contextlib
from concurrent.futures import Future
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
)

from phonolab.core import scripting
from phonolab.core.sound import LongSoundError
from phonolab.ui import workers

WORKER = "script"


class _Signals(QObject):
    finished = pyqtSignal(object)  # ScriptResult


class ScriptWindow(QDialog):
    """Non-modal: stays open while you work in the editor. Runs scripts in a worker process."""

    # (ScriptResult, editor it ran on)
    result_ready = pyqtSignal(object, object)

    def __init__(self, current_editor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Script")
        self.resize(760, 620)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self.current_editor = current_editor  # callable -> SoundEditor | None
        self.path: Path | None = None
        self._future: Future | None = None
        self._target = None
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.language = QComboBox()
        self.language.addItem("Praat script", "praat")
        self.language.addItem("Python", "python")
        self.language.currentIndexChanged.connect(self._language_changed)
        examples = QToolButton(text="Examples")
        examples.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(examples)
        for name in scripting.EXAMPLES:
            menu.addAction(name, lambda n=name: self._load_example(n))
        examples.setMenu(menu)
        open_button = QPushButton("Open…")
        open_button.clicked.connect(self.open_script)
        save_button = QPushButton("Save…")
        save_button.clicked.connect(self.save_script)
        top = QHBoxLayout()
        top.addWidget(self.language)
        top.addWidget(examples)
        top.addStretch()
        top.addWidget(open_button)
        top.addWidget(save_button)

        self.editor = QPlainTextEdit()
        self.editor.setFont(mono)
        self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.output = QPlainTextEdit(readOnly=True)
        self.output.setFont(mono)
        self.output.setPlaceholderText("Output (writeInfoLine / print) appears here.")
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.output)
        splitter.setSizes([400, 160])

        self.arguments = QLineEdit()
        self.arguments.setPlaceholderText('Form arguments, e.g.  1000 "some text"')
        self.args_label = QLabel("Arguments:")
        self.run_button = QPushButton("Run  (Ctrl+Enter)")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.run_or_stop)
        bottom = QHBoxLayout()
        bottom.addWidget(self.args_label)
        bottom.addWidget(self.arguments, 1)
        bottom.addWidget(self.run_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self.run_or_stop)
        self._language_changed()

    # ------------------------------------------------------------------ files

    def _language_changed(self):
        praat = self.language.currentData() == "praat"
        self.arguments.setVisible(praat)
        self.args_label.setVisible(praat)
        if not self.editor.toPlainText().strip() and not praat:
            self.editor.setPlainText(scripting.PYTHON_HELP)

    def _load_example(self, name: str):
        lang, code = scripting.EXAMPLES[name]
        self.language.setCurrentIndex(self.language.findData(lang))
        self.editor.setPlainText(code)
        self.path = None

    def open_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open script", "", "Scripts (*.praat *.py);;All files (*)")
        if not path:
            return
        self.path = Path(path)
        self.editor.setPlainText(self.path.read_text(encoding="utf-8", errors="replace"))
        lang = "python" if self.path.suffix == ".py" else "praat"
        self.language.setCurrentIndex(self.language.findData(lang))
        self.setWindowTitle(f"Script — {self.path.name}")

    def save_script(self):
        suffix = ".py" if self.language.currentData() == "python" else ".praat"
        default = str(self.path) if self.path else f"script{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, "Save script", default, f"Script (*{suffix});;All files (*)")
        if path:
            self.path = Path(path)
            self.path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self.setWindowTitle(f"Script — {self.path.name}")

    # ------------------------------------------------------------------ running

    def run_or_stop(self):
        if self._future is not None and not self._future.done():
            workers.kill_worker(WORKER)
            self._future = None
            self.output.appendPlainText("\nStopped.")
            self.run_button.setText("Run  (Ctrl+Enter)")
            return
        editor = self.current_editor()
        if editor is None:
            QMessageBox.information(self, "Script", "Open a sound first: scripts run on the current sound.")
            return
        doc = editor.doc
        code = self.editor.toPlainText()
        sound, textgrid = doc.sound, doc.textgrid
        if sound.is_long:  # scripts need the sound in memory, so they get the selection or the visible part
            try:
                sound, textgrid = sound.extract(*(editor.axis.selection or editor.axis.view)), None
            except LongSoundError as e:
                QMessageBox.information(self, "Script", str(e))
                return
        if self.language.currentData() == "praat":
            fn, args = scripting.run_praat, (sound, textgrid, code, self.arguments.text())
        else:
            fn, args = scripting.run_python, (sound, textgrid, code)
        where = "the selected part of a long recording" if doc.sound.is_long else doc.sound.name
        self.output.setPlainText(f"Running on {where}…")
        self.run_button.setText("Stop")
        self._target = editor
        self._future = workers.run_in_worker(WORKER, fn, *args)
        signals = self._signals

        def done(f: Future):
            if f.cancelled():
                return
            exc = f.exception()
            result = scripting.ScriptResult(error=f"Worker failed: {exc}") if exc else f.result()
            with contextlib.suppress(RuntimeError):  # window closed meanwhile
                signals.finished.emit(result)

        self._future.add_done_callback(done)

    def _on_finished(self, result: scripting.ScriptResult):
        if self._future is None:  # stopped
            return
        self._future = None
        self.run_button.setText("Run  (Ctrl+Enter)")
        text = result.output
        if result.error:
            text += ("\n" if text else "") + f"Error: {result.error}"
        notes = [f"Opened {name}" for name, _, _ in result.sounds]
        if result.textgrid is not None:
            notes.append("Updated the TextGrid")
        self.output.setPlainText("\n".join(filter(None, [text.rstrip(), *notes])) or "(no output)")
        self.result_ready.emit(result, self._target)
