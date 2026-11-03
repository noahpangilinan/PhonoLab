import numpy as np
import pytest

from phonolab.core import spectrum
from phonolab.core.spectrum import SpectrumSettings
from tests.conftest import make_sine, make_vowel


def test_slice_peaks_at_sine_frequency():
    snd = make_sine(freq=1000, duration=0.5)
    r = spectrum.compute_slice(snd, SpectrumSettings(), 0.1, 0.3)
    assert r.frequencies[np.argmax(r.db)] == pytest.approx(1000, abs=10)
    assert r.centre_of_gravity == pytest.approx(1000, abs=20)
    assert r.frequencies.max() <= SpectrumSettings().max_frequency


def test_ltas_of_vowel_has_formant_peak():
    snd = make_vowel(formants=(700, 1220, 2600), duration=1.0)
    r = spectrum.compute_ltas(snd, SpectrumSettings(), 0, 1)
    low = (r.frequencies > 400) & (r.frequencies < 1000)
    assert r.frequencies[low][np.argmax(r.db[low])] == pytest.approx(700, abs=100)


def test_slice_range_uses_selection_or_cursor_window():
    snd = make_sine(duration=1.0)
    s = SpectrumSettings(slice_window=0.04)
    assert spectrum.slice_range(snd, s, 0.5, (0.1, 0.2)) == (0.1, 0.2)
    assert spectrum.slice_range(snd, s, 0.5, None) == pytest.approx((0.48, 0.52))
    assert spectrum.slice_range(snd, s, 0.0, None) == pytest.approx((0.0, 0.02))


def test_cpps_higher_for_periodic_than_noise():
    voiced = spectrum.cpps(make_vowel(duration=1.0), 0, 1)
    rng = np.random.default_rng(0)
    from phonolab.core.sound import Sound

    noise = spectrum.cpps(Sound(rng.normal(0, 0.1, 16000), 16000), 0, 1)
    assert voiced > noise + 5
