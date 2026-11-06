"""Praat's point tiers as files: PitchTier, DurationTier, IntensityTier, AmplitudeTier, RealTier."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from phonolab.core.manipulation import Tier, write_tier
from phonolab.core.textgrid import _decode

UNITS = {"PitchTier": "Hz", "DurationTier": "relative", "IntensityTier": "dB", "AmplitudeTier": "Pa", "RealTier": ""}
SUFFIXES = tuple(f".{name.lower()}" for name in UNITS)

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class TierFileError(Exception):
    pass


@dataclass
class TierFile:
    object_class: str
    xmin: float
    xmax: float
    tier: Tier

    @property
    def unit(self) -> str:
        return UNITS[self.object_class]

    def save(self, path: Path) -> None:
        write_tier(str(path), self.object_class, self.xmin, self.xmax, self.tier)


def read_tier(path: str | Path) -> TierFile:
    """Read a tier saved as Praat text, in the long or short format."""
    text = _decode(Path(path).read_bytes())
    match = re.search(r'Object class = "(\w+)', text)
    if match is None or match.group(1) not in UNITS:
        raise TierFileError(f"{Path(path).name} is not a Praat tier in text format")
    body = re.sub(r"\[[^\]]*\]", " ", text[match.end() :].split("\n", 1)[-1])  # drop "points [1]:" labels
    numbers = [float(n) for n in _NUMBER.findall(body)]
    if len(numbers) < 3 or len(numbers) < 3 + 2 * int(numbers[2]):
        raise TierFileError(f"{Path(path).name} is incomplete")
    n = int(numbers[2])
    points = np.array(numbers[3 : 3 + 2 * n]).reshape(n, 2)
    return TierFile(match.group(1), numbers[0], numbers[1], Tier(points[:, 0].copy(), points[:, 1].copy()))
