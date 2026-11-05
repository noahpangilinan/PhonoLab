"""Point and range queries over analysis results (the Praat "Query" menu)."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from phonolab.core.analysis import FormantResult, FormantSettings, IntensityResult, PitchResult, praat_formant
from phonolab.core.sound import Sound


def value_at(times: np.ndarray, values: np.ndarray, t: float) -> float:
    """Linear interpolation that returns NaN outside the frames or across unvoiced gaps."""
    if len(times) == 0 or t < times[0] or t > times[-1]:
        return float("nan")
    i = int(np.searchsorted(times, t))
    if i == 0:
        return float(values[0])
    t0, t1 = times[i - 1], times[i]
    v0, v1 = values[i - 1], values[i]
    if np.isnan(v0) or np.isnan(v1):
        # Praat reports undefined if the nearest frame is unvoiced.
        nearest = v0 if t - t0 <= t1 - t else v1
        return float(nearest) if not np.isnan(nearest) else float("nan")
    return float(v0 + (v1 - v0) * (t - t0) / (t1 - t0))


@dataclass(frozen=True)
class RangeStats:
    mean: float
    minimum: float
    maximum: float
    stdev: float
    n_frames: int
    median: float = float("nan")
    time_of_minimum: float = float("nan")
    time_of_maximum: float = float("nan")

    @classmethod
    def of(cls, values: np.ndarray, times: np.ndarray | None = None) -> RangeStats:
        defined = ~np.isnan(values)
        v = values[defined]
        if len(v) == 0:
            nan = float("nan")
            return cls(nan, nan, nan, nan, 0)
        t = times[defined] if times is not None else None
        return cls(
            float(v.mean()),
            float(v.min()),
            float(v.max()),
            float(v.std(ddof=1)) if len(v) > 1 else 0.0,
            len(v),
            float(np.median(v)),
            float(t[np.argmin(v)]) if t is not None else float("nan"),
            float(t[np.argmax(v)]) if t is not None else float("nan"),
        )


def _in_range(times: np.ndarray, start: float, end: float) -> np.ndarray:
    start, end = sorted((start, end))
    return (times >= start) & (times <= end)


def pitch_at(p: PitchResult, t: float) -> float:
    return value_at(p.times, p.frequencies, t)


def pitch_stats(p: PitchResult, start: float, end: float) -> RangeStats:
    mask = _in_range(p.times, start, end)
    return RangeStats.of(p.frequencies[mask], p.times[mask])


def pitch_mean_abs_slope(p: PitchResult, start: float, end: float) -> float:
    """Mean absolute F0 slope (Hz/s) over consecutive voiced frames, like Praat's "Get mean absolute slope"."""
    mask = _in_range(p.times, start, end)
    t, f = p.times[mask], p.frequencies[mask]
    slopes = np.abs(np.diff(f)) / np.diff(t)
    slopes = slopes[~np.isnan(slopes)]
    return float(slopes.mean()) if len(slopes) else float("nan")


def semitones(hz: float, reference: float = 100.0) -> float:
    return float(12 * np.log2(hz / reference)) if hz and not np.isnan(hz) else float("nan")


def formants_at(f: FormantResult, t: float) -> list[float]:
    return [value_at(f.times, row, t) for row in f.frequencies]


def formant_stats(f: FormantResult, start: float, end: float) -> list[RangeStats]:
    mask = _in_range(f.times, start, end)
    return [RangeStats.of(row[mask], f.times[mask]) for row in f.frequencies]


def formant_bandwidths_at(sound: Sound, s: FormantSettings, t: float) -> list[float]:
    """Formant bandwidths at ``t``, from a short Burg analysis around it (not kept in bulk results)."""
    margin = 2 * s.window_length
    if sound.is_long:
        a = max(0.0, t - margin)
        return formant_bandwidths_at(sound.extract(a, min(sound.duration, t + margin)), s, t - a)
    part = sound.praat.extract_part(
        from_time=max(0.0, t - margin), to_time=min(sound.duration, t + margin), preserve_times=True
    )
    formant = praat_formant(part, s)
    return [formant.get_bandwidth_at_time(i + 1, t) for i in range(int(np.ceil(s.n_formants)))]


def intensity_at(i: IntensityResult, t: float) -> float:
    return value_at(i.times, i.db, t)


def intensity_stats(i: IntensityResult, start: float, end: float) -> RangeStats:
    """Mean intensity is energy-averaged, as Praat's "Get mean (energy)" does."""
    mask = _in_range(i.times, start, end)
    v = i.db[mask]
    stats = RangeStats.of(v, i.times[mask])
    if stats.n_frames:
        energy_mean = 10 * np.log10(np.mean(10 ** (v[~np.isnan(v)] / 10)))
        stats = replace(stats, mean=float(energy_mean))
    return stats


def fmt(value: float, unit: str, decimals: int = 2) -> str:
    if value is None or np.isnan(value):
        return "--undefined--"
    return f"{value:.{decimals}f} {unit}" if unit else f"{value:.{decimals}f}"
