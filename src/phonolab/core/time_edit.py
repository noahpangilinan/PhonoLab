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

from phonolab.core.textgrid import EPSILON, Interval, IntervalTier, Point, PointTier, TextGrid, TextGridError


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
