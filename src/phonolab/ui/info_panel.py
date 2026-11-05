"""Dock with live values under the mouse (or cursor) and statistics of the selection."""

from __future__ import annotations

import contextlib

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from phonolab.core import queries
from phonolab.core.queries import fmt

READOUT_ROWS = ("Time", "Amplitude", "Frequency", "Pitch", "Voicing", "F1", "F2", "F3", "F4", "Intensity")
SELECTION_ROWS = ("Start", "End", "Duration", "Voiced", "Mean pitch", "Mean F1", "Mean F2", "Mean intensity")


class InfoPanel(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Measurements", parent)
        self.setObjectName("info_dock")
        self.editor = None
        self._hover = (None, None)
        body = QWidget()
        layout = QVBoxLayout(body)
        self.readout_box, self.readout = self._group("Under the mouse", READOUT_ROWS)
        self.selection_box, self.selection = self._group("Selection", SELECTION_ROWS)
        layout.addWidget(self.readout_box)
        layout.addWidget(self.selection_box)
        layout.addStretch()
        self.setWidget(body)
        self.setMinimumWidth(220)

    @staticmethod
    def _group(title, rows):
        box = QGroupBox(title)
        form = QFormLayout(box)
        labels = {}
        for row in rows:
            value = QLabel("")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(row + ":", value)
            labels[row] = value
        return box, labels

    def set_editor(self, editor) -> None:
        if self.editor is not None:
            for sig, slot in self._connections():
                # TypeError: never connected; RuntimeError: editor already deleted.
                with contextlib.suppress(TypeError, RuntimeError):
                    sig.disconnect(slot)
        self.editor = editor
        if editor is not None:
            for sig, slot in self._connections():
                sig.connect(slot)
        self._hover = (None, None)
        self.refresh()

    def _connections(self):
        e = self.editor
        return [
            (e.axis.hover_changed, self._on_hover),
            (e.axis.cursor_changed, self._on_cursor),
            (e.axis.selection_changed, self._on_selection),
            (e.manager.result_ready, self._on_result),
        ]

    def _on_hover(self, t, freq):
        self._hover = (t, freq)
        self._update_readout()

    def _on_cursor(self, _t):
        if self._hover[0] is None:
            self._update_readout()

    def _on_selection(self, _sel):
        self._update_selection()

    def _on_result(self, name):
        if name != "spectrogram":
            self.refresh()

    def refresh(self):
        self._update_readout()
        self._update_selection()

    def _update_readout(self):
        if self.editor is None:
            values = {}
        else:
            t, freq = self._hover
            if t is None:
                t, freq = self.editor.axis.cursor, None
                self.readout_box.setTitle("At the cursor")
            else:
                self.readout_box.setTitle("Under the mouse")
            values = self.editor.readout(t, freq)
        for row, label in self.readout.items():
            label.setText(values.get(row, ""))

    def _update_selection(self):
        e = self.editor
        sel = e.axis.selection if e else None
        values = {}
        if sel:
            a, b = sel
            values = {"Start": f"{a:.4f} s", "End": f"{b:.4f} s", "Duration": f"{b - a:.4f} s"}
            res = e.manager.results
            if "voicing" in res:
                values["Voiced"] = f"{100 * res['voicing'].voiced_fraction(a, b):.0f} %"
            if "pitch" in res:
                values["Mean pitch"] = fmt(queries.pitch_stats(res["pitch"], a, b).mean, "Hz", 1)
            if "formants" in res:
                stats = queries.formant_stats(res["formants"], a, b)
                values["Mean F1"] = fmt(stats[0].mean, "Hz", 0)
                if len(stats) > 1:
                    values["Mean F2"] = fmt(stats[1].mean, "Hz", 0)
            if "intensity" in res:
                values["Mean intensity"] = fmt(queries.intensity_stats(res["intensity"], a, b).mean, "dB", 1)
        for row, label in self.selection.items():
            label.setText(values.get(row, ""))
