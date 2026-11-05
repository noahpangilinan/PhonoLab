"""Glottal pulses and Praat's voice report (jitter, shimmer, harmonicity)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass

import numpy as np
from parselmouth.praat import call

from phonolab.core import praat_engine
from phonolab.core.analysis import PitchSettings, pitch_command, praat_pitch, setting
from phonolab.core.sound import Sound
from phonolab.core.textgrid import TextGrid

# Script text leaving the PointProcess selected; PITCH is replaced with the pitch command.
_PULSES = """p = PITCH
selectObject: s, p
To PointProcess (cc)"""


@dataclass(frozen=True)
class VoiceSettings:
    title = "Voice (pulses, jitter, shimmer)"
    max_period_factor: float = setting(1.3, "Maximum period factor", "", 1.0, 10.0)
    max_amplitude_factor: float = setting(1.6, "Maximum amplitude factor", "", 1.0, 10.0)


@dataclass(frozen=True)
class PulsesResult:
    times: np.ndarray


def compute_pulses(sound: Sound, _settings: VoiceSettings, pitch: PitchSettings) -> PulsesResult:
    """Glottal pulse times, as Praat's "To PointProcess (cc)" finds them."""
    if praat_engine.available():
        body = f"""{_PULSES}
if do("Get number of points") > 0
    To Matrix
    @export: "pulses"
endif"""
        matrices = praat_engine.analyse(sound, body.replace("PITCH", pitch_command(pitch)))[1]
        return PulsesResult(matrices["pulses"][1][0] if "pulses" in matrices else np.zeros(0))
    snd = sound.praat
    pulses = call([snd, praat_pitch(snd, pitch)], "To PointProcess (cc)")
    if call(pulses, "Get number of points") == 0:
        return PulsesResult(np.zeros(0))
    return PulsesResult(np.asarray(call(pulses, "To Matrix").values[0]))


@dataclass(frozen=True)
class VoicingSettings:
    title = "Voicing"
    max_period: float = setting(0.02, "Maximum period", "s", 0.001, 1.0, decimals=4)
    mean_period: float = setting(0.01, "Mean period", "s", 0.001, 1.0, decimals=4)


@dataclass(frozen=True)
class VoicingResult:
    """Voiced stretches; everything between them is unvoiced."""

    starts: np.ndarray
    ends: np.ndarray

    def voiced_at(self, t: float) -> bool:
        i = int(np.searchsorted(self.starts, t, side="right")) - 1
        return i >= 0 and t < self.ends[i]

    def voiced_fraction(self, start: float, end: float) -> float:
        start, end = sorted((start, end))
        if end <= start:
            return float("nan")
        overlap = np.clip(np.minimum(self.ends, end) - np.maximum(self.starts, start), 0, None)
        return float(overlap.sum() / (end - start))


def compute_voicing(sound: Sound, s: VoicingSettings, pitch: PitchSettings) -> VoicingResult:
    """Voiced/unvoiced decision from glottal pulses, as Praat's "PointProcess: To TextGrid (vuv)"."""
    if praat_engine.available():
        pulses = _PULSES.replace("PITCH", pitch_command(pitch))
        save = 'Save as text file: folder$ + "/voicing.TextGrid"'
        body = f"{pulses}\nTo TextGrid (vuv): {s.max_period}, {s.mean_period}\n{save}"
        _, folder = praat_engine.analyse_with_files(sound, body)
        try:
            intervals = TextGrid.read(folder / "voicing.TextGrid").tiers[0].intervals
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        voiced = [iv for iv in intervals if iv.text == "V"]
        return VoicingResult(np.array([iv.xmin for iv in voiced]), np.array([iv.xmax for iv in voiced]))
    snd = sound.praat
    pulses = call([snd, praat_pitch(snd, pitch)], "To PointProcess (cc)")
    grid = call(pulses, "To TextGrid (vuv)", s.max_period, s.mean_period)
    starts, ends = [], []
    for i in range(1, call(grid, "Get number of intervals", 1) + 1):
        if call(grid, "Get label of interval", 1, i) == "V":
            starts.append(call(grid, "Get start time of interval", 1, i))
            ends.append(call(grid, "Get end time of interval", 1, i))
    return VoicingResult(np.asarray(starts, dtype=float), np.asarray(ends, dtype=float))


@dataclass(frozen=True)
class VoiceReport:
    text: str  # exactly what Praat prints
    sections: dict[str, list[tuple[str, str]]]  # section -> [(measure, value)]

    def value(self, measure: str) -> str | None:
        for rows in self.sections.values():
            for name, value in rows:
                if name == measure:
                    return value
        return None


_ROW = re.compile(r"^\s+([^:]+):\s*(.*)$")


def parse_report(text: str) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    current = "General"
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.strip().rstrip(":")
            continue
        if m := _ROW.match(line):
            sections.setdefault(current, []).append((m.group(1).strip(), m.group(2).strip()))
    return sections


def voice_report(sound: Sound, pitch: PitchSettings, voice: VoiceSettings, start: float, end: float) -> VoiceReport:
    """Praat's "Voice report" for [start, end], analysed with a margin like Praat's editor does."""
    start, end = sorted((start, end))
    margin = 3.0 / pitch.floor  # enough context for the pitch analysis at the edges
    from_time, to_time = max(0.0, start - margin), min(sound.duration, end + margin)
    if praat_engine.available():
        arguments = (
            f"{start}, {end}, {pitch.floor}, {pitch.ceiling}, {voice.max_period_factor}, "
            f"{voice.max_amplitude_factor}, {pitch.silence_threshold}, {pitch.voicing_threshold}"
        )
        body = f"""part = Extract part: {from_time}, {to_time}, "rectangular", 1, "yes"
p = {pitch_command(pitch)}
selectObject: part, p
pp = To PointProcess (cc)
selectObject: part, p, pp
report$ = Voice report: {arguments}
writeInfoLine: report$"""
        text = praat_engine.analyse(sound, body)[0]
        return VoiceReport(text, parse_report(text))
    snd = sound.praat.extract_part(from_time=from_time, to_time=to_time, preserve_times=True)
    pitch_obj = praat_pitch(snd, pitch)
    pulses = call([snd, pitch_obj], "To PointProcess (cc)")
    text = call(
        [snd, pitch_obj, pulses], "Voice report", start, end, pitch.floor, pitch.ceiling,
        voice.max_period_factor, voice.max_amplitude_factor, pitch.silence_threshold, pitch.voicing_threshold,
    )  # fmt: skip
    return VoiceReport(text, parse_report(text))
