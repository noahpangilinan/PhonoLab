"""Hand corrections to analyses: unvoiced stretches, octave shifts, removed and added pulses.

Corrections are stored as edits over time ranges rather than as a copy of the corrected values,
so they still apply after analysis settings change. Every measurement passes through them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from phonolab.core.analysis import PitchResult
from phonolab.core.time_edit import Splice
from phonolab.core.voice_types import VoicingResult

SUFFIX = ".corrections.json"
FORMAT_VERSION = 1


def _overlaps(item_start: float, item_end: float, start: float, end: float) -> bool:
    return item_start <= end and start <= item_end


@dataclass(frozen=True)
class Corrections:
    unvoiced: tuple[tuple[float, float], ...] = ()  # stretches with no pitch and no pulses
    octaves: tuple[tuple[float, float, float], ...] = ()  # (start, end, frequency factor)
    removed_pulses: tuple[tuple[float, float], ...] = ()
    added_pulses: tuple[float, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.unvoiced or self.octaves or self.removed_pulses or self.added_pulses)

    # ------------------------------------------------------------------ editing

    def with_unvoiced(self, start: float, end: float) -> Corrections:
        return replace(self, unvoiced=(*self.unvoiced, (start, end)))

    def with_octave(self, start: float, end: float, factor: float) -> Corrections:
        return replace(self, octaves=(*self.octaves, (start, end, factor)))

    def with_pulses_removed(self, start: float, end: float) -> Corrections:
        added = tuple(t for t in self.added_pulses if not start <= t <= end)
        return replace(self, removed_pulses=(*self.removed_pulses, (start, end)), added_pulses=added)

    def with_pulse(self, t: float) -> Corrections:
        return replace(self, added_pulses=tuple(sorted((*self.added_pulses, t))))

    def without_range(self, start: float, end: float) -> Corrections:
        """Drop every correction touching ``[start, end]``, restoring the analysis there."""
        return Corrections(
            tuple(r for r in self.unvoiced if not _overlaps(*r, start, end)),
            tuple(r for r in self.octaves if not _overlaps(r[0], r[1], start, end)),
            tuple(r for r in self.removed_pulses if not _overlaps(*r, start, end)),
            tuple(t for t in self.added_pulses if not start <= t <= end),
        )

    def shifted(self, offset: float) -> Corrections:
        """The same corrections for a stretch whose time zero is ``-offset`` in this sound's time."""
        return Corrections(
            tuple((a + offset, b + offset) for a, b in self.unvoiced),
            tuple((a + offset, b + offset, f) for a, b, f in self.octaves),
            tuple((a + offset, b + offset) for a, b in self.removed_pulses),
            tuple(t + offset for t in self.added_pulses),
        )

    def spliced(self, edit: Splice) -> Corrections:
        """These corrections after an audio edit. They were made on the old audio, so none cover new sound."""

        def ranges(items: tuple[tuple, ...]) -> tuple[tuple, ...]:
            out = []
            for start, end, *rest in items:
                before = (start, min(end, edit.start)) if start < edit.start else None
                after = (max(start, edit.end) + edit.change, end + edit.change) if end > edit.end else None
                if before and after and edit.inserted == 0:
                    out.append((before[0], after[1], *rest))
                    continue
                out += [(*part, *rest) for part in (before, after) if part and part[1] > part[0]]
            return tuple(out)

        added = [t if t < edit.start else t + edit.change for t in self.added_pulses if not edit.start <= t < edit.end]
        return Corrections(ranges(self.unvoiced), ranges(self.octaves), ranges(self.removed_pulses), tuple(added))

    # ------------------------------------------------------------------ applying to results

    def apply_pitch(self, pitch: PitchResult) -> PitchResult:
        if self.is_empty:
            return pitch
        frequencies = pitch.frequencies.copy()
        for a, b, factor in self.octaves:
            frequencies[(pitch.times >= a) & (pitch.times <= b)] *= factor
        for a, b in self.unvoiced:
            frequencies[(pitch.times >= a) & (pitch.times <= b)] = np.nan
        return PitchResult(pitch.times, frequencies)

    def apply_pulses(self, times: np.ndarray) -> np.ndarray:
        keep = np.ones(len(times), dtype=bool)
        for a, b in (*self.unvoiced, *self.removed_pulses):
            keep &= (times < a) | (times > b)
        return np.sort(np.concatenate([times[keep], np.array(self.added_pulses, dtype=float)]))

    def apply_voicing(self, voicing: VoicingResult) -> VoicingResult:
        spans = list(zip(voicing.starts, voicing.ends, strict=True))
        for a, b in self.unvoiced:
            cut = []
            for start, end in spans:
                if end <= a or start >= b:
                    cut.append((start, end))
                    continue
                if start < a:
                    cut.append((start, a))
                if end > b:
                    cut.append((b, end))
            spans = cut
        return VoicingResult(np.array([s[0] for s in spans]), np.array([s[1] for s in spans]))

    # ------------------------------------------------------------------ applying to Praat objects

    def pitch_formulas(self) -> list[str]:
        """Formulas that make the same edits to a Praat Pitch object."""
        octaves = [f"if x >= {a} and x <= {b} then self * {f} else self fi" for a, b, f in self.octaves]
        return octaves + [f"if x >= {a} and x <= {b} then 0 else self fi" for a, b in self.unvoiced]

    def pulse_commands(self) -> list[tuple]:
        """Praat commands that make the same edits to a PointProcess."""
        removed = [("Remove points between", a, b) for a, b in (*self.unvoiced, *self.removed_pulses)]
        return removed + [("Add point", t) for t in self.added_pulses]

    def pitch_script(self) -> str:
        return "".join(f'Formula: "{formula}"\n' for formula in self.pitch_formulas())

    def pulse_script(self) -> str:
        return "".join(f"{c[0]}: {', '.join(map(str, c[1:]))}\n" for c in self.pulse_commands())

    # ------------------------------------------------------------------ files

    @staticmethod
    def path_for(sound_path: Path) -> Path:
        return sound_path.with_name(sound_path.stem + SUFFIX)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"version": FORMAT_VERSION, **asdict(self)}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Corrections:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            tuple(tuple(r) for r in data.get("unvoiced", [])),
            tuple(tuple(r) for r in data.get("octaves", [])),
            tuple(tuple(r) for r in data.get("removed_pulses", [])),
            tuple(data.get("added_pulses", [])),
        )

    @classmethod
    def load_for(cls, sound_path: Path | None) -> Corrections:
        """Corrections saved next to a sound; none if there's no file or it can't be read."""
        if sound_path is not None:
            path = cls.path_for(sound_path)
            if path.exists():
                try:
                    return cls.load(path)
                except (OSError, ValueError, TypeError):
                    pass
        return cls()
