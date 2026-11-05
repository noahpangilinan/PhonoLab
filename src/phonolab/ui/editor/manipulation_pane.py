"""Pitch-tier editor: drag points, Ctrl+click to add; duration factors shown as labels."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal

from phonolab.core.manipulation import Tier
from phonolab.ui.editor.base_pane import TimePane, TimeViewBox
from phonolab.ui.manipulation import ManipulationState
from phonolab.ui.theme import COLORS

GRAB_PX = 7
MAX_EDITABLE_POINTS = 2000  # beyond this, zoom in to edit (points would overlap anyway)


class _ManipulationViewBox(TimeViewBox):
    pane: ManipulationPane

    def mouseClickEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            ev.accept()
            p = self.mapSceneToView(ev.scenePos())
            self.pane.add_point(p.x(), p.y())
            return
        super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.isStart():
                self.pane.begin_drag(self.mapSceneToView(ev.buttonDownScenePos()))
            if self.pane.dragging:
                ev.accept()
                self.pane.drag_to(self.mapSceneToView(ev.scenePos()))
                if ev.isFinish():
                    self.pane.end_drag()
                return
        super().mouseDragEvent(ev, axis)


class ManipulationPane(TimePane):
    frequency_axis = True
    viewbox_class = _ManipulationViewBox
    message = pyqtSignal(str)

    def __init__(self, axis, parent=None):
        self.state: ManipulationState | None = None
        super().__init__(axis, parent)
        self.vb.pane = self
        self.setMinimumHeight(110)
        plot = self.getPlotItem()
        plot.getAxis("left").setLabel("Pitch (Hz)")
        plot.getAxis("left").enableAutoSIPrefix(False)
        opts = {"connect": "finite", "clipToView": True, "autoDownsample": True, "downsampleMethod": "subsample"}
        self.original_curve = pg.PlotDataItem(
            pen=pg.mkPen(COLORS["muted"], width=1, style=Qt.PenStyle.DashLine), **opts
        )
        self.curve = pg.PlotDataItem(pen=pg.mkPen(COLORS["manipulation"], width=2), **opts)
        self.points = pg.ScatterPlotItem(size=8, pen=pg.mkPen("w"), brush=pg.mkBrush(COLORS["manipulation"]))
        for item in (self.original_curve, self.curve, self.points):
            self.addItem(item)
        self.status = pg.TextItem("", color=COLORS["muted"], anchor=(0, 0))
        self.addItem(self.status, ignoreBounds=True)
        self.duration_labels: list[pg.TextItem] = []
        self._drag: tuple[int, Tier] | None = None  # (point index, working copy) while dragging
        self.set_status("Analysing pitch for manipulation…")

    def retheme(self):
        super().retheme()
        self.original_curve.setPen(pg.mkPen(COLORS["muted"], width=1, style=Qt.PenStyle.DashLine))
        self.curve.setPen(pg.mkPen(COLORS["manipulation"], width=2))
        self.points.setBrush(pg.mkBrush(COLORS["manipulation"]))
        self.status.setColor(COLORS["muted"])
        self.refresh()  # rebuilds the duration labels in the new colour

    # ------------------------------------------------------------------ state

    def set_state(self, state: ManipulationState | None):
        if self.state is not None:
            self.state.changed.disconnect(self.refresh)
        self.state = state
        if state is not None:
            state.changed.connect(self.refresh)
            self.vb.setYRange(state.settings.floor, state.settings.ceiling, padding=0.02)
            self.original_curve.setData(state.original.times, state.original.values)
            self.set_status("")
        self.refresh()

    def set_status(self, text: str):
        self.status.setText(text)
        v0, _ = self.axis.view
        self.status.setPos(v0, self.vb.viewRange()[1][1])

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    def _pitch(self) -> Tier:
        return self._drag[1] if self._drag else (self.state.pitch if self.state else Tier.empty())

    def refresh(self):
        pitch = self._pitch()
        self.curve.setData(pitch.times, pitch.values)
        self._update_points()
        self._update_duration_labels()

    def view_updated(self, start, end):
        if self.state is None:
            if hasattr(self, "status"):
                self.set_status(self.status.toPlainText())
            return
        self._update_points()
        self._update_duration_labels()

    def _visible(self) -> tuple[np.ndarray, np.ndarray, int]:
        pitch = self._pitch()
        start, end = self.axis.view
        i0, i1 = np.searchsorted(pitch.times, start), np.searchsorted(pitch.times, end)
        return pitch.times[i0:i1], pitch.values[i0:i1], i0

    def _update_points(self):
        times, values, _ = self._visible()
        if len(times) > MAX_EDITABLE_POINTS:
            self.points.setData([], [])  # the line still shows the contour
        else:
            self.points.setData(times, values)

    def _update_duration_labels(self):
        for label in self.duration_labels:
            self.removeItem(label)
        self.duration_labels = []
        if self.state is None:
            return
        d = self.state.duration
        top = self.vb.viewRange()[1][1]
        # Label each plateau (a run of equal factors other than 1) at its start.
        for i in range(len(d)):
            factor = d.values[i]
            starts_plateau = i == 0 or d.values[i - 1] != factor
            if abs(factor - 1.0) > 1e-9 and starts_plateau:
                label = pg.TextItem(f"duration ×{factor:g}", color=COLORS["manipulation"], anchor=(0, 0))
                label.setPos(d.times[i], top)
                self.addItem(label, ignoreBounds=True)
                self.duration_labels.append(label)

    # ------------------------------------------------------------------ editing

    def _point_near(self, pos) -> int | None:
        times, values, offset = self._visible()
        if len(times) == 0:
            return None
        if len(times) > MAX_EDITABLE_POINTS:
            self.message.emit("Zoom in to edit individual pitch points")
            return None
        px_w, px_h = self.vb.viewPixelSize()
        dist = np.hypot((times - pos.x()) / px_w, (values - pos.y()) / px_h)
        i = int(np.argmin(dist))
        return offset + i if dist[i] <= GRAB_PX else None

    def begin_drag(self, pos):
        if self.state is None:
            return
        idx = self._point_near(pos)
        if idx is not None:
            p = self.state.pitch
            self._drag = (idx, Tier(p.times.copy(), p.values.copy()))

    def drag_to(self, pos):
        idx, tier = self._drag
        lo = tier.times[idx - 1] + 1e-4 if idx > 0 else 0.0
        hi = tier.times[idx + 1] - 1e-4 if idx + 1 < len(tier) else self.axis.duration
        tier.times[idx] = min(max(pos.x(), lo), hi)
        tier.values[idx] = max(pos.y(), 1.0)
        self.refresh()

    def end_drag(self):
        _, tier = self._drag
        self._drag = None
        self.state.apply("Move pitch point", pitch=tier)

    def add_point(self, t: float, hz: float):
        if self.state is None:
            return
        t = self.axis.clamp(t)
        if np.any(np.abs(self.state.pitch.times - t) < 1e-4):
            return
        self.state.apply("Add pitch point", pitch=self.state.pitch.with_point(t, max(hz, 1.0)))
