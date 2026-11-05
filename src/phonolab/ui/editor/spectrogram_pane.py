"""Spectrogram pane with pitch, formant and intensity overlays."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt, QTimer

from phonolab.core.analysis import FormantResult, IntensityResult, PitchResult, SpectrogramResult
from phonolab.ui.editor.base_pane import TimePane
from phonolab.ui.theme import COLORS, colormap
from phonolab.ui.workers import AnalysisManager

SPECTROGRAM_DEBOUNCE_MS = 60
MAX_FORMANT_DOTS = 30000


class OverlayViewBox(pg.ViewBox):
    """A second y-scale over the main plot that lets every mouse event fall through."""

    def __init__(self):
        super().__init__(enableMenu=False)
        self.setMouseEnabled(x=False, y=False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def wheelEvent(self, ev, axis=None):  # noqa: N802
        ev.ignore()

    def mouseClickEvent(self, ev):  # noqa: N802
        ev.ignore()

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802
        ev.ignore()


class SpectrogramPane(TimePane):
    frequency_axis = True
    LAYERS = ("spectrogram", "pitch", "formants", "intensity")

    def __init__(self, axis, manager: AnalysisManager, parent=None):
        self.manager = manager
        super().__init__(axis, parent)
        self.setMinimumHeight(140)
        plot = self.getPlotItem()
        # Units go in the label text: pyqtgraph's auto SI prefix would show kHz.
        plot.getAxis("left").setLabel("Frequency (Hz)")

        self.image = pg.ImageItem()
        self.image.setZValue(-10)
        self.addItem(self.image)
        self.formant_dots = pg.ScatterPlotItem(size=3, pen=None, brush=pg.mkBrush(COLORS["formant"]), pxMode=True)
        self.addItem(self.formant_dots)

        self.pitch_vb = self._add_overlay()
        # Thick pens are slow to rasterise: only draw what is visible, downsampled to the screen.
        curve_opts = {"connect": "finite", "clipToView": True, "autoDownsample": True, "downsampleMethod": "subsample"}
        self.pitch_curve = pg.PlotDataItem(pen=pg.mkPen(COLORS["pitch"], width=3), **curve_opts)
        self.pitch_vb.addItem(self.pitch_curve)
        self.intensity_vb = self._add_overlay()
        self.intensity_curve = pg.PlotDataItem(pen=pg.mkPen(COLORS["intensity"], width=2), **curve_opts)
        self.intensity_vb.addItem(self.intensity_curve)
        self.vb.sigResized.connect(self._sync_overlays)

        self.visible = dict.fromkeys(self.LAYERS, True)
        self._formant_xy = (np.zeros(0), np.zeros(0))
        self._debounce = QTimer(self, singleShot=True, interval=SPECTROGRAM_DEBOUNCE_MS)
        self._debounce.timeout.connect(lambda: self.manager.set_spectrogram_range(*self.axis.view))
        manager.result_ready.connect(self._on_result)
        self.apply_settings()

    def _add_overlay(self) -> OverlayViewBox:
        vb = OverlayViewBox()
        self.getPlotItem().scene().addItem(vb)
        vb.setXLink(self.vb)
        vb.setZValue(5)
        return vb

    def _sync_overlays(self):
        for vb in (self.pitch_vb, self.intensity_vb):
            vb.setGeometry(self.vb.sceneBoundingRect())
            vb.linkedViewChanged(self.vb, vb.XAxis)

    # ------------------------------------------------------------------ configuration

    def apply_settings(self):
        """Re-read display ranges from the manager's settings."""
        s = self.manager.settings
        nyquist = self.manager.sound.sampling_rate / 2
        self.vb.setYRange(0, min(s["spectrogram"].view_range, nyquist), padding=0)
        self.pitch_vb.setYRange(s["pitch"].floor, s["pitch"].ceiling, padding=0)
        self.intensity_vb.setYRange(s["intensity"].view_min, s["intensity"].view_max, padding=0)
        self.image.setLookupTable(colormap(s["spectrogram"].colormap).getLookupTable(nPts=256))
        self._update_right_axis()
        for name in self.LAYERS:
            self._on_result(name)

    def retheme(self):
        super().retheme()
        self.formant_dots.setBrush(pg.mkBrush(COLORS["formant"]))
        self.pitch_curve.setPen(pg.mkPen(COLORS["pitch"], width=3))
        self.intensity_curve.setPen(pg.mkPen(COLORS["intensity"], width=2))
        self.apply_settings()  # rebuilds the colour map and the coloured right-axis label

    def set_layer_visible(self, name: str, visible: bool):
        self.visible[name] = visible
        item = {
            "spectrogram": self.image,
            "pitch": self.pitch_curve,
            "formants": self.formant_dots,
            "intensity": self.intensity_curve,
        }[name]
        item.setVisible(visible)
        self.manager.set_enabled(name, visible)
        self._update_right_axis()

    def _update_right_axis(self):
        right = self.getPlotItem().getAxis("right")
        if self.visible.get("pitch"):
            right.linkToView(self.pitch_vb)
            right.setLabel("Pitch (Hz)", color=COLORS["pitch"])
        elif self.visible.get("intensity"):
            right.linkToView(self.intensity_vb)
            right.setLabel("Intensity (dB)", color=COLORS["intensity"])
        else:
            right.setStyle(showValues=False)
            right.setLabel("")
            return
        right.setStyle(showValues=True)

    # ------------------------------------------------------------------ data

    def view_updated(self, start, end):
        if not hasattr(self, "_debounce"):
            return  # still constructing
        self._debounce.start()
        self._update_formant_dots()

    def _on_result(self, name: str):
        result = self.manager.results.get(name)
        if result is None:
            return
        if name == "spectrogram":
            self._show_spectrogram(result)
        elif name == "pitch":
            self._show_pitch(result)
        elif name == "formants":
            self._show_formants(result)
        elif name == "intensity":
            self._show_intensity(result)

    def _show_spectrogram(self, r: SpectrogramResult):
        if r.db.size == 0:
            self.image.clear()
            return
        s = self.manager.settings["spectrogram"]
        self.image.setImage(r.db, levels=(r.max_db - s.dynamic_range, r.max_db), autoLevels=False)
        dt = r.times[1] - r.times[0] if len(r.times) > 1 else 0.001
        df = r.frequencies[1] - r.frequencies[0] if len(r.frequencies) > 1 else 1.0
        self.image.setRect(
            QRectF(r.times[0] - dt / 2, r.frequencies[0] - df / 2, dt * len(r.times), df * len(r.frequencies))
        )

    def _show_pitch(self, r: PitchResult):
        self.pitch_curve.setData(r.times, r.frequencies)

    def _show_formants(self, r: FormantResult):
        s = self.manager.settings["formants"]
        if r.frequencies.size == 0:
            self.formant_dots.clear()
            return
        loud = r.intensity_db >= np.nanmax(r.intensity_db) - s.dynamic_range
        x = np.tile(r.times, r.frequencies.shape[0])
        y = r.frequencies.ravel()
        keep = np.tile(loud, r.frequencies.shape[0]) & ~np.isnan(y)
        order = np.argsort(x[keep], kind="stable")
        self._formant_xy = (x[keep][order], y[keep][order])
        self._update_formant_dots()

    def _update_formant_dots(self):
        """Only hand the visible dots to the scatter item; it is slow with many points."""
        x, y = self._formant_xy
        start, end = self.axis.view
        i0, i1 = np.searchsorted(x, start), np.searchsorted(x, end)
        # ~5 formants x 2 frames per pixel is all the eye can resolve.
        limit = min(MAX_FORMANT_DOTS, 10 * max(int(self.vb.width()), 100))
        step = max(1, (i1 - i0) // limit)
        self.formant_dots.setData(x[i0:i1:step], y[i0:i1:step])

    def _show_intensity(self, r: IntensityResult):
        self.intensity_curve.setData(r.times, r.db)
