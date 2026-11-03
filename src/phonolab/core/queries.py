"""Point and range queries over analysis results (the Praat "Query" menu)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from phonolab.core.analysis import FormantResult, IntensityResult, PitchResult


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

    @classmethod
    def of(cls, values: np.ndarray) -> RangeStats:
        v = values[~np.isnan(values)]
        if len(v) == 0:
            nan = float("nan")
            return cls(nan, nan, nan, nan, 0)
        return cls(
            float(v.mean()),
            float(v.min()),
            float(v.max()),
            float(v.std(ddof=1)) if len(v) > 1 else 0.0,
            len(v),
        )


def _in_range(times: np.ndarray, start: float, end: float) -> np.ndarray:
    start, end = sorted((start, end))
    return (times >= start) & (times <= end)


def pitch_at(p: PitchResult, t: float) -> float:
    return value_at(p.times, p.frequencies, t)


def pitch_stats(p: PitchResult, start: float, end: float) -> RangeStats:
    return RangeStats.of(p.frequencies[_in_range(p.times, start, end)])


def formants_at(f: FormantResult, t: float) -> list[float]:
    return [value_at(f.times, row, t) for row in f.frequencies]


def formant_stats(f: FormantResult, start: float, end: float) -> list[RangeStats]:
    mask = _in_range(f.times, start, end)
    return [RangeStats.of(row[mask]) for row in f.frequencies]


def intensity_at(i: IntensityResult, t: float) -> float:
    return value_at(i.times, i.db, t)


def intensity_stats(i: IntensityResult, start: float, end: float) -> RangeStats:
    """Mean intensity is energy-averaged, as Praat's "Get mean (energy)" does."""
    v = i.db[_in_range(i.times, start, end)]
    stats = RangeStats.of(v)
    if stats.n_frames:
        energy_mean = 10 * np.log10(np.mean(10 ** (v[~np.isnan(v)] / 10)))
        stats = RangeStats(float(energy_mean), stats.minimum, stats.maximum, stats.stdev, stats.n_frames)
    return stats


def fmt(value: float, unit: str, decimals: int = 2) -> str:
    return "--undefined--" if value is None or np.isnan(value) else f"{value:.{decimals}f} {unit}"
