import numpy as np
import pytest

from phonolab.core import analysis, queries
from phonolab.core.analysis import (
    FormantSettings,
    IntensitySettings,
    PitchMethod,
    PitchSettings,
    SpectrogramSettings,
)
from tests.conftest import make_sine, make_vowel


# SHS is tested separately: it needs natural spectral tilt, which this flat-spectrum pulse vowel lacks.
@pytest.mark.parametrize("method", [PitchMethod.AUTOCORRELATION, PitchMethod.CROSS_CORRELATION])
def test_pitch_of_vowel(method):
    snd = make_vowel(f0=120)
    r = analysis.compute_pitch(snd, PitchSettings(method=method))
    assert np.nanmedian(r.frequencies) == pytest.approx(120, abs=2)


def test_pitch_of_silence_is_undefined():
    snd = make_sine(amplitude=0.0)
    r = analysis.compute_pitch(snd, PitchSettings())
    assert np.all(np.isnan(r.frequencies))


def test_formants_of_vowel():
    snd = make_vowel(formants=(700, 1220, 2600))
    r = analysis.compute_formants(snd, FormantSettings())
    f1, f2 = np.nanmedian(r.frequencies[0]), np.nanmedian(r.frequencies[1])
    assert f1 == pytest.approx(700, rel=0.1)
    assert f2 == pytest.approx(1220, rel=0.1)


def test_intensity_of_sine():
    # A sine of amplitude A Pa has RMS A/sqrt(2); dB SPL = 20 log10(rms / 2e-5).
    snd = make_sine(amplitude=0.2)
    r = analysis.compute_intensity(snd, IntensitySettings())
    expected = 20 * np.log10(0.2 / np.sqrt(2) / 2e-5)
    assert np.median(r.db) == pytest.approx(expected, abs=0.5)


def test_intensity_too_short_is_empty():
    snd = make_sine(duration=0.01)
    assert analysis.compute_intensity(snd, IntensitySettings()).times.size == 0


def test_spectrogram_peak_at_sine_frequency():
    snd = make_sine(freq=1000)
    r = analysis.compute_spectrogram(snd, SpectrogramSettings())
    peak_bin = r.db[:, r.db.shape[1] // 2].argmax()
    assert r.frequencies[peak_bin] == pytest.approx(1000, abs=60)


def test_spectrogram_window_covers_requested_range():
    snd = make_sine(duration=2.0)
    r = analysis.compute_spectrogram(snd, SpectrogramSettings(), 0.5, 0.8)
    assert r.times[0] <= 0.505 and r.times[-1] >= 0.795
    assert r.times[-1] < 1.0


def test_queries_over_selection():
    snd = make_vowel(f0=150)
    p = analysis.compute_pitch(snd, PitchSettings())
    stats = queries.pitch_stats(p, 0.1, 0.5)
    assert stats.mean == pytest.approx(150, abs=2)
    assert stats.n_frames > 10
    assert queries.pitch_at(p, 0.3) == pytest.approx(150, abs=2)
    assert np.isnan(queries.pitch_at(p, 10.0))


def test_value_at_interpolates_and_respects_gaps():
    times = np.array([0.0, 1.0, 2.0, 3.0])
    values = np.array([10.0, 20.0, np.nan, 40.0])
    assert queries.value_at(times, values, 0.5) == pytest.approx(15)
    assert queries.value_at(times, values, 1.2) == 20  # nearest frame voiced
    assert np.isnan(queries.value_at(times, values, 1.8))  # nearest frame unvoiced


def test_settings_roundtrip_through_dict():
    s = PitchSettings(floor=60, method=PitchMethod.CROSS_CORRELATION, very_accurate=True)
    d = analysis.settings_to_dict(s)
    assert analysis.settings_from_dict(PitchSettings, d) == s
    # Garbage values fall back to defaults instead of crashing.
    bad = {"floor": "abc", "method": "nope"}
    assert analysis.settings_from_dict(PitchSettings, bad) == PitchSettings()
    bad_map = {"colormap": "bogus"}
    assert analysis.settings_from_dict(SpectrogramSettings, bad_map) == SpectrogramSettings()


def test_range_stats_report_extremes_and_times():
    times = np.array([0.0, 0.1, 0.2, 0.3])
    values = np.array([100.0, np.nan, 300.0, 200.0])
    st = queries.RangeStats.of(values, times)
    assert (st.minimum, st.time_of_minimum) == (100.0, 0.0)
    assert (st.maximum, st.time_of_maximum) == (300.0, 0.2)
    assert st.median == 200.0 and st.n_frames == 3


def test_pitch_slope_and_semitones():
    times = np.array([0.0, 0.01, 0.02, 0.03])
    p = analysis.PitchResult(times, np.array([100.0, 101.0, np.nan, 103.0]), np.ones(4))
    assert queries.pitch_mean_abs_slope(p, 0, 1) == pytest.approx(100.0)  # only the voiced pair counts
    assert queries.semitones(200.0) == pytest.approx(12.0)
    assert np.isnan(queries.semitones(float("nan")))


def test_formant_bandwidths_at_cursor():
    snd = make_vowel(formants=(700, 1220, 2600), duration=0.6)
    bws = queries.formant_bandwidths_at(snd, FormantSettings(), 0.3)
    assert len(bws) == 5 and 0 < bws[0] < 400


def test_shs_pitch_on_harmonic_complex():
    from phonolab.core.sound import Sound

    sr = 16000
    t = np.arange(sr) / sr
    x = 0.1 * sum(np.sin(2 * np.pi * 120 * k * t) / k for k in range(1, 30))
    r = analysis.compute_pitch(Sound(x, sr), PitchSettings(method=PitchMethod.SUBHARMONIC_SUMMATION))
    assert np.nanmedian(r.frequencies) == pytest.approx(120, rel=0.02)


def test_robust_formants_agree_with_burg():
    snd = make_vowel(formants=(700, 1220, 2600), duration=0.6)
    robust = analysis.compute_formants(snd, FormantSettings(method=analysis.FormantMethod.ROBUST))
    assert np.nanmedian(robust.frequencies[0]) == pytest.approx(700, rel=0.1)
    assert np.nanmedian(robust.frequencies[1]) == pytest.approx(1220, rel=0.1)
