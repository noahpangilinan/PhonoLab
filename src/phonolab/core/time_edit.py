"""What an audio edit does to everything else on the timeline.

One edit replaces ``[start, start + removed)`` with ``inserted`` seconds of new sound:

- cut (nothing inserted): labels are trimmed, and anything wholly inside the cut goes.
- insert (nothing removed): later items move right. An interval around the insertion stretches over
  it; at a boundary the new sound gets an empty interval of its own, so no label claims it.
- replace (both): the stretch is rescaled to the new length, so its labels survive.

Times are the exact sample times of the edit, so annotations stay on the samples they marked.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from phonolab.core.textgrid import EPSILON, Interval, IntervalTier, Point, PointTier, TextGrid, TextGridError


def _ramp(n: int) -> np.ndarray:
    """Rises smoothly from 0 to 1 over ``n`` samples, as a column to scale every channel."""
    return (0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n))[:, np.newaxis]


def smooth_joins(
    samples: np.ndarray, start: int, end: int, inserted: np.ndarray | None, length: int
) -> tuple[int, np.ndarray | None]:
    """Crossfade the joins of an edit. Returns the ``end`` and ``inserted`` to use instead.

    Each crossfade blends in what would have continued past the join, which exists because it's the audio
    being removed or the audio beside the insertion. So the sound comes out exactly the same length, no
    sample before the join changes, and labels stay on the samples they marked.
    """
    total = len(samples)
    if inserted is None or len(inserted) == 0:
        n = min(length, end - start, total - end)
        if start == 0 or n <= 0:  # a cut from the very start or to the very end joins nothing
            return end, inserted
        ramp = _ramp(n)
        return end + n, samples[start : start + n] * (1 - ramp) + samples[end : end + n] * ramp
    new = np.array(inserted, dtype=float)
    n = min(length, len(new) // 2)
    if n == 0:
        return end, new
    ramp = _ramp(n)
    if start > 0:  # from what would have followed, held at the last sample if the sound runs out
        following = samples[min(start, total - 1) : start + n]
        following = np.concatenate([following, np.repeat(following[-1:], n - len(following), axis=0)])
        new[:n] = following * (1 - ramp) + new[:n] * ramp
    if end < total:  # into what comes next, from just before it, held at the first sample at the very start
        leading = samples[max(end - n, 0) : end] if end > 0 else samples[:1]
        leading = np.concatenate([np.repeat(leading[:1], n - len(leading), axis=0), leading])
        new[-n:] = new[-n:] * (1 - ramp) + leading * ramp
    return end, new


@dataclass(frozen=True)
class Splice:
    start: float
    removed: float
    inserted: float

    @property
    def end(self) -> float:
        return self.start + self.removed

    @property
    def change(self) -> float:
        return self.inserted - self.removed

    def moved(self, t: float) -> float:
        """Where a boundary at ``t`` ends up. Those inside a cut collapse onto its start."""
        if t <= self.start:
            return t
        if t >= self.end:
            return t + self.change
        return self.start + (t - self.start) * self.inserted / self.removed

    def keeps(self, t: float) -> bool:
        """Whether a point at ``t`` survives. The sample at the start of a cut goes; the one at its end stays."""
        return self.inserted > 0 or not self.start <= t < self.end

    def moved_point(self, t: float) -> float:
        """As ``moved``, but a point at an insertion moves with the sample it marks."""
        return t + self.inserted if self.removed == 0 and t >= self.start else self.moved(t)

    def within(self, xmin: float, xmax: float) -> Splice | None:
        """This edit as seen by a tier covering ``[xmin, xmax]``: None if it doesn't reach the tier."""
        if self.start > xmax + EPSILON or (self.removed > 0 and self.start >= xmax - EPSILON) or self.end < xmin:
            return None
        if self.end <= xmax + EPSILON or self.inserted > 0:
            return self
        return Splice(self.start, xmax - self.start, 0.0)

    # ------------------------------------------------------------------ TextGrids

    def applied_to(self, grid: TextGrid) -> TextGrid:
        """A copy of ``grid`` following this edit. Raises TextGridError if nothing of it would remain."""
        edit = self.within(grid.xmin, grid.xmax)
        if edit is None:
            return grid.copy()
        xmax = edit.moved(grid.xmax) if edit.removed or edit.start < grid.xmax else grid.xmax + edit.inserted
        if xmax - grid.xmin < EPSILON:
            raise TextGridError("This would remove the whole TextGrid")
        return TextGrid(grid.xmin, xmax, [edit._tier(tier, xmax) for tier in grid.tiers])

    def _tier(self, tier: IntervalTier | PointTier, xmax: float) -> IntervalTier | PointTier:
        if isinstance(tier, PointTier):
            points = [Point(self.moved_point(p.time), p.mark) for p in tier.points if self.keeps(p.time)]
            return PointTier(tier.name, tier.xmin, xmax, points)
        intervals = self._insert(tier) if self.removed == 0 else self._replace(tier)
        intervals[0].xmin, intervals[-1].xmax = tier.xmin, xmax
        for left, right in zip(intervals, intervals[1:], strict=False):
            right.xmin = left.xmax
        return IntervalTier(tier.name, tier.xmin, xmax, intervals)

    def _insert(self, tier: IntervalTier) -> list[Interval]:
        at, gap = self.start, self.inserted
        out = []
        for iv in tier.intervals:
            if iv.xmax <= at + EPSILON:
                out.append(Interval(iv.xmin, iv.xmax, iv.text))
            elif iv.xmin >= at - EPSILON:
                out.append(Interval(iv.xmin + gap, iv.xmax + gap, iv.text))
            else:
                out.append(Interval(iv.xmin, iv.xmax + gap, iv.text))  # the insertion is inside this interval
        at_boundary = any(abs(iv.xmin - at) < EPSILON or abs(iv.xmax - at) < EPSILON for iv in tier.intervals)
        if at_boundary:
            place = sum(1 for iv in out if iv.xmax <= at + EPSILON)
            out.insert(place, Interval(at, at + gap))
        return out

    def _replace(self, tier: IntervalTier) -> list[Interval]:
        moved = [Interval(self.moved(iv.xmin), self.moved(iv.xmax), iv.text) for iv in tier.intervals]
        return [iv for iv in moved if iv.xmax - iv.xmin > EPSILON]
