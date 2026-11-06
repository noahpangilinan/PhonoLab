"""Edit a standalone Praat tier file: drag points, Ctrl+click to add, Delete to remove."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from phonolab.core.manipulation import Tier
from phonolab.core.tiers import TierFile
from phonolab.ui.theme import COLORS, style_plot

GRAB_PX = 7


class _TierViewBox(pg.ViewBox):
    window: TierWindow

    def __init__(self):
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=False, y=False)

    def mouseClickEvent(self, ev):  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        p = self.mapSceneToView(ev.scenePos())
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.window.add_point(p.x(), p.y())
        else:
            self.window.select_near(p)

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        ev.accept()
        if ev.isStart():
            self.window.select_near(self.mapSceneToView(ev.buttonDownScenePos()))
            if self.window.selected is not None:
                self.window.begin_edit()
        if self.window.selected is not None:
            self.window.move_selected(self.mapSceneToView(ev.scenePos()))


class TierWindow(QDialog):
    """Non-modal, so several tiers can be open beside the editor."""

    def __init__(self, tier_file: TierFile, path: Path | None, parent=None):
        super().__init__(parent)
        self.file = tier_file
        self.path = path
        self.dirty = False
        self.selected: int | None = None
        self.history: list[Tier] = []
        self.resize(760, 420)

        box = _TierViewBox()
        box.window = self
        self.plot = pg.PlotWidget(viewBox=box)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        unit = f" ({tier_file.unit})" if tier_file.unit else ""
        self.plot.setLabel("left", tier_file.object_class + unit)
        self.plot.setLabel("bottom", "Time (s)")
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)
        style_plot(self.plot)
        self.curve = self.plot.plot(pen=pg.mkPen(COLORS["manipulation"], width=2))
        self.points = pg.ScatterPlotItem(size=9, pen=pg.mkPen("w"), brush=pg.mkBrush(COLORS["manipulation"]))
        self.chosen = pg.ScatterPlotItem(size=12, pen=pg.mkPen(COLORS["cursor"], width=2), brush=pg.mkBrush(None))
        self.plot.addItem(self.points)
        self.plot.addItem(self.chosen)

        hint = QLabel("Drag a point to move it. Ctrl+click adds one. Delete removes the selected point.")
        hint.setObjectName("muted")
        save = QPushButton("Save")
        save.clicked.connect(self.save)
        save_as = QPushButton("Save as…")
        save_as.clicked.connect(self.save_as)
        for button in (save, save_as):
            button.setAutoDefault(False)  # Enter shouldn't save
        buttons = QHBoxLayout()
        buttons.addWidget(hint, 1)
        buttons.addWidget(save_as)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addWidget(self.plot, 1)
        layout.addLayout(buttons)
        QShortcut(QKeySequence("Delete"), self, activated=self.remove_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.remove_selected)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        self._refresh(fit=True)

    @property
    def tier(self) -> Tier:
        return self.file.tier

    def _refresh(self, fit: bool = False):
        name = self.path.name if self.path else f"untitled {self.file.object_class}"
        self.setWindowTitle(name + ("*" if self.dirty else ""))
        t, v = self.tier.times, self.tier.values
        self.curve.setData(t, v)
        self.points.setData(t, v)
        i = self.selected
        self.chosen.setData([t[i]], [v[i]]) if i is not None else self.chosen.setData([], [])
        if fit:
            span = float(np.ptp(v)) if len(v) else 1.0
            low = float(v.min()) if len(v) else 0.0
            self.plot.getViewBox().setRange(
                xRange=(self.file.xmin, self.file.xmax), yRange=(low - 0.15 * span - 1e-6, low + 1.15 * span + 1e-6),
                padding=0,
            )  # fmt: skip

    def begin_edit(self):
        self.history.append(Tier(self.tier.times.copy(), self.tier.values.copy()))

    def _changed(self):
        self.dirty = True
        self._refresh()

    def select_near(self, pos):
        self.selected = None
        if len(self.tier):
            px_w, px_h = self.plot.getViewBox().viewPixelSize()
            distance = np.hypot((self.tier.times - pos.x()) / px_w, (self.tier.values - pos.y()) / px_h)
            nearest = int(np.argmin(distance))
            if distance[nearest] <= GRAB_PX:
                self.selected = nearest
        self._refresh()

    def move_selected(self, pos):
        i, t = self.selected, self.tier
        low = t.times[i - 1] + 1e-4 if i > 0 else self.file.xmin
        high = t.times[i + 1] - 1e-4 if i + 1 < len(t) else self.file.xmax
        t.times[i] = min(max(pos.x(), low), high)
        t.values[i] = pos.y()
        self._changed()

    def add_point(self, time: float, value: float):
        time = min(max(time, self.file.xmin), self.file.xmax)
        if np.any(np.abs(self.tier.times - time) < 1e-6):
            return
        self.begin_edit()
        self.file.tier = self.tier.with_point(time, value)
        self.selected = int(np.searchsorted(self.tier.times, time))
        self._changed()

    def remove_selected(self):
        if self.selected is None:
            return
        self.begin_edit()
        keep = np.arange(len(self.tier)) != self.selected
        self.file.tier = Tier(self.tier.times[keep], self.tier.values[keep])
        self.selected = None
        self._changed()

    def undo(self):
        if self.history:
            self.file.tier = self.history.pop()
            self.selected = None
            self._changed()

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        try:
            self.file.save(self.path)
        except OSError as e:
            QMessageBox.warning(self, "Could not save tier", str(e))
            return False
        self.dirty = False
        self._refresh()
        return True

    def save_as(self) -> bool:
        suffix = f".{self.file.object_class}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save tier", str(self.path or f"untitled{suffix}"), f"{self.file.object_class} (*{suffix})"
        )
        if not path:
            return False
        self.path = Path(path)
        return self.save()

    def reject(self):
        self.close()  # Esc would otherwise hide the window without asking about unsaved changes

    def closeEvent(self, ev):  # noqa: N802
        if self.dirty:
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.question(
                self, "Unsaved tier", "Save your changes to this tier?", buttons.Save | buttons.Discard | buttons.Cancel
            )
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save()):
                ev.ignore()
                return
        ev.accept()
