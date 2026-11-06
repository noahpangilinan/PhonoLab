"""Compare formant analyses at several ceilings (Praat's FormantPath)."""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass

import numpy as np

from phonolab.core import praat_engine
from phonolab.core.analysis import FormantSettings, setting
from phonolab.core.sound import Sound

TRACKS = 3  # stresses are scored on F1-F3, Praat's standard
TIME_STEP = 0.005
MARGIN = 0.05  # s of context around the stretch
MAX_SECONDS = 30.0


@dataclass(frozen=True)
class FormantPathSettings:
    title = "Formant ceilings"
    step: float = setting(0.05, "Ceiling step size", "", 0.01, 0.5, decimals=3)
    steps: int = setting(4, "Number of steps up and down", "", 1, 8)
    power: float = setting(1.25, "Stress power", "", 0.5, 3.0)


@dataclass(frozen=True)
class Candidate:
    ceiling: float
    stress: float  # how well F1-F3 fit smooth tracks; lower is better
    times: np.ndarray
    frequencies: np.ndarray  # (TRACKS, frames), NaN where undefined


@dataclass(frozen=True)
class FormantPathResult:
    start: float
    end: float
    candidates: list[Candidate]

    @property
    def best(self) -> int | None:
        stresses = np.array([c.stress for c in self.candidates])
        return None if np.all(np.isnan(stresses)) else int(np.nanargmin(stresses))

    @property
    def best_is_at_edge(self) -> bool:
        """The true best ceiling may lie outside the range tried."""
        return self.best in (0, len(self.candidates) - 1)


def _stress(value: str) -> float:
    try:
        return float(value)
    except ValueError:  # --undefined--
        return float("nan")


def compare_ceilings(
    sound: Sound, start: float, end: float, formants: FormantSettings, s: FormantPathSettings
) -> FormantPathResult:
    if not praat_engine.available():
        raise ValueError("Comparing formant ceilings needs the bundled Praat 7 program")
    if end - start > MAX_SECONDS:
        raise ValueError(f"Choose {MAX_SECONDS:.0f} seconds or less")
    offset = max(0.0, start - MARGIN)
    part = sound.extract(offset, min(sound.duration, end + MARGIN))
    a, b = start - offset, end - offset
    common = f"{formants.n_formants}, {formants.max_formant}, {formants.window_length}, {formants.pre_emphasis_from}"
    tracks = "\n".join(
        f'    To Matrix: {t + 1}\n    Save as short text file: folder$ + "/c" + string$ (i) + "t{t}.Matrix"\n'
        "    selectObject: f"
        for t in range(TRACKS)
    )
    candidate = f"To Formant (burg): {TIME_STEP}, {formants.n_formants}, ceiling, {formants.window_length}, " + str(
        formants.pre_emphasis_from
    )
    body = f"""To FormantPath (burg): {TIME_STEP}, {common}, {s.step}, {s.steps}
table = Down to Table (stresses): {a}, {b}, "3 3 3", {s.power}, 3, "no", 3
Save as tab-separated file: folder$ + "/stresses.Table"
for i to {2 * s.steps + 1}
    selectObject: table
    ceiling = Get value: i, "Ceiling(Hz)"
    selectObject: s
    f = {candidate}
{tracks}
endfor"""
    _, folder = praat_engine.analyse_with_files(part, body)
    try:
        with open(folder / "stresses.Table", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        candidates = []
        for i, row in enumerate(rows, 1):
            matrices = [praat_engine.read_matrix(folder / f"c{i}t{t}.Matrix") for t in range(TRACKS)]
            freqs = np.vstack([m[1][0] for m in matrices])
            freqs[freqs <= 0] = np.nan
            candidates.append(
                Candidate(float(row["Ceiling(Hz)"]), _stress(row["Stress13"]), matrices[0][0] + offset, freqs)
            )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return FormantPathResult(start, end, candidates)
