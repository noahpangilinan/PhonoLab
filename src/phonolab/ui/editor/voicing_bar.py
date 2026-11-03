"""Voicing bar: voiced stretches as blocks under the spectrogram, aligned with the panes."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from phonolab.core.voice import VoicingResult
from phonolab.ui.editor.time_axis import TimeAxisController
from phonolab.ui.theme import COLORS

BAR_HEIGHT = 20


class VoicingBar(QWidget):
    """Click a voiced block (or the gap between blocks) to select it."""

    def __init__(self, axis: TimeAxisController, plot_area, parent=None):
        super().__init__(parent)
        self.axis = axis
        self.plot_area = plot_area  # callable -> (left_px, right_px)
        self.result: VoicingResult | None = None
        self.playhead: float | None = None
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Voicing: blue where Praat finds glottal pulses. Click a stretch to select it.")
        for sig in (axis.view_changed, axis.cursor_changed, axis.selection_changed):
            sig.connect(self.update)

    def set_result(self, result: VoicingResult | None):
        self.result = result
        self.update()

    def _x(self, t: float) -> float:
        left, right = self.plot_area()
        v0, v1 = self.axis.view
        return left + (t - v0) / (v1 - v0) * (right - left)

    def _t(self, x: float) -> float:
        left, right = self.plot_area()
        v0, v1 = self.axis.view
        return v0 + (x - left) / max(right - left, 1) * (v1 - v0)

    def paintEvent(self, ev):  # noqa: N802
        p = QPainter(self)
        left, right = self.plot_area()
        h = self.height()
        p.fillRect(self.rect(), QColor(COLORS["background"]))
        p.setPen(QColor(COLORS["muted"]))
        p.drawText(QRectF(4, 0, left - 8, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "voicing")
        track = QRectF(left, 3, right - left, h - 6)
        p.fillRect(track, QColor(COLORS["track"]))
        p.setClipRect(track)
        if self.result is None:
            p.drawText(track, Qt.AlignmentFlag.AlignCenter, "analysing…")
        else:
            v0, v1 = self.axis.view
            r = self.result
            i0 = int(np.searchsorted(r.ends, v0))
            i1 = int(np.searchsorted(r.starts, v1))
            fill, edge = QColor(COLORS["voiced"]), QColor(COLORS["voiced_edge"])
            p.setPen(QPen(edge, 1))
            for a, b in zip(r.starts[i0:i1], r.ends[i0:i1], strict=True):
                x0, x1 = self._x(a), self._x(b)
                p.fillRect(QRectF(x0, track.top(), max(x1 - x0, 1.0), track.height()), fill)
                p.drawLine(QPointF(x0, track.top()), QPointF(x0, track.bottom()))
                p.drawLine(QPointF(x1, track.top()), QPointF(x1, track.bottom()))
        if self.axis.selection:
            s0, s1 = self.axis.selection
            p.fillRect(QRectF(self._x(s0), 0, self._x(s1) - self._x(s0), h), QColor(*COLORS["selection"]))
        for t, colour, width, style in (
            (self.axis.cursor, COLORS["cursor"], 1, Qt.PenStyle.DashLine),
            (self.playhead, COLORS["playhead"], 2, Qt.PenStyle.SolidLine),
        ):
            if t is not None:
                p.setPen(QPen(QColor(colour), width, style))
                p.drawLine(QPointF(self._x(t), 0), QPointF(self._x(t), h))
        p.end()

    def mousePressEvent(self, ev):  # noqa: N802
        left, right = self.plot_area()
        if ev.button() != Qt.MouseButton.LeftButton or not left <= ev.position().x() <= right or self.result is None:
            return super().mousePressEvent(ev)
        t = self._t(ev.position().x())
        r = self.result
        i = int(np.searchsorted(r.starts, t, side="right")) - 1
        if i >= 0 and t < r.ends[i]:
            start, end = r.starts[i], r.ends[i]  # inside a voiced stretch
        else:  # in the unvoiced gap between stretches i and i + 1
            start = r.ends[i] if i >= 0 else 0.0
            end = r.starts[i + 1] if i + 1 < len(r.starts) else self.axis.duration
        self.axis.set_selection(start, end)
        self.axis.set_cursor(start)
