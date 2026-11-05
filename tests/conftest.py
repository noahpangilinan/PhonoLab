import gc

import numpy as np
import pytest
from scipy.signal import lfilter

from phonolab.core.sound import Sound, remove_stale_long_files


def make_vowel(f0=120.0, formants=(700, 1220, 2600), duration=0.6, sr=16000) -> Sound:
    """Pulse train through second-order resonators: a crude but well-defined vowel."""
    n = int(duration * sr)
    source = np.zeros(n)
    source[:: int(sr / f0)] = 1.0
    y = source
    for f in formants:
        bw = 80.0
        r = np.exp(-np.pi * bw / sr)
        a = [1, -2 * r * np.cos(2 * np.pi * f / sr), r * r]
        y = lfilter([1 - r], a, y)
    return Sound(0.5 * y / np.max(np.abs(y)), sr)


def make_sine(freq=200.0, amplitude=0.5, duration=1.0, sr=16000, channels=1) -> Sound:
    t = np.arange(int(duration * sr)) / sr
    x = amplitude * np.sin(2 * np.pi * freq * t)
    return Sound(np.column_stack([x] * channels), sr)


@pytest.fixture(scope="session", autouse=True)
def clean_long_sound_files():
    """Long-sound tests leave working files behind while their maps are open."""
    yield
    gc.collect()
    remove_stale_long_files()


@pytest.fixture
def vowel():
    return make_vowel()


@pytest.fixture
def sine():
    return make_sine()
