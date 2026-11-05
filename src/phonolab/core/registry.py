"""Every analysis the editor can show: its settings class, compute function and dependencies."""

from __future__ import annotations

from phonolab.core import analysis, voice
from phonolab.core.sound import Sound

ANALYSES = {
    "spectrogram": (analysis.SpectrogramSettings, analysis.compute_spectrogram),
    "pitch": (analysis.PitchSettings, analysis.compute_pitch),
    "formants": (analysis.FormantSettings, analysis.compute_formants),
    "intensity": (analysis.IntensitySettings, analysis.compute_intensity),
    "pulses": (voice.VoiceSettings, voice.compute_pulses),
    "voicing": (voice.VoicingSettings, voice.compute_voicing),
}

# Analyses whose compute function also takes other analyses' settings, in this order.
DEPENDS = {"pulses": ("pitch",), "voicing": ("pitch",)}


def dependents(name: str) -> list[str]:
    return [other for other, deps in DEPENDS.items() if name in deps]


def compute_args(name: str, settings: dict) -> tuple:
    """Settings arguments for ``name``'s compute function: its own, then its dependencies'."""
    return (settings[name], *(settings[d] for d in DEPENDS.get(name, ())))


def compute(name: str, sound: Sound, settings: dict, *extra):
    _, fn = ANALYSES[name]
    return fn(sound, *compute_args(name, settings), *extra)
