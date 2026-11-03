"""Batch measurement of a folder of sounds into a CSV file."""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from phonolab.core import batch
from phonolab.core.batch import MEASURES, BatchOptions


class _Signals(QObject):
    file_done = pyqtSignal(str, object)  # path, rows


class BatchDialog(QDialog):
    def __init__(self, base_options: BatchOptions, start_dir: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch measure")
        self.resize(640, 560)
        self.base_options = base_options
        self.executor: ProcessPoolExecutor | None = None
        self.futures: list[Future] = []
        self.rows: list[dict] = []
        self.output: Path | None = None
        self._signals = _Signals()
        self._signals.file_done.connect(self._on_file_done)

        self.folder = QLineEdit(start_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.tier = QLineEdit(base_options.tier)
        self.tier.setPlaceholderText("e.g. words — leave empty to measure whole files")

        form = QFormLayout()
        form.addRow("Folder:", folder_row)
        form.addRow("", self.recursive)
        form.addRow("Per interval of tier:", self.tier)

        measures = QGroupBox("Measurements (using the current analysis settings)")
        measures_layout = QVBoxLayout(measures)
        self.checks = {}
        for key, label in MEASURES.items():
            box = QCheckBox(label)
            box.setChecked(key in base_options.measures)
            measures_layout.addWidget(box)
            self.checks[key] = box

        self.progress = QProgressBar()
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(5000)
        self.run_button = QPushButton("Run…")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.run)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(measures)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)
        layout.addLayout(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with sounds", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def options(self) -> BatchOptions:
        measures = frozenset(k for k, box in self.checks.items() if box.isChecked())
        o = self.base_options
        return BatchOptions(measures, self.tier.text().strip(), o.pitch, o.formants, o.intensity, o.voice)

    @property
    def running(self) -> bool:
        return any(not f.done() for f in self.futures)

    def run(self):
        if self.running:
            self.cancel()
            return
        folder = Path(self.folder.text())
        if not folder.is_dir():
            self.log.appendPlainText("Choose a folder first.")
            return
        files = batch.find_sounds(folder, self.recursive.isChecked())
        if not files:
            self.log.appendPlainText(f"No sound files found in {folder}.")
            return
        output, _ = QFileDialog.getSaveFileName(self, "Save results", str(folder / "measurements.csv"), "CSV (*.csv)")
        if not output:
            return
        self.start(files, Path(output))

    def start(self, files: list[Path], output: Path):
        """Measure ``files`` in parallel and write ``output`` when all are done."""
        self.output = output
        self.rows = []
        self.log.clear()
        self.log.appendPlainText(f"Measuring {len(files)} files…")
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.run_button.setText("Cancel")
        workers = max(1, min(len(files), (os.cpu_count() or 2) - 1))
        self.executor = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"))
        options = self.options()
        signals = self._signals
        self.futures = []
        for path in files:
            fut = self.executor.submit(batch.measure_file, path, options)
            fut.add_done_callback(lambda f, p=str(path): self._finished(signals, p, f))
            self.futures.append(fut)

    @staticmethod
    def _finished(signals: _Signals, path: str, fut: Future):
        if fut.cancelled():
            return
        exc = fut.exception()
        rows = [{"file": Path(path).name, "folder": str(Path(path).parent), "error": str(exc)}] if exc else fut.result()
        with contextlib.suppress(RuntimeError):  # the dialog was closed meanwhile
            signals.file_done.emit(path, rows)

    def _on_file_done(self, path: str, rows: list):
        self.rows += rows
        self.progress.setValue(self.progress.value() + 1)
        errors = [r["error"] for r in rows if "error" in r]
        status = f"  ({len(rows)} rows)" if len(rows) > 1 else ""
        self.log.appendPlainText(f"{Path(path).name}{status}" + (f" — {errors[0]}" if errors else ""))
        if self.progress.value() == self.progress.maximum():
            self._complete()

    def _complete(self):
        self._shutdown()
        self.rows.sort(key=lambda r: (r.get("folder", ""), r.get("file", ""), r.get("start_s", 0)))
        try:
            n = batch.write_csv(self.rows, self.output)
        except OSError as e:
            self.log.appendPlainText(f"Could not write {self.output}: {e}")
            return
        self.log.appendPlainText(f"Done: wrote {n} rows to {self.output}")

    def cancel(self):
        for f in self.futures:
            f.cancel()
        self._shutdown()
        self.log.appendPlainText("Cancelled.")

    def _shutdown(self):
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        self.run_button.setText("Run…")

    def reject(self):
        if self.running:
            self.cancel()
        super().reject()
