import numpy as np
import pytest

from phonolab.core import analysis, praat_engine, spectrum, voice
from phonolab.core.analysis import FormantSettings, IntensitySettings, PitchMethod, PitchSettings
from tests.conftest import make_vowel

needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")


@pytest.fixture
def vowel():
    return make_vowel(f0=120, duration=1.0)


def test_env_can_disable_the_engine(monkeypatch):
    monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    assert not praat_engine.available()
    assert praat_engine.version() is None
    assert "Parselmouth" in praat_engine.engine_description()
    with pytest.raises(praat_engine.PraatEngineError):
        praat_engine.run_script('writeInfoLine: "x"')


def test_read_matrix_handles_undefined_cells(tmp_path):
    path = tmp_path / "m.Matrix"
    path.write_text(
        'File type = "ooTextFile"\nObject class = "Matrix 2"\n\n0\n1\n3\n0.1\n0.2\n1\n1\n1\n1\n1\n'
        "10\n--undefined--\n30\n"
    )
    x, values = praat_engine.read_matrix(path)
    assert x == pytest.approx([0.2, 0.3, 0.4])
    assert values[0][0] == 10 and np.isnan(values[0][1]) and values[0][2] == 30


def test_missing_program_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("PHONOLAB_PRAAT", str(tmp_path / "nope.exe"))
    with pytest.raises(praat_engine.PraatEngineError, match="Could not start Praat"):
        praat_engine.run_script('writeInfoLine: "x"')


@needs_praat
def test_version_matches_the_pinned_build():
    assert praat_engine.version() == praat_engine.PRAAT_VERSION


@needs_praat
def test_script_errors_become_exceptions():
    with pytest.raises(praat_engine.PraatEngineError, match="not available"):
        praat_engine.run_script("No such command: 1\n")


@needs_praat
def test_samples_reach_praat_exactly(vowel):
    output, _ = praat_engine.analyse(vowel, 'peak = Get maximum: 0, 0, "None"\nwriteInfoLine: peak')
    assert float(output) == vowel.mono.max()


def both_engines(monkeypatch, fn):
    """Run ``fn`` on Praat 7, then on Parselmouth's Praat."""
    new = fn()
    monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    return new, fn()


@needs_praat
@pytest.mark.parametrize("method", list(PitchMethod))
def test_pitch_agrees_across_engines(vowel, monkeypatch, method):
    s = PitchSettings(method=method)
    new, old = both_engines(monkeypatch, lambda: analysis.compute_pitch(vowel, s))
    assert new.times == pytest.approx(old.times)
    assert np.nanmedian(new.frequencies) == pytest.approx(np.nanmedian(old.frequencies), rel=1e-3)


@needs_praat
@pytest.mark.parametrize("method", list(analysis.FormantMethod))
def test_formants_agree_across_engines(vowel, monkeypatch, method):
    s = FormantSettings(method=method)
    new, old = both_engines(monkeypatch, lambda: analysis.compute_formants(vowel, s))
    assert new.frequencies.shape == old.frequencies.shape
    # Robust analysis really did change between versions (about 3 % on this vowel).
    tolerance = 0.05 if method is analysis.FormantMethod.ROBUST else 0.01
    assert np.nanmedian(new.frequencies[0]) == pytest.approx(np.nanmedian(old.frequencies[0]), rel=tolerance)


@needs_praat
def test_intensity_pulses_and_voicing_agree_across_engines(vowel, monkeypatch):
    p = PitchSettings()

    def measure():
        return (
            analysis.compute_intensity(vowel, IntensitySettings()),
            voice.compute_pulses(vowel, voice.VoiceSettings(), p),
            voice.compute_voicing(vowel, voice.VoicingSettings(), p),
        )

    (i7, p7, v7), (i6, p6, v6) = both_engines(monkeypatch, measure)
    assert i7.db == pytest.approx(i6.db, abs=1e-3)  # energy integration was refined in Praat 6.4.32
    assert p7.times == pytest.approx(p6.times, abs=1e-4)
    assert v7.starts == pytest.approx(v6.starts, abs=1e-3)


@needs_praat
def test_voice_report_has_praat_7_measures(vowel, monkeypatch):
    report = voice.voice_report(vowel, PitchSettings(), voice.VoiceSettings(), 0.1, 0.9)
    assert "H1-minus-H2" in report.text  # added in Praat 6.4.33
    monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    assert "H1-minus-H2" not in voice.voice_report(vowel, PitchSettings(), voice.VoiceSettings(), 0.1, 0.9).text


@needs_praat
def test_cpps_runs_on_praat_7(vowel):
    assert spectrum.cpps(vowel, 0.1, 0.9) > 10


@needs_praat
def test_pulses_of_silence_are_empty():
    from tests.conftest import make_sine

    assert len(voice.compute_pulses(make_sine(amplitude=0.0), voice.VoiceSettings(), PitchSettings()).times) == 0


@needs_praat
def test_engine_self_check_and_praat_7_scripts(vowel, capsys):
    from phonolab.app import engine_info
    from phonolab.core import scripting

    assert engine_info() == 0
    assert "script result: 42" in capsys.readouterr().out
    # Commands newer than Parselmouth's Praat work in the script window.
    r = scripting.run_praat(
        vowel, None, 'To Pitch (filtered ac): 0, 50, 800, 15, "no", 0.03, 0.09, 0.5, 0.055, 0.35, 0.14\n'
    )
    assert r.error is None
