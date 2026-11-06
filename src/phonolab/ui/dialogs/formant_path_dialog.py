"""Choose a formant ceiling by comparing analyses side by side."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QVBoxLayout,
)

from phonolab.core.formant_path import Candidate, FormantPathResult
from phonolab.ui.theme import COLORS, style_plot

COLUMNS = 3
TRACK_COLOURS = ("formant", "pitch", "manipulation")  # F1, F2, F3


class CandidateTile(QFrame):
    """One analysis: its formant tracks, ceiling and stress. Click to choose it."""

    chosen = pyqtSignal(int)

    def __init__(self, index: int, candidate: Candidate, is_best: bool, top: float, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("candidateTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        stress = "undefined" if np.isnan(candidate.stress) else f"{candidate.stress:.1f}"
        label = QLabel(f"{candidate.ceiling:.0f} Hz   ·   stress {stress}" + ("   ·   lowest" if is_best else ""))
        label.setObjectName("candidateBest" if is_best else "muted")
        plot = pg.PlotWidget()
        plot.setMenuEnabled(False)
        plot.hideButtons()
        plot.setMouseEnabled(x=False, y=False)
        plot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # clicks reach the tile
        plot.setMinimumSize(220, 130)
        style_plot(plot)
        plot.getPlotItem().hideAxis("bottom")
        for track, colour in zip(candidate.frequencies, TRACK_COLOURS, strict=True):
            keep = ~np.isnan(track)
            plot.plot(candidate.times[keep], track[keep], pen=None, symbol="o", symbolSize=3,
                      symbolPen=None, symbolBrush=pg.mkBrush(COLORS[colour]))  # fmt: skip
        plot.setYRange(0, top, padding=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addWidget(label)
        layout.addWidget(plot)

    def set_selected(self, selected: bool):
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, ev):  # noqa: N802
        self.chosen.emit(self.index)


class FormantPathDialog(QDialog):
    def __init__(self, result: FormantPathResult, current_ceiling: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Formant ceilings, {result.start:.3f}–{result.end:.3f} s")
        self.result_data = result
        best = result.best
        grid = QGridLayout()
        grid.setSpacing(8)
        top = max(c.ceiling for c in result.candidates) * 0.75
        self.tiles = []
        for i, candidate in enumerate(result.candidates):
            tile = CandidateTile(i, candidate, i == best, top)
            tile.chosen.connect(self.choose)
            grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
            self.tiles.append(tile)

        note = (
            "Lower stress means F1–F3 follow smoother tracks, which usually means a better ceiling. "
            "Check the tracks too: it's a guide, not a verdict."
        )
        if result.best_is_at_edge:
            note += " The lowest stress is at the end of this range, so the best ceiling may lie beyond it."
        hint = QLabel(note)
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use this ceiling")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(grid, 1)
        layout.addWidget(hint)
        layout.addWidget(self.buttons)

        distances = [abs(c.ceiling - current_ceiling) for c in result.candidates]
        self.choose(best if best is not None else int(np.argmin(distances)))

    def choose(self, index: int):
        self.selected = index
        for tile in self.tiles:
            tile.set_selected(tile.index == index)

    @property
    def ceiling(self) -> float:
        return self.result_data.candidates[self.selected].ceiling
