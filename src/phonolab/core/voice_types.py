"""Result types shared by voice analysis and corrections."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VoicingResult:
    """Voiced stretches; everything between them is unvoiced."""

    starts: np.ndarray
    ends: np.ndarray

    def voiced_at(self, t: float) -> bool:
        i = int(np.searchsorted(self.starts, t, side="right")) - 1
        return i >= 0 and t < self.ends[i]

    def voiced_fraction(self, start: float, end: float) -> float:
        start, end = sorted((start, end))
        if end <= start:
            return float("nan")
        overlap = np.clip(np.minimum(self.ends, end) - np.maximum(self.starts, start), 0, None)
        return float(overlap.sum() / (end - start))
