"""TextGrid annotation model with Praat-compatible text (long/short) file I/O."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

from phonolab.core.ipa import to_unicode

# Two boundaries closer than this are considered the same boundary.
EPSILON = 1e-9


class TextGridError(Exception):
    pass


@dataclass
class Interval:
    xmin: float
    xmax: float
    text: str = ""


@dataclass
class Point:
    time: float
    mark: str = ""


@dataclass
class IntervalTier:
    name: str
    xmin: float
    xmax: float
    intervals: list[Interval] = field(default_factory=list)

    def __post_init__(self):
        if not self.intervals:
            self.intervals = [Interval(self.xmin, self.xmax)]

    @property
    def boundaries(self) -> list[float]:
        """Interior boundary times (excludes the tier's own edges)."""
        return [iv.xmin for iv in self.intervals[1:]]

    def interval_at(self, t: float) -> int:
        """Index of the interval containing ``t`` (boundaries belong to the right interval)."""
        if t <= self.xmin:
            return 0
        for i, iv in enumerate(self.intervals):
            if t < iv.xmax:
                return i
        return len(self.intervals) - 1

    def boundary_near(self, t: float, tolerance: float) -> int | None:
        """Index ``i`` of the boundary between intervals i-1 and i closest to ``t``."""
        best, best_d = None, tolerance
        for i in range(1, len(self.intervals)):
            d = abs(self.intervals[i].xmin - t)
            if d <= best_d:
                best, best_d = i, d
        return best

    def add_boundary(self, t: float) -> int:
        """Split the interval at ``t``; the left part keeps the text. Returns the boundary index."""
        if not (self.xmin + EPSILON < t < self.xmax - EPSILON):
            raise TextGridError("Boundary must lie strictly inside the tier")
        i = self.interval_at(t)
        iv = self.intervals[i]
        if abs(iv.xmin - t) < EPSILON or abs(iv.xmax - t) < EPSILON:
            raise TextGridError("There is already a boundary at this time")
        self.intervals[i : i + 1] = [Interval(iv.xmin, t, iv.text), Interval(t, iv.xmax, "")]
        return i + 1

    def remove_boundary(self, index: int) -> None:
        """Merge intervals index-1 and index, joining their texts like Praat does."""
        if not 1 <= index < len(self.intervals):
            raise TextGridError("No such boundary")
        left, right = self.intervals[index - 1], self.intervals[index]
        text = left.text + right.text
        self.intervals[index - 1 : index + 1] = [Interval(left.xmin, right.xmax, text)]

    def move_boundary(self, index: int, t: float) -> float:
        """Move a boundary, clamped between its neighbours. Returns the time actually used."""
        if not 1 <= index < len(self.intervals):
            raise TextGridError("No such boundary")
        left, right = self.intervals[index - 1], self.intervals[index]
        t = min(max(t, left.xmin + EPSILON * 10), right.xmax - EPSILON * 10)
        left.xmax = right.xmin = t
        return t

    @property
    def items(self) -> list[Interval]:
        return self.intervals

    def get_text(self, index: int) -> str:
        return self.intervals[index].text

    def set_text(self, index: int, text: str) -> None:
        self.intervals[index].text = text


@dataclass
class PointTier:
    name: str
    xmin: float
    xmax: float
    points: list[Point] = field(default_factory=list)

    def point_near(self, t: float, tolerance: float) -> int | None:
        best, best_d = None, tolerance
        for i, p in enumerate(self.points):
            d = abs(p.time - t)
            if d <= best_d:
                best, best_d = i, d
        return best

    def add_point(self, t: float, mark: str = "") -> int:
        if not (self.xmin <= t <= self.xmax):
            raise TextGridError("Point must lie inside the tier")
        if any(abs(p.time - t) < EPSILON for p in self.points):
            raise TextGridError("There is already a point at this time")
        i = sum(1 for p in self.points if p.time < t)
        self.points.insert(i, Point(t, mark))
        return i

    def remove_point(self, index: int) -> None:
        del self.points[index]

    def move_point(self, index: int, t: float) -> float:
        lo = self.points[index - 1].time + EPSILON * 10 if index > 0 else self.xmin
        hi = self.points[index + 1].time - EPSILON * 10 if index + 1 < len(self.points) else self.xmax
        t = min(max(t, lo), hi)
        self.points[index].time = t
        return t

    @property
    def items(self) -> list[Point]:
        return self.points

    def get_text(self, index: int) -> str:
        return self.points[index].mark

    def set_text(self, index: int, text: str) -> None:
        self.points[index].mark = text


Tier = IntervalTier | PointTier


@dataclass
class TextGrid:
    xmin: float
    xmax: float
    tiers: list[Tier] = field(default_factory=list)

    @classmethod
    def for_duration(cls, duration: float, interval_tiers=("words",), point_tiers=()) -> TextGrid:
        tg = cls(0.0, duration)
        for name in interval_tiers:
            tg.tiers.append(IntervalTier(name, 0.0, duration))
        for name in point_tiers:
            tg.tiers.append(PointTier(name, 0.0, duration))
        return tg

    def copy(self) -> TextGrid:
        return copy.deepcopy(self)

    # ------------------------------------------------------------------ reading

    @classmethod
    def read(cls, path: str | Path) -> TextGrid:
        return cls.parse(_decode(Path(path).read_bytes()))

    @classmethod
    def parse(cls, text: str) -> TextGrid:
        tokens = _tokens(text)
        try:
            if next(tokens) != "ooTextFile" or next(tokens) != "TextGrid":
                raise TextGridError("Not a text TextGrid file")
            xmin, xmax = float(next(tokens)), float(next(tokens))
            tg = cls(xmin, xmax)
            if next(tokens) != "<exists>":
                return tg
            for _ in range(int(next(tokens))):
                kind, name = next(tokens), next(tokens)
                txmin, txmax, n = float(next(tokens)), float(next(tokens)), int(next(tokens))
                if kind == "IntervalTier":
                    ivs = [Interval(float(next(tokens)), float(next(tokens)), next(tokens)) for _ in range(n)]
                    tg.tiers.append(IntervalTier(name, txmin, txmax, ivs))
                elif kind == "TextTier":
                    pts = [Point(float(next(tokens)), next(tokens)) for _ in range(n)]
                    tg.tiers.append(PointTier(name, txmin, txmax, pts))
                else:
                    raise TextGridError(f"Unknown tier class {kind!r}")
        except StopIteration:
            raise TextGridError("Unexpected end of TextGrid file") from None
        except ValueError as e:
            raise TextGridError(f"Malformed TextGrid file: {e}") from None
        return tg

    # ------------------------------------------------------------------ writing

    def write(self, path: str | Path, short: bool = False) -> None:
        Path(path).write_text(self.to_short_text() if short else self.to_text(), encoding="utf-8")

    def to_text(self) -> str:
        out = [
            'File type = "ooTextFile"',
            'Object class = "TextGrid"',
            "",
            f"xmin = {_num(self.xmin)} ",
            f"xmax = {_num(self.xmax)} ",
        ]
        if not self.tiers:
            out.append("tiers? <absent> ")
            return "\n".join(out) + "\n"
        out += ["tiers? <exists> ", f"size = {len(self.tiers)} ", "item []: "]
        for k, tier in enumerate(self.tiers, 1):
            is_iv = isinstance(tier, IntervalTier)
            items = tier.intervals if is_iv else tier.points
            word = "intervals" if is_iv else "points"
            out += [
                f"    item [{k}]:",
                f'        class = "{"IntervalTier" if is_iv else "TextTier"}" ',
                f"        name = {_str(tier.name)} ",
                f"        xmin = {_num(tier.xmin)} ",
                f"        xmax = {_num(tier.xmax)} ",
                f"        {word}: size = {len(items)} ",
            ]
            for j, item in enumerate(items, 1):
                out.append(f"        {word} [{j}]:")
                if is_iv:
                    out += [
                        f"            xmin = {_num(item.xmin)} ",
                        f"            xmax = {_num(item.xmax)} ",
                        f"            text = {_str(item.text)} ",
                    ]
                else:
                    out += [
                        f"            number = {_num(item.time)} ",
                        f"            mark = {_str(item.mark)} ",
                    ]
        return "\n".join(out) + "\n"

    def to_short_text(self) -> str:
        out = ['File type = "ooTextFile"', 'Object class = "TextGrid"', "", _num(self.xmin), _num(self.xmax)]
        if not self.tiers:
            out.append("<absent>")
            return "\n".join(out) + "\n"
        out += ["<exists>", str(len(self.tiers))]
        for tier in self.tiers:
            if isinstance(tier, IntervalTier):
                out += ['"IntervalTier"', _str(tier.name), _num(tier.xmin), _num(tier.xmax), str(len(tier.intervals))]
                for iv in tier.intervals:
                    out += [_num(iv.xmin), _num(iv.xmax), _str(iv.text)]
            else:
                out += ['"TextTier"', _str(tier.name), _num(tier.xmin), _num(tier.xmax), str(len(tier.points))]
                for p in tier.points:
                    out += [_num(p.time), _str(p.mark)]
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- moving several boundaries


def aligned_handles(grid: TextGrid, t: float, tolerance: float = 1e-6) -> list[tuple[int, int]]:
    """(tier, index) of every boundary or point at ``t``, across all tiers."""
    found = []
    for i, tier in enumerate(grid.tiers):
        near = tier.boundary_near(t, tolerance) if isinstance(tier, IntervalTier) else tier.point_near(t, tolerance)
        if near is not None:
            found.append((i, near))
    return found


def _room(tier: Tier, index: int) -> tuple[float, float]:
    """How far a boundary or point can move before it reaches a neighbour."""
    margin = EPSILON * 10
    if isinstance(tier, IntervalTier):
        return tier.intervals[index - 1].xmin + margin, tier.intervals[index].xmax - margin
    low = tier.points[index - 1].time + margin if index > 0 else tier.xmin
    high = tier.points[index + 1].time - margin if index + 1 < len(tier.points) else tier.xmax
    return low, high


def move_together(grid: TextGrid, handles: list[tuple[int, int]], t: float) -> float:
    """Move boundaries and points to one time, stopping where the first of them would hit a neighbour."""
    rooms = [_room(grid.tiers[i], j) for i, j in handles]
    t = min(max(t, max(r[0] for r in rooms)), min(r[1] for r in rooms))
    for i, j in handles:
        tier = grid.tiers[i]
        tier.move_boundary(j, t) if isinstance(tier, IntervalTier) else tier.move_point(j, t)
    return t


def rubber_band(tier: IntervalTier, original: IntervalTier, index: int, t: float, low: float, high: float) -> float:
    """Move a boundary and stretch those around it in proportion, between the fixed times ``low`` and ``high``.

    Works from ``original`` so that a long drag doesn't build up rounding, and boundaries keep their order.
    """
    start = original.intervals[index].xmin
    margin = EPSILON * 1000
    t = min(max(t, low + margin), high - margin)
    for i in range(1, len(original.intervals)):
        b = original.intervals[i].xmin
        if low < b <= start:
            moved = low + (b - low) * (t - low) / (start - low)
        elif start < b < high:
            moved = t + (b - start) * (high - t) / (high - start)
        else:
            continue
        tier.intervals[i - 1].xmax = tier.intervals[i].xmin = moved
    return t


# ---------------------------------------------------------------------- converting, extracting, merging


def points_from_intervals(tier: IntervalTier, where: str = "centre") -> PointTier:
    """A point for each labelled interval, at its ``start``, ``centre`` or ``end``, keeping the labels."""
    times = {
        "start": lambda iv: iv.xmin,
        "centre": lambda iv: (iv.xmin + iv.xmax) / 2,
        "end": lambda iv: iv.xmax,
    }[where]
    points = [Point(times(iv), iv.text) for iv in tier.intervals if iv.text.strip()]
    return PointTier(f"{tier.name}_{where}", tier.xmin, tier.xmax, points)


def intervals_from_points(tier: PointTier) -> IntervalTier:
    """Boundaries at the points. Each interval takes the label of the point that starts it."""
    out = IntervalTier(f"{tier.name}_intervals", tier.xmin, tier.xmax)
    for p in tier.points:
        if abs(p.time - tier.xmin) < EPSILON:
            out.intervals[0].text = p.mark
        elif abs(p.time - tier.xmax) >= EPSILON:
            out.intervals[out.add_boundary(p.time)].text = p.mark
    return out


def extract_tier(grid: TextGrid, index: int) -> TextGrid:
    return TextGrid(grid.xmin, grid.xmax, [copy.deepcopy(grid.tiers[index])])


def merge_tiers(grid: TextGrid, other: TextGrid, tolerance: float = 1e-3) -> None:
    """Add copies of ``other``'s tiers to ``grid``. They must cover the same time, or labels would be misplaced."""
    if abs(other.xmax - grid.xmax) > tolerance or abs(other.xmin - grid.xmin) > tolerance:
        raise TextGridError(
            f"That TextGrid covers {other.xmin:g} to {other.xmax:g} s, and this one {grid.xmin:g} to {grid.xmax:g} s"
        )
    names = {tier.name for tier in grid.tiers}
    for tier in other.tiers:
        new = copy.deepcopy(tier)
        new.xmin, new.xmax = grid.xmin, grid.xmax
        if isinstance(new, IntervalTier):
            new.intervals[0].xmin, new.intervals[-1].xmax = grid.xmin, grid.xmax
        else:
            new.points = [p for p in new.points if grid.xmin <= p.time <= grid.xmax]
        number = 2
        while new.name in names:
            new.name = f"{tier.name}_{number}"
            number += 1
        names.add(new.name)
        grid.tiers.append(new)


def find(tg: TextGrid, pattern: str, regex: bool = False, case_sensitive: bool = False) -> list[tuple[int, int]]:
    """(tier, item) of every label matching ``pattern``, in time order (then tier order).

    Labels match in their typed form or with Praat backslash codes shown as symbols,
    so searching "æ" finds "\ae" and vice versa.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        raise TextGridError(f"Invalid pattern: {e}") from None
    hits = []
    for ti, tier in enumerate(tg.tiers):
        for i, item in enumerate(tier.items):
            text = tier.get_text(i)
            if text and (rx.search(text) or rx.search(to_unicode(text))):
                start = item.xmin if isinstance(tier, IntervalTier) else item.time
                hits.append((start, ti, i))
    return [(ti, i) for _, ti, i in sorted(hits)]


_TOKEN = re.compile(
    r'"((?:[^"]|"")*)"'  # string, "" escapes a quote
    r"|(\[[^\]]*\])"  # [index] labels in long format
    r"|(<exists>|<absent>)"
    r"|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    r"|(![^\n]*)"  # comment
)


def _tokens(text: str):
    for m in _TOKEN.finditer(text):
        string, _label, flag, number, _comment = m.groups()
        if string is not None:
            yield string.replace('""', '"')
        elif flag is not None:
            yield flag
        elif number is not None:
            yield number


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _num(x: float) -> str:
    s = repr(float(x))
    return s[:-2] if s.endswith(".0") else s


def _str(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'
