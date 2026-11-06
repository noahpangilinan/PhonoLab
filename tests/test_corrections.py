import numpy as np
import pytest

from phonolab.core import batch, praat_engine, voice
from phonolab.core.analysis import PitchResult, PitchSettings
from phonolab.core.batch import BatchOptions
from phonolab.core.corrections import Corrections
from phonolab.core.voice_types import VoicingResult
from tests.conftest import make_vowel


@pytest.fixture
def pitch():
    return PitchResult(np.array([0.1, 0.2, 0.3, 0.4]), np.array([100.0, 100.0, 100.0, 100.0]))


def test_octave_and_unvoice_change_only_their_stretch(pitch):
    c = Corrections().with_octave(0.15, 0.25, 2.0).with_unvoiced(0.35, 0.45)
    fixed = c.apply_pitch(pitch)
    assert fixed.frequencies[0] == 100 and fixed.frequencies[1] == 200
    assert np.isnan(fixed.frequencies[3])
    assert pitch.frequencies[1] == 100  # the analysis itself is untouched


def test_octave_edits_cancel(pitch):
    c = Corrections().with_octave(0, 1, 2.0).with_octave(0, 1, 0.5)
    assert c.apply_pitch(pitch).frequencies == pytest.approx(pitch.frequencies)


def test_pulses_can_be_removed_and_added():
    times = np.array([0.1, 0.2, 0.3])
    c = Corrections().with_pulses_removed(0.15, 0.25).with_pulse(0.5)
    assert c.apply_pulses(times).tolist() == [0.1, 0.3, 0.5]
    assert Corrections().with_unvoiced(0.25, 0.35).apply_pulses(times).tolist() == [0.1, 0.2]
    assert Corrections().with_pulse(0.2).with_pulses_removed(0.15, 0.25).added_pulses == ()


def test_unvoicing_cuts_voiced_stretches():
    voiced = VoicingResult(np.array([0.0, 1.0]), np.array([0.5, 2.0]))
    cut = Corrections().with_unvoiced(1.2, 1.4).apply_voicing(voiced)
    assert cut.starts.tolist() == [0.0, 1.0, 1.4] and cut.ends.tolist() == [0.5, 1.2, 2.0]


def test_restoring_a_range_keeps_the_rest():
    c = Corrections().with_unvoiced(0.1, 0.2).with_unvoiced(0.5, 0.6).with_pulse(0.15)
    kept = c.without_range(0.0, 0.3)
    assert kept.unvoiced == ((0.5, 0.6),) and kept.added_pulses == ()


def test_shifted_moves_everything():
    c = Corrections().with_unvoiced(1, 2).with_octave(1, 2, 2.0).with_pulses_removed(1, 2).with_pulse(1.5)
    s = c.shifted(-1)
    assert s.unvoiced == ((0, 1),) and s.octaves == ((0, 1, 2.0),) and s.added_pulses == (0.5,)


def test_save_and_load(tmp_path):
    c = Corrections().with_unvoiced(0.1, 0.2).with_octave(0.3, 0.4, 0.5).with_pulse(0.7)
    sound = tmp_path / "talk.wav"
    c.save(Corrections.path_for(sound))
    assert Corrections.path_for(sound).name == "talk.corrections.json"
    assert Corrections.load_for(sound) == c
    Corrections.path_for(sound).write_text("not json")
    assert Corrections.load_for(sound).is_empty  # a damaged file doesn't stop the sound opening
    assert Corrections.load_for(None).is_empty


@pytest.mark.parametrize("engine", ["praat7", "parselmouth"])
def test_voice_report_uses_corrections(engine, monkeypatch):
    if engine == "praat7" and not praat_engine.available():
        pytest.skip("run packaging/fetch_praat.py first")
    if engine == "parselmouth":
        monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    snd = make_vowel(f0=120, duration=1.0)
    args = (snd, PitchSettings(), voice.VoiceSettings(), 0.1, 0.9)
    plain = voice.voice_report(*args)
    fixed = voice.voice_report(*args, Corrections().with_unvoiced(0.3, 0.7).with_pulses_removed(0.2, 0.25))
    assert int(fixed.value("Number of pulses")) < int(plain.value("Number of pulses")) - 40
    doubled = voice.voice_report(*args, Corrections().with_octave(0.0, 1.0, 2.0))
    assert float(doubled.value("Median pitch").split()[0]) == pytest.approx(240.6, abs=4)


@pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
def test_period_range_adds_its_own_lines():
    snd = make_vowel(f0=120, duration=1.0)
    s = voice.VoiceSettings(period_floor=0.002, period_ceiling=0.012)
    report = voice.voice_report(snd, PitchSettings(), s, 0.1, 0.9)
    assert "With periods from 0.002 to 0.012 s:" in report.text


def test_batch_applies_saved_corrections(tmp_path):
    path = tmp_path / "v.wav"
    make_vowel(f0=120, duration=1.0).save(path)
    options = BatchOptions(measures=frozenset({"pitch"}))
    (plain,) = batch.measure_file(path, options)
    assert "corrected" not in plain
    Corrections().with_octave(0.0, 1.0, 2.0).save(Corrections.path_for(path))
    (row,) = batch.measure_file(path, options)
    assert row["corrected"] == "yes" and row["f0_median_hz"] == pytest.approx(2 * plain["f0_median_hz"])
