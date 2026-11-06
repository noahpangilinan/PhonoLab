import numpy as np
import pytest

from phonolab.core import analysis, praat_engine, spectrum, views
from phonolab.core.analysis import FormantSettings
from tests.conftest import make_vowel

needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")


@pytest.fixture
def vowel():
    return make_vowel(f0=120, formants=(700, 1220, 2600), duration=1.0)


@needs_praat
@pytest.mark.parametrize("name", list(views.VIEWS))
def test_views_have_the_right_shape_and_place(vowel, name):
    r = views.compute_view(vowel, name, 0.2, 0.8)
    assert r.values.shape == (len(r.ys), len(r.times)) and len(r.times) > 5
    assert r.times[0] >= 0.2 and r.times[-1] <= 0.8  # on the whole sound's time axis
    assert np.isfinite(r.values).all()


@needs_praat
def test_cepstrogram_peak_is_at_the_pitch_period(vowel):
    r = views.compute_view(vowel, "cepstrogram", 0.2, 0.8)
    profile = r.values.mean(axis=1)
    search = (r.ys > 0.003) & (r.ys < 0.02)
    assert r.ys[search][np.argmax(profile[search])] == pytest.approx(1 / 120, rel=0.05)


def test_views_need_praat_and_a_short_stretch(vowel, monkeypatch):
    with pytest.raises(ValueError):
        views.compute_view(vowel, "mfcc", 0.0, 100.0)
    monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    with pytest.raises(ValueError, match="bundled Praat 7"):
        views.compute_view(vowel, "mfcc", 0.1, 0.5)


@needs_praat
def test_lpc_spectrum_peaks_near_the_formants(vowel):
    r = spectrum.compute_lpc(vowel, spectrum.SpectrumSettings(), 0.4, 0.6)
    low = (r.frequencies > 400) & (r.frequencies < 1000)
    assert r.frequencies[low][np.argmax(r.db[low])] == pytest.approx(700, rel=0.15)
    assert r.frequencies.max() <= 5000 and np.isnan(r.centre_of_gravity)


@needs_praat
def test_excitation_runs_along_bark(vowel):
    r = spectrum.compute_excitation(vowel, spectrum.SpectrumSettings(), 0.4, 0.6)
    assert r.frequencies.max() == pytest.approx(25.6, abs=0.2) and len(r.db) == 256


def test_formant_tracking_gives_three_continuous_tracks(vowel):
    r = analysis.compute_formants(vowel, FormantSettings(track=True))
    assert r.frequencies.shape[0] == 3
    assert np.nanmedian(r.frequencies[0]) == pytest.approx(700, rel=0.15)
    assert np.isnan(r.frequencies).mean() < 0.1
