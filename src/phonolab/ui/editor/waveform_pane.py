"""Waveform pane: per-channel traces drawn as a min/max envelope at screen resolution."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from phonolab.core.sound import Sound
from phonolab.ui.editor.base_pane import TimePane
from phonolab.ui.theme import COLORS

ENVELOPE_BLOCK = 256  # samples per block in the precomputed envelope


class Envelope:
    """Min/max envelope of a signal with a precomputed coarse level for long views."""

    def __init__(self, signal: np.ndarray, sr: float):
        self.signal = signal
        self.sr = sr
        n = len(signal) // ENVELOPE_BLOCK * ENVELOPE_BLOCK
        blocks = signal[:n].reshape(-1, ENVELOPE_BLOCK)
        self.block_min = blocks.min(axis=1) if n else np.zeros(0)
        self.block_max = blocks.max(axis=1) if n else np.zeros(0)

    def render(self, start: float, end: float, n_pixels: int) -> tuple[np.ndarray, np.ndarray]:
        """Return (x, y) for the visible range: raw samples when zoomed in, else a
        vertical min/max line per pixel (no aliasing, unlike naive decimation)."""
        i0 = max(0, int(start * self.sr) - 1)
        i1 = min(len(self.signal), int(np.ceil(end * self.sr)) + 2)
        n = i1 - i0
        if n <= 0:
            return np.zeros(0), np.zeros(0)
        n_pixels = max(n_pixels, 1)
        if n <= 2 * n_pixels:
            x = np.arange(i0, i1) / self.sr
            return x, self.signal[i0:i1]
        per_pixel = n / n_pixels
        if per_pixel >= 4 * ENVELOPE_BLOCK and len(self.block_min):
            # Use the coarse level: work in blocks instead of samples.
            b0, b1 = i0 // ENVELOPE_BLOCK, min(len(self.block_min), i1 // ENVELOPE_BLOCK + 1)
            lo_src, hi_src, unit = self.block_min[b0:b1], self.block_max[b0:b1], ENVELOPE_BLOCK
            origin = b0 * ENVELOPE_BLOCK
        else:
            lo_src = hi_src = self.signal[i0:i1]
            unit, origin = 1, i0
        k = max(1, int(len(lo_src) / n_pixels))
        m = len(lo_src) // k * k
        if m == 0:
            return np.zeros(0), np.zeros(0)
        lo = lo_src[:m].reshape(-1, k).min(axis=1)
        hi = hi_src[:m].reshape(-1, k).max(axis=1)
        t = (origin + (np.arange(len(lo)) + 0.5) * k * unit) / self.sr
        x = np.repeat(t, 2)
        y = np.empty(2 * len(lo))
        y[0::2], y[1::2] = lo, hi
        return x, y


class WaveformPane(TimePane):
    def __init__(self, axis, sound: Sound, parent=None):
        self.sound = sound
        self.envelopes = [Envelope(sound.samples[:, c], sound.sampling_rate) for c in range(sound.n_channels)]
        self.curves = []
        super().__init__(axis, parent)
        self.setMinimumHeight(70)
        n = sound.n_channels
        self.peak = float(np.max(np.abs(sound.samples))) or 1.0
        spacing = 2 * self.peak  # channels stacked top to bottom
        pen = pg.mkPen(COLORS["waveform"], width=1)
        for c in range(n):
            curve = pg.PlotDataItem(pen=pen, connect="all", skipFiniteCheck=True)
            curve.setPos(0, -spacing * c)
            self.addItem(curve)
            self.curves.append(curve)
        self.vb.setYRange(-spacing * (n - 1) - self.peak, self.peak, padding=0.05)
        if n > 1:
            labels = [(-spacing * c, f"ch {c + 1}") for c in range(n)]
            self.getPlotItem().getAxis("left").setTicks([labels, []])
        self.view_updated(*axis.view)

    def view_updated(self, start, end):
        if not self.curves:
            return
        width = max(int(self.vb.width()), 200)
        for env, curve in zip(self.envelopes, self.curves, strict=True):
            x, y = env.render(start, end, width)
            curve.setData(x, y)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self.view_updated(*self.axis.view)
