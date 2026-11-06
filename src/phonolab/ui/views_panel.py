"""Dock with a cepstrogram, cochleagram or MFCC view of the selection or visible stretch."""

from __future__ import annotations

import contextlib

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, QTimer
from PyQt6.QtWidgets import QComboBox, QDockWidget, QLabel, QVBoxLayout, QWidget

from phonolab.core import views
from phonolab.ui.theme import colormap, style_plot

UPDATE_DELAY_MS = 200
VISIBLE_RANGE = (2, 98)  # percentiles shown from quietest to loudest, so outliers don't wash out the image


class ViewsPanel(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Time views", parent)
        self.setObjectName("views_dock")
        self.editor = None
        self.result: views.ViewResult | None = None
        body = QWidget()
        layout = QVBoxLayout(body)
        self.kind = QComboBox()
        for name, view in views.VIEWS.items():
            self.kind.addItem(view.label, name)
        self.kind.currentIndexChanged.connect(self.schedule_update)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(170)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setLabel("bottom", "Time (s)")
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)
        self.image = pg.ImageItem()
        self.plot.addItem(self.image)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.kind)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.status)
        self.setWidget(body)
        self.retheme()
        self._timer = QTimer(self, singleShot=True, interval=UPDATE_DELAY_MS)
        self._timer.timeout.connect(self.update_view)
        self.visibilityChanged.connect(lambda visible: visible and self.schedule_update())

    def retheme(self):
        style_plot(self.plot)
        self.image.setLookupTable(colormap("Grey (Praat)").getLookupTable(nPts=256))

    def set_editor(self, editor) -> None:
        if self.editor is not None:
            pairs = (
                (self.editor.axis.view_changed, self.schedule_update),
                (self.editor.axis.selection_changed, self.schedule_update),
                (self.editor.manager.job_done, self._on_job_done),
                (self.editor.manager.job_failed, self._on_job_failed),
            )
            for sig, slot in pairs:
                with contextlib.suppress(TypeError, RuntimeError):
                    sig.disconnect(slot)
        self.editor = editor
        if editor is not None:
            editor.axis.view_changed.connect(self.schedule_update)
            editor.axis.selection_changed.connect(self.schedule_update)
            editor.manager.job_done.connect(self._on_job_done)
            editor.manager.job_failed.connect(self._on_job_failed)
        self.schedule_update()

    def schedule_update(self, *_):
        if self.isVisible():
            self._timer.start()

    def update_view(self):
        if self.editor is None:
            return
        start, end = self.editor.axis.selection or self.editor.axis.view
        if end - start > views.MAX_SECONDS:
            self.image.clear()
            self.status.setText(f"Select or zoom to {views.MAX_SECONDS:.0f} seconds or less.")
            return
        self.status.setText("Analysing…")
        self.editor.manager.submit("view", views.compute_view, self.kind.currentData(), start, end)

    def _on_job_done(self, key: str, result):
        if key != "view":
            return
        self.result = result
        spec = views.VIEWS[result.name]
        low, high = np.nanpercentile(result.values, VISIBLE_RANGE)
        self.image.setImage(result.values, levels=(low, high), autoLevels=False)
        dt = result.times[1] - result.times[0] if len(result.times) > 1 else 0.01
        dy = result.ys[1] - result.ys[0] if len(result.ys) > 1 else 1.0
        self.image.setRect(
            QRectF(result.times[0] - dt / 2, result.ys[0] - dy / 2, dt * len(result.times), dy * len(result.ys))
        )
        self.plot.setLabel("left", spec.y_label)
        self.plot.getPlotItem().getViewBox().autoRange(padding=0)
        self.status.setText(f"{spec.label}, {result.times[0]:.2f}–{result.times[-1]:.2f} s")

    def _on_job_failed(self, key: str, message: str):
        if key == "view":
            self.status.setText(message)
