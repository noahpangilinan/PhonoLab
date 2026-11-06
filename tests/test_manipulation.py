import numpy as np
import pytest

from phonolab.core import manipulation as m
from phonolab.core.analysis import PitchSettings, compute_pitch
from phonolab.core.sound import Sound
from tests.conftest import make_vowel

SETTINGS = m.ManipulationSettings()


@pytest.fixture(scope="module")
def vowel():
    return make_vowel(f0=120, duration=1.0)


def median_f0(samples, sr):
    return np.nanmedian(compute_pitch(Sound(samples, sr), PitchSettings()).frequencies)


def test_analyse_gives_points_near_f0(vowel):
    tier = m.analyse(vowel, SETTINGS)
    assert len(tier) > 50
    assert np.median(tier.values) == pytest.approx(120, abs=2)


def test_resynthesis_follows_shifted_pitch(vowel):
    tier = m.analyse(vowel, SETTINGS)
    # A fifth rather than an octave: an exactly doubled, perfectly periodic synthetic source
    # makes the pitch tracker report the original period (an octave error), not PSOLA failing.
    shifted = m.shift_semitones(tier, 7, 0, vowel.duration)
    samples, sr = m.resynthesize(vowel, SETTINGS, shifted, m.Tier.empty())
    assert median_f0(samples, sr) == pytest.approx(120 * 2 ** (7 / 12), rel=0.02)


def test_unchanged_resynthesis_keeps_pitch_and_length(vowel):
    samples, sr = m.resynthesize(vowel, SETTINGS, m.analyse(vowel, SETTINGS), m.Tier.empty())
    assert len(samples) / sr == pytest.approx(vowel.duration, abs=0.01)
    assert median_f0(samples, sr) == pytest.approx(120, abs=2)


def test_duration_factor_lengthens(vowel):
    duration = m.set_duration_factor(m.Tier.empty(), 0.2, 0.6, 2.0)
    samples, sr = m.resynthesize(vowel, SETTINGS, m.analyse(vowel, SETTINGS), duration)
    assert len(samples) / sr == pytest.approx(1.4, abs=0.02)  # 0.4 s stretched to 0.8 s
    assert m.map_time(duration, 0.6, vowel.duration) == pytest.approx(1.0, abs=0.01)
    assert m.map_time(duration, 0.1, vowel.duration) == pytest.approx(0.1, abs=0.01)


def test_stylize_and_flatten(vowel):
    tier = m.analyse(vowel, SETTINGS)
    wavy = m.Tier(tier.times, tier.values * (1 + 0.1 * np.sin(tier.times * 20)))
    stylized = m.stylize(wavy, 2.0, vowel)
    assert 2 <= len(stylized) < len(wavy)
    flat = m.flatten(wavy, 0.2, 0.4)
    inside = (flat.times >= 0.2) & (flat.times <= 0.4)
    assert np.ptp(flat.values[inside]) == pytest.approx(0)
    assert not np.allclose(flat.values[~inside], flat.values[~inside].mean())


def test_tier_helpers():
    tier = m.Tier(np.array([0.1, 0.3]), np.array([100.0, 200.0]))
    assert tier.value_at(0.2) == pytest.approx(150)
    assert tier.value_at(0.0) == 100  # constant beyond the ends
    added = tier.with_point(0.2, 500.0)
    assert list(added.times) == [0.1, 0.2, 0.3]
    assert len(added.without_range(0.15, 0.25)) == 2
    assert tier == m.Tier(np.array([0.1, 0.3]), np.array([100.0, 200.0]))


def test_gain_changes_only_its_stretch():
    samples = np.ones(1000)
    gain = m.set_gain(m.Tier.empty(), 0.2, 0.4, 6.0)
    out = m.apply_gain(samples, 1000.0, gain, m.Tier.empty(), 1.0)
    assert out[300] == pytest.approx(10 ** (6 / 20)) and out[100] == pytest.approx(1) and out[600] == pytest.approx(1)


def test_gain_follows_duration_changes():
    duration = m.set_duration_factor(m.Tier.empty(), 0.0, 0.5, 2.0)  # the first half doubles
    gain = m.set_gain(m.Tier.empty(), 0.6, 0.8, -20.0)  # on the original timeline
    out = m.apply_gain(np.ones(1500), 1000.0, gain, duration, 1.0)
    assert out[1200] == pytest.approx(0.1) and out[700] == pytest.approx(1)


def test_resynthesis_applies_loudness(vowel):
    tier = m.analyse(vowel, SETTINGS)
    gain = m.set_gain(m.Tier.empty(), 0.2, 0.6, -12.0)
    quiet, sr = m.resynthesize(vowel, SETTINGS, tier, m.Tier.empty(), gain)
    loud, _ = m.resynthesize(vowel, SETTINGS, tier, m.Tier.empty())
    stretch = slice(int(0.3 * sr), int(0.5 * sr))
    assert np.abs(quiet[stretch]).max() == pytest.approx(np.abs(loud[stretch]).max() * 10 ** (-12 / 20), rel=0.01)
