"""Pitch and duration manipulation with PSOLA resynthesis (Praat's Manipulation object).

Tiers travel to and from Praat as short text files: adding thousands of points
one Praat call at a time is far slower than writing and reading one file.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

import numpy as np
import parselmouth
from parselmouth.praat import call

from phonolab.core.analysis import setting
from phonolab.core.sound import Sound


@dataclass(frozen=True)
class ManipulationSettings:
    title = "Manipulation"
    time_step: float = setting(0.01, "Time step", "s", 0.001, 0.1, decimals=3)
    floor: float = setting(75.0, "Minimum pitch", "Hz", 10.0, 1000.0)
    ceiling: float = setting(600.0, "Maximum pitch", "Hz", 50.0, 3000.0)


@dataclass(frozen=True, eq=False)
class Tier:
    """Time-value points (a PitchTier in Hz, or a DurationTier of relative factors)."""

    times: np.ndarray
    values: np.ndarray

    @classmethod
    def empty(cls) -> Tier:
        return cls(np.zeros(0), np.zeros(0))

    def __len__(self) -> int:
        return len(self.times)

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Tier)
            and np.array_equal(self.times, other.times)
            and np.array_equal(self.values, other.values)
        )

    def value_at(self, t: float, default: float = float("nan")) -> float:
        """Linear interpolation, constant beyond the first/last point (as Praat's tiers)."""
        if len(self.times) == 0:
            return default
        return float(np.interp(t, self.times, self.values))

    def without_range(self, start: float, end: float) -> Tier:
        keep = (self.times < start) | (self.times > end)
        return Tier(self.times[keep], self.values[keep])

    def with_point(self, t: float, value: float) -> Tier:
        times = np.append(self.times, t)
        values = np.append(self.values, value)
        order = np.argsort(times, kind="stable")
        return Tier(times[order], values[order])


# --------------------------------------------------------------------------- Praat tier files


def write_tier(path: str, object_class: str, xmin: float, xmax: float, tier: Tier) -> None:
    lines = ['File type = "ooTextFile"', f'Object class = "{object_class}"', "", repr(xmin), repr(xmax), str(len(tier))]
    for t, v in zip(tier.times, tier.values, strict=True):
        lines += [repr(float(t)), repr(float(v))]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _read_tier(praat_tier) -> Tier:
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        call(praat_tier, "Save as short text file", path)
        with open(path, encoding="utf-8") as fh:
            numbers = [line.strip() for line in fh.readlines()[3:] if line.strip()]
    finally:
        os.remove(path)
    n = int(numbers[2])
    data = np.array(numbers[3 : 3 + 2 * n], dtype=float).reshape(n, 2) if n else np.zeros((0, 2))
    return Tier(data[:, 0].copy(), data[:, 1].copy())


def _load_tier(object_class: str, xmin: float, xmax: float, tier: Tier):
    fd, path = tempfile.mkstemp(suffix=f".{object_class}")
    os.close(fd)
    try:
        write_tier(path, object_class, xmin, xmax, tier)
        return parselmouth.read(path)
    finally:
        os.remove(path)


# --------------------------------------------------------------------------- analysis & resynthesis

# Manipulation objects are expensive to build; keep the latest per (sound, settings).
_cache: dict[tuple, object] = {}


def _manipulation(sound: Sound, s: ManipulationSettings):
    key = (id(sound), s)
    if key not in _cache:
        _cache.clear()
        _cache[key] = call(sound.praat, "To Manipulation", s.time_step, s.floor, s.ceiling)
    return _cache[key]


def analyse(sound: Sound, s: ManipulationSettings) -> Tier:
    """The pitch tier Praat derives for manipulation (one point per voiced frame)."""
    return _read_tier(call(_manipulation(sound, s), "Extract pitch tier"))


def resynthesize(
    sound: Sound, s: ManipulationSettings, pitch: Tier, duration: Tier, gain: Tier | None = None
) -> tuple[np.ndarray, float]:
    """PSOLA (overlap-add) resynthesis with the given pitch and duration tiers, then any loudness changes."""
    manipulation = _manipulation(sound, s).copy()
    xmin, xmax = 0.0, sound.duration
    call([manipulation, _load_tier("PitchTier", xmin, xmax, pitch)], "Replace pitch tier")
    call([manipulation, _load_tier("DurationTier", xmin, xmax, duration)], "Replace duration tier")
    out = call(manipulation, "Get resynthesis (overlap-add)")
    samples, sr = np.asarray(out.values[0]), float(out.sampling_frequency)
    if gain is not None and len(gain):
        samples = apply_gain(samples, sr, gain, duration, sound.duration)
    return samples, sr


def apply_gain(samples: np.ndarray, sr: float, gain: Tier, duration: Tier, total: float) -> np.ndarray:
    """Change loudness over time. ``gain`` is in dB on the original timeline, so follow any duration changes."""
    moved = [map_time(duration, float(t), total) for t in gain.times]
    return samples * 10 ** (np.interp(np.arange(len(samples)) / sr, moved, gain.values) / 20)


def stylize(pitch: Tier, semitones: float, sound: Sound) -> Tier:
    """Praat's "Stylize": keep only the points needed to stay within ``semitones`` of the contour."""
    praat_tier = _load_tier("PitchTier", 0.0, sound.duration, pitch)
    call(praat_tier, "Stylize", semitones, "Semitones")
    return _read_tier(praat_tier)


def shift_semitones(pitch: Tier, semitones: float, start: float, end: float) -> Tier:
    inside = (pitch.times >= start) & (pitch.times <= end)
    values = pitch.values.copy()
    values[inside] *= 2 ** (semitones / 12)
    return Tier(pitch.times, values)


def flatten(pitch: Tier, start: float, end: float) -> Tier:
    """Set every point in the range to the range's mean (a monotone)."""
    inside = (pitch.times >= start) & (pitch.times <= end)
    if not inside.any():
        return pitch
    values = pitch.values.copy()
    values[inside] = values[inside].mean()
    return Tier(pitch.times, values)


def set_duration_factor(duration: Tier, start: float, end: float, factor: float) -> Tier:
    """Scale ``[start, end]`` by ``factor``, leaving the rest at its current factor (Praat-style plateau)."""
    return _set_plateau(duration, start, end, factor, default=1.0)


def set_gain(gain: Tier, start: float, end: float, decibels: float) -> Tier:
    """Make ``[start, end]`` louder or quieter by ``decibels``, leaving the rest as it is."""
    return _set_plateau(gain, start, end, decibels, default=0.0)


def _set_plateau(tier: Tier, start: float, end: float, value: float, default: float, edge: float = 1e-4) -> Tier:
    outside_before = tier.value_at(start - edge, default)
    outside_after = tier.value_at(end + edge, default)
    tier = tier.without_range(start - edge, end + edge)
    for t, v in ((start - edge, outside_before), (start, value), (end, value), (end + edge, outside_after)):
        if t >= 0:
            tier = tier.with_point(t, v)
    return tier


def map_time(duration: Tier, t: float, total: float) -> float:
    """Where original time ``t`` ends up after duration manipulation."""
    if len(duration) == 0:
        return t
    grid = np.linspace(0.0, total, max(2, int(total * 1000) + 1))
    factors = np.interp(grid, duration.times, duration.values)
    new_times = np.concatenate([[0.0], np.cumsum((factors[1:] + factors[:-1]) / 2 * np.diff(grid))])
    return float(np.interp(t, grid, new_times))
