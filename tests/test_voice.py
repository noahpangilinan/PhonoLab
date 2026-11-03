import numpy as np
import pytest

from phonolab.core import registry
from phonolab.core.analysis import PitchSettings
from phonolab.core.voice import VoiceSettings, compute_pulses, parse_report, voice_report
from tests.conftest import make_vowel


def test_pulses_follow_f0():
    snd = make_vowel(f0=120, duration=1.0)
    times = compute_pulses(snd, VoiceSettings(), PitchSettings()).times
    assert len(times) == pytest.approx(120, abs=3)
    assert np.median(np.diff(times)) == pytest.approx(1 / 120, rel=0.02)


def test_pulses_registered_with_pitch_dependency():
    snd = make_vowel(duration=0.5)
    settings = {"pulses": VoiceSettings(), "pitch": PitchSettings()}
    assert len(registry.compute("pulses", snd, settings).times) > 10
    assert "pulses" in registry.dependents("pitch")


def test_voice_report_of_steady_vowel():
    snd = make_vowel(f0=150, duration=1.0)
    report = voice_report(snd, PitchSettings(), VoiceSettings(), 0.1, 0.9)
    assert "Jitter (local)" in report.text
    assert float(report.value("Median pitch").split()[0]) == pytest.approx(150, abs=2)
    jitter = float(report.value("Jitter (local)").rstrip("%"))
    assert jitter < 0.1  # a synthetic pulse train is nearly perfectly periodic
    assert {"Pitch", "Pulses", "Jitter", "Shimmer"} <= set(report.sections)


def test_parse_report_sections():
    text = "   From 0 to 1 seconds\nPitch:\n   Median pitch: 100 Hz\nJitter:\n   Jitter (local): 1.2%\n"
    sections = parse_report(text)
    assert sections["Pitch"] == [("Median pitch", "100 Hz")]
    assert sections["Jitter"] == [("Jitter (local)", "1.2%")]
