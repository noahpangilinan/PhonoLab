"""Dock showing the spectrum (slice or LTAS) of the selection or around the cursor."""

from __future__ import annotations

import contextlib
import logging

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from phonolab.core import spectrum
from phonolab.core.queries import fmt
from phonolab.core.spectrum import SpectrumResult, SpectrumSettings
from phonolab.ui.theme import COLORS, style_plot

log = logging.getLogger(__name__)

UPDATE_DELAY_MS = 120
MAX_SLICE_SECONDS = 30.0  # longer selections are better summarised by an LTAS


class SpectrumPanel(QDockWidget):
    log_message = pyqtSignal(str)
    settings_requested = pyqtSignal()

    def __init__(self, settings: SpectrumSettings, parent=None):
        super().__init__("Spectrum", parent)
        self.setObjectName("spectrum_dock")
        self.settings = settings
        self.editor = None
        self.result: SpectrumResult | None = None
        self._cpps_range = (0.0, 0.0)

        body = QWidget()
        layout = QVBoxLayout(body)
        top = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("Spectral slice", "slice")
        self.mode.addItem("Long-term average (LTAS)", "ltas")
        self.mode.addItem("LPC spectrum", "lpc")
        self.mode.addItem("Excitation (Bark)", "excitation")
        self.mode.currentIndexChanged.connect(self.schedule_update)
        settings_button = QPushButton("Settings…")
        settings_button.clicked.connect(self.settings_requested)
        top.addWidget(self.mode, 1)
        top.addWidget(settings_button)
        layout.addLayout(top)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(170)  # grows with the dock; small enough to never overlap the summary
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Frequency (Hz)")
        self.plot.setLabel("left", "Level (dB)")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.getAxis("bottom").setHeight(42)  # room for tick labels and the axis title
        self.curve = self.plot.plot(pen=pg.mkPen(COLORS["waveform"], width=1.5))
        layout.addWidget(self.plot, 1)
        layout.addSpacing(4)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary)
        buttons = QHBoxLayout()
        log_button = QPushButton("Log measurements")
        log_button.clicked.connect(self.log_measurements)
        cpps_button = QPushButton("Measure CPPS")
        cpps_button.setToolTip("Smoothed cepstral peak prominence of the same range")
        cpps_button.clicked.connect(self.log_cpps)
        buttons.addStretch()
        buttons.addWidget(cpps_button)
        buttons.addWidget(log_button)
        layout.addLayout(buttons)
        self.setWidget(body)

        self._timer = QTimer(self, singleShot=True, interval=UPDATE_DELAY_MS)
        self._timer.timeout.connect(self.update_spectrum)
        self.visibilityChanged.connect(lambda visible: visible and self.schedule_update())

    def retheme(self):
        style_plot(self.plot)
        self.curve.setPen(pg.mkPen(COLORS["waveform"], width=1.5))

    def set_editor(self, editor) -> None:
        if self.editor is not None:
            for sig in (self.editor.axis.cursor_changed, self.editor.axis.selection_changed):
                with contextlib.suppress(TypeError, RuntimeError):
                    sig.disconnect(self.schedule_update)
            with contextlib.suppress(TypeError, RuntimeError):
                self.editor.manager.job_done.disconnect(self._on_job_done)
                self.editor.manager.job_failed.disconnect(self._on_job_failed)
        self.editor = editor
        if editor is not None:
            editor.axis.cursor_changed.connect(self.schedule_update)
            editor.axis.selection_changed.connect(self.schedule_update)
            editor.manager.job_done.connect(self._on_job_done)
            editor.manager.job_failed.connect(self._on_job_failed)
        self.schedule_update()

    def set_settings(self, settings: SpectrumSettings) -> None:
        self.settings = settings
        self.schedule_update()

    def schedule_update(self, *_):
        if self.isVisible():
            self._timer.start()

    def _range(self):
        e = self.editor
        return spectrum.slice_range(e.doc.analysis_sound, self.settings, e.axis.cursor, e.axis.selection)

    def update_spectrum(self):
        self.result = None
        self.curve.setData([], [])
        if self.editor is None:
            self.summary.setText("")
            return
        start, end = self._range()
        kind = self.mode.currentData()
        if end - start < 0.003:
            self.summary.setText("Select a longer stretch or move the cursor into the sound.")
            return
        if kind == "slice" and end - start > MAX_SLICE_SECONDS:
            self.summary.setText(f"Selections over {MAX_SLICE_SECONDS:.0f} s: switch to LTAS.")
            return
        fn = {
            "slice": spectrum.compute_slice,
            "ltas": spectrum.compute_ltas,
            "lpc": spectrum.compute_lpc,
            "excitation": spectrum.compute_excitation,
        }[kind]
        try:
            r = fn(self.editor.doc.analysis_sound, self.settings, start, end)
        except Exception as e:  # Praat raises on degenerate ranges
            log.info("spectrum failed: %s", e)
            self.summary.setText(f"No spectrum: {e}")
            return
        self.result = r
        self.curve.setData(r.frequencies, r.db)
        bark = kind == "excitation"
        self.plot.setXRange(0, 25.6 if bark else self.settings.max_frequency, padding=0)
        self.plot.setLabel("bottom", "Place (Bark)" if bark else "Frequency (Hz)")
        summary = f"{self.mode.currentText()} {start:.3f}–{end:.3f} s"
        if not np.isnan(r.centre_of_gravity):  # LPC and excitation have no moments
            summary += (
                f" · centre of gravity {fmt(r.centre_of_gravity, 'Hz', 0)} · sd {fmt(r.standard_deviation, 'Hz', 0)} · "
                f"skewness {fmt(r.skewness, '', 2)} · kurtosis {fmt(r.kurtosis, '', 2)}"
            )
        self.summary.setText(summary)

    def log_measurements(self):
        if self.result is None:
            self.update_spectrum()
        r = self.result
        if r is None:
            return
        self.log_message.emit(
            f"Spectral moments {r.start:.4f}–{r.end:.4f} s: centre of gravity {fmt(r.centre_of_gravity, 'Hz', 1)}, "
            f"sd {fmt(r.standard_deviation, 'Hz', 1)}, skewness {fmt(r.skewness, '', 3)}, "
            f"kurtosis {fmt(r.kurtosis, '', 3)}"
        )

    def log_cpps(self):
        """Measure CPPS in a worker: it takes about a third of the sound's duration."""
        if self.editor is None:
            return
        self._cpps_range = self.editor.axis.selection or self.editor.axis.view
        self.editor.manager.submit("cpps", spectrum.cpps, *self._cpps_range)

    def _on_job_done(self, key: str, value):
        if key == "cpps":
            start, end = self._cpps_range
            self.log_message.emit(f"CPPS {start:.4f}–{end:.4f} s: {fmt(value, 'dB')}")

    def _on_job_failed(self, key: str, message: str):
        if key == "cpps":  # too short, silent, etc.
            start, end = self._cpps_range
            self.log_message.emit(f"CPPS {start:.4f}–{end:.4f} s: --undefined-- ({message})")
