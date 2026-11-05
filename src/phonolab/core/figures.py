"""Publication-quality figures (Praat's Picture window): waveform, spectrogram, pitch, TextGrid."""

from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Agg")  # render off-screen; the UI shows the result as an image

import numpy as np  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from phonolab.core import analysis, voice  # noqa: E402
from phonolab.core.analysis import (  # noqa: E402
    FormantSettings,
    IntensitySettings,
    PitchSettings,
    SpectrogramSettings,
    setting,
)
from phonolab.core.ipa import to_unicode  # noqa: E402
from phonolab.core.sound import MAX_WINDOW_SECONDS, LongSoundError, Sound  # noqa: E402
from phonolab.core.textgrid import IntervalTier, TextGrid  # noqa: E402

PANELS = ("waveform", "spectrogram", "pitch", "voicing", "textgrid")
# Height of each panel relative to a standard one (the TextGrid scales with its tier count).
PANEL_HEIGHT = {"voicing": 0.22}


@dataclass(frozen=True)
class FigureSettings:
    title = "Figure"
    width: float = setting(6.5, "Width", "in", 1.0, 30.0, decimals=2)
    panel_height: float = setting(1.6, "Height per panel", "in", 0.3, 10.0, decimals=2)
    font_size: float = setting(10.0, "Font size", "pt", 4.0, 30.0, decimals=1)
    font_family: str = setting("serif", "Font", choices=("serif", "sans-serif"))
    colour: bool = setting(False, "Colour (otherwise greyscale, like Praat)")
    dpi: int = setting(300, "Resolution for PNG", "dpi", 72, 1200)
    show_formants: bool = setting(True, "Formant dots on the spectrogram")
    show_pitch_on_spectrogram: bool = setting(False, "Pitch contour on the spectrogram")
    show_intensity_on_spectrogram: bool = setting(False, "Intensity contour on the spectrogram")
    pitch_semitones: bool = setting(False, "Pitch panel in semitones (re 100 Hz)")


@dataclass(frozen=True)
class FigureRequest:
    panels: tuple[str, ...] = ("waveform", "spectrogram", "textgrid")
    start: float = 0.0
    end: float | None = None
    tiers: tuple[str, ...] | None = None  # None = all tiers
    figure: FigureSettings = field(default_factory=FigureSettings)
    spectrogram: SpectrogramSettings = field(default_factory=SpectrogramSettings)
    pitch: PitchSettings = field(default_factory=PitchSettings)
    formants: FormantSettings = field(default_factory=FormantSettings)
    intensity: IntensitySettings = field(default_factory=IntensitySettings)


ANALYSIS_MARGIN = 0.2  # s of context on each side, so contours reach the figure's edges


def _local(sound: Sound, start: float, end: float) -> tuple[Sound, float]:
    """The plotted range plus a margin, and the time offset to add to its analysis times."""
    a = max(0.0, start - ANALYSIS_MARGIN)
    return sound.extract(a, min(sound.duration, end + ANALYSIS_MARGIN)), a


def _palette(colour: bool) -> dict:
    if colour:
        return {"wave": "#1f3a5f", "pitch": "#1f77d4", "formant": "#d62728", "intensity": "#d4a017",
                "cmap": "magma_r", "boundary": "#1f3a5f", "voiced": "#9cc3ea"}  # fmt: skip
    return {"wave": "black", "pitch": "black", "formant": "black", "intensity": "0.4",
            "cmap": "Greys", "boundary": "black", "voiced": "0.75"}  # fmt: skip


def make_figure(sound: Sound, textgrid: TextGrid | None, req: FigureRequest) -> Figure:
    start = max(0.0, req.start)
    end = sound.duration if req.end is None else min(req.end, sound.duration)
    if end - start <= 0:
        raise ValueError("Empty time range")
    if sound.is_long and end - start > MAX_WINDOW_SECONDS:
        raise LongSoundError(f"Choose {MAX_WINDOW_SECONDS:.0f} seconds or less of this long recording")
    fs = req.figure
    pal = _palette(fs.colour)
    tiers = []
    if "textgrid" in req.panels and textgrid is not None:
        tiers = [t for t in textgrid.tiers if req.tiers is None or t.name in req.tiers]
    panels = [p for p in req.panels if p != "textgrid" or tiers]
    if not panels:
        raise ValueError("Nothing to draw: choose at least one panel")

    heights = [0.35 * len(tiers) if p == "textgrid" else PANEL_HEIGHT.get(p, 1.0) for p in panels]
    height = fs.panel_height * sum(heights)
    rc = {"font.size": fs.font_size, "font.family": fs.font_family, "axes.linewidth": 0.8}
    with matplotlib.rc_context(rc):
        fig = Figure(figsize=(fs.width, height), layout="constrained")
        axes = fig.subplots(len(panels), 1, sharex=True, height_ratios=heights, squeeze=False)[:, 0]
        for ax, panel in zip(axes, panels, strict=True):
            if panel == "waveform":
                _draw_waveform(ax, sound.extract(start, end), start, pal)
            elif panel == "spectrogram":
                _draw_spectrogram(ax, sound, start, end, req, pal)
            elif panel == "pitch":
                _draw_pitch(ax, sound, start, end, req, pal)
            elif panel == "voicing":
                _draw_voicing(ax, sound, start, end, req, pal)
            else:
                _draw_textgrid(ax, tiers, start, end, pal)
        axes[-1].set_xlim(start, end)
        axes[-1].set_xlabel("Time (s)")
        for ax in axes[:-1]:
            ax.tick_params(labelbottom=False)
    return fig


def _draw_waveform(ax, part: Sound, offset: float, pal):
    t = offset + np.arange(part.n_samples) / part.sampling_rate
    peak = float(np.max(np.abs(part.samples))) or 1.0
    n = part.n_channels
    for c in range(n):
        y = part.samples[:, c] / peak - 2.2 * c
        ax.plot(t, y, color=pal["wave"], linewidth=0.4, rasterized=part.n_samples > 200_000)
    ax.set_ylim(-2.2 * (n - 1) - 1.1, 1.1)
    ax.set_yticks([])
    ax.set_ylabel("Amplitude" if n == 1 else "Channels")


def _draw_spectrogram(ax, sound: Sound, start: float, end: float, req: FigureRequest, pal):
    s = req.spectrogram
    r = analysis.compute_spectrogram(sound, s, start, end)
    lo = r.max_db - s.dynamic_range
    ax.pcolormesh(r.times, r.frequencies, np.clip(r.db, lo, r.max_db), cmap=pal["cmap"], shading="auto",
                  vmin=lo, vmax=r.max_db, rasterized=True)  # fmt: skip
    ax.set_ylim(0, min(s.view_range, sound.sampling_rate / 2))
    ax.set_ylabel("Frequency (Hz)")
    fs = req.figure
    local, offset = _local(sound, start, end)
    if fs.show_formants:
        f = analysis.compute_formants(local, req.formants)
        t = f.times + offset
        keep = (t >= start) & (t <= end) & (f.intensity_db >= np.nanmax(f.intensity_db) - req.formants.dynamic_range)
        for row in f.frequencies:
            ax.plot(t[keep], row[keep], ".", color=pal["formant"], markersize=1.5)
    if fs.show_pitch_on_spectrogram or fs.show_intensity_on_spectrogram:
        twin = ax.twinx()
        if fs.show_pitch_on_spectrogram:
            p = analysis.compute_pitch(local, req.pitch)
            twin.plot(p.times + offset, p.frequencies, color=pal["pitch"], linewidth=1.5)
            twin.set_ylim(req.pitch.floor, req.pitch.ceiling)
            twin.set_ylabel("Pitch (Hz)")
        else:
            i = analysis.compute_intensity(local, req.intensity)
            twin.plot(i.times + offset, i.db, color=pal["intensity"], linewidth=1.2)
            twin.set_ylim(req.intensity.view_min, req.intensity.view_max)
            twin.set_ylabel("Intensity (dB)")


def _draw_pitch(ax, sound: Sound, start: float, end: float, req: FigureRequest, pal):
    local, offset = _local(sound, start, end)
    p = analysis.compute_pitch(local, req.pitch)
    times = p.times + offset
    mask = (times >= start) & (times <= end)
    f = p.frequencies[mask]
    if req.figure.pitch_semitones:
        f = 12 * np.log2(f / 100.0)
        lo, hi = (12 * np.log2(v / 100.0) for v in (req.pitch.floor, req.pitch.ceiling))
        ax.set_ylabel("Pitch (st re 100 Hz)")
    else:
        lo, hi = req.pitch.floor, req.pitch.ceiling
        ax.set_ylabel("Pitch (Hz)")
    ax.plot(times[mask], f, ".", color=pal["pitch"], markersize=2.5)
    voiced = f[~np.isnan(f)]
    if len(voiced):  # zoom to the data with a margin, within the analysis range
        margin = 0.1 * (voiced.max() - voiced.min() or 10)
        lo, hi = max(lo, voiced.min() - margin), min(hi, voiced.max() + margin)
    ax.set_ylim(lo, hi)


def _draw_voicing(ax, sound: Sound, start: float, end: float, req: FigureRequest, pal):
    local, offset = _local(sound, start, end)
    r = voice.compute_voicing(local, voice.VoicingSettings(), req.pitch)
    spans = [(a + offset, b - a) for a, b in zip(r.starts, r.ends, strict=True)]
    ax.broken_barh(spans, (0.15, 0.7), facecolor=pal["voiced"], edgecolor=pal["boundary"], linewidth=0.5)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.5], ["voicing"])
    ax.tick_params(axis="y", length=0)


def _draw_textgrid(ax, tiers, start: float, end: float, pal):
    n = len(tiers)
    ax.set_ylim(0, n)
    ax.set_yticks([n - i - 0.5 for i in range(n)], [t.name for t in tiers])
    ax.tick_params(axis="y", length=0)
    for i, tier in enumerate(tiers):
        top, bottom = n - i, n - i - 1
        if i:
            ax.axhline(top, color=pal["boundary"], linewidth=0.6)
        if isinstance(tier, IntervalTier):
            for iv in tier.intervals:
                if iv.xmax < start or iv.xmin > end:
                    continue
                if start < iv.xmin < end:
                    ax.vlines(iv.xmin, bottom, top, color=pal["boundary"], linewidth=0.8)
                if iv.text:
                    mid = (max(iv.xmin, start) + min(iv.xmax, end)) / 2
                    ax.text(mid, bottom + 0.5, to_unicode(iv.text), ha="center", va="center", clip_on=True)
        else:
            for p in tier.points:
                if start <= p.time <= end:
                    ax.vlines(p.time, bottom, bottom + 0.25, color=pal["boundary"], linewidth=0.8)
                    ax.vlines(p.time, top - 0.25, top, color=pal["boundary"], linewidth=0.8)
                    ax.text(p.time, bottom + 0.5, to_unicode(p.mark), ha="center", va="center", clip_on=True)


def save_figure(fig: Figure, path, dpi: int = 300) -> None:
    """Format follows the extension: .svg and .pdf stay vector, .png uses ``dpi``."""
    fig.savefig(str(path), dpi=dpi)
