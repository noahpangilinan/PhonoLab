"""Spectral slices, long-term average spectra, spectral moments and CPPS (all via Praat)."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import parselmouth
from parselmouth.praat import call

from phonolab.core import praat_engine
from phonolab.core.analysis import setting
from phonolab.core.sound import Sound

# Spectral moments need one FFT over the whole range; beyond this it gets slow and is rarely meaningful.
MAX_MOMENTS_SECONDS = 30.0
HALF_CONTEXT = 0.2  # s of sound around the time point for LPC and excitation
LPC_SCRIPT = """To LPC (burg): 16, 0.025, 0.005, 50
To Spectrum (slice): {time}, 20, 0, 50
To Ltas (1-to-1)
To Matrix
@export: "curve"
"""
EXCITATION_SCRIPT = """To Cochleagram: 0.01, 0.1, 0.03, 0.03
To Excitation (slice): {time}
To Matrix
@export: "curve"
"""


@dataclass(frozen=True)
class SpectrumSettings:
    title = "Spectrum"
    max_frequency: float = setting(5000.0, "Maximum frequency", "Hz", 100.0, 50000.0)
    slice_window: float = setting(0.04, "Window at the cursor", "s", 0.005, 1.0, decimals=3)
    ltas_bandwidth: float = setting(100.0, "LTAS bandwidth", "Hz", 1.0, 1000.0)
    moment_power: float = setting(2.0, "Power for spectral moments", "", 0.5, 4.0, decimals=1)


@dataclass(frozen=True)
class SpectrumResult:
    kind: str  # "slice" or "ltas"
    start: float
    end: float
    frequencies: np.ndarray
    db: np.ndarray  # dB/Hz re 2e-5 Pa (slice) or dB (LTAS)
    centre_of_gravity: float
    standard_deviation: float
    skewness: float
    kurtosis: float


def _part(sound: Sound, start: float, end: float, window: bool) -> parselmouth.Sound:
    shape = parselmouth.WindowShape.HANNING if window else parselmouth.WindowShape.RECTANGULAR
    return sound.praat.extract_part(
        from_time=max(0.0, start), to_time=min(sound.duration, end), window_shape=shape,
        relative_width=1.0, preserve_times=True,
    )  # fmt: skip


def slice_range(sound: Sound, s: SpectrumSettings, cursor: float, selection) -> tuple[float, float]:
    """The selection, or a window centred on the cursor (as Praat's "View spectral slice")."""
    if selection:
        return selection
    half = s.slice_window / 2
    return max(0.0, cursor - half), min(sound.duration, cursor + half)


def compute_slice(sound: Sound, s: SpectrumSettings, start: float, end: float) -> SpectrumResult:
    if sound.is_long:
        return replace(compute_slice(sound.extract(start, end), s, 0.0, end - start), start=start, end=end)
    spectrum = _part(sound, start, end, window=True).to_spectrum()
    ltas = call(spectrum, "To Ltas (1-to-1)")
    return _result("slice", start, end, spectrum, ltas, s)


def compute_ltas(sound: Sound, s: SpectrumSettings, start: float, end: float) -> SpectrumResult:
    if sound.is_long:
        return replace(compute_ltas(sound.extract(start, end), s, 0.0, end - start), start=start, end=end)
    part = _part(sound, start, end, window=False)
    ltas = call(part, "To Ltas", s.ltas_bandwidth)
    spectrum = part.to_spectrum() if end - start <= MAX_MOMENTS_SECONDS else None
    return _result("ltas", start, end, spectrum, ltas, s)


def compute_lpc(sound: Sound, s: SpectrumSettings, start: float, end: float) -> SpectrumResult:
    """The smooth LPC spectrum at the middle of ``[start, end]``: the vocal tract without the harmonics."""
    return _engine_curve(sound, s, start, end, "lpc", LPC_SCRIPT)


def compute_excitation(sound: Sound, s: SpectrumSettings, start: float, end: float) -> SpectrumResult:
    """Excitation along the basilar membrane at the middle of ``[start, end]``, in Bark."""
    return _engine_curve(sound, s, start, end, "excitation", EXCITATION_SCRIPT)


def _engine_curve(sound: Sound, s: SpectrumSettings, start: float, end: float, kind: str, script: str):
    if not praat_engine.available():
        raise ValueError(f"The {kind} spectrum needs the bundled Praat 7 program")
    middle = (start + end) / 2
    a = max(0.0, middle - HALF_CONTEXT)
    part = sound.extract(a, min(sound.duration, middle + HALF_CONTEXT))
    _, matrices = praat_engine.analyse(part, script.format(time=middle - a))
    x, rows = matrices["curve"]
    keep = x <= s.max_frequency if kind == "lpc" else slice(None)
    nan = float("nan")
    return SpectrumResult(kind, start, end, x[keep], rows[0][keep], nan, nan, nan, nan)


def _result(kind, start, end, spectrum, ltas, s: SpectrumSettings) -> SpectrumResult:
    db = np.asarray(call(ltas, "To Matrix").values[0])
    n = len(db)
    x1, dx = call(ltas, "Get frequency from bin number", 1), call(ltas, "Get bin width")
    freqs = x1 + dx * np.arange(n)
    keep = freqs <= s.max_frequency
    p = s.moment_power
    queries = ("Get centre of gravity", "Get standard deviation", "Get skewness", "Get kurtosis")
    moments = [call(spectrum, q, p) if spectrum is not None else float("nan") for q in queries]
    return SpectrumResult(kind, start, end, freqs[keep], db[keep], *moments)


def cpps(sound: Sound, start: float, end: float) -> float:
    """Smoothed cepstral peak prominence (dB) with Praat's standard settings (Hillenbrand-style)."""
    sound, start, end = sound.part(start, end)
    if praat_engine.available():
        body = f"""Extract part: {max(0.0, start)}, {min(sound.duration, end)}, "rectangular", 1, "yes"
To PowerCepstrogram: 60, 0.002, 5000, 50
value = Get CPPS: "no", 0.02, 0.0005, 60, 330, 0.05, "parabolic", 0.001, 0, "Straight", "Robust"
writeInfoLine: value"""
        output = praat_engine.analyse(sound, body)[0].strip()
        return float("nan") if output == "--undefined--" else float(output)
    part = _part(sound, start, end, window=False)
    cepstrogram = call(part, "To PowerCepstrogram", 60.0, 0.002, 5000.0, 50.0)
    return call(
        cepstrogram, "Get CPPS", False, 0.02, 0.0005, 60.0, 330.0, 0.05, "Parabolic", 0.001, 0.0, "Straight", "Robust"
    )
