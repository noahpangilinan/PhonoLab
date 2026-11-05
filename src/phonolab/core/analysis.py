"""Acoustic analyses backed by Praat (via parselmouth).

Each analysis has a frozen settings dataclass (defaults match Praat's editor
defaults) and a ``compute_*`` function returning plain numpy data so the UI and
tests never need to touch parselmouth objects directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum

import numpy as np
import parselmouth
from parselmouth.praat import call

from phonolab.core.sound import Sound


def setting(default, label: str, unit: str = "", minimum=None, maximum=None, **extra):
    """Dataclass field carrying UI metadata for the generic settings dialog."""
    meta = {"label": label, "unit": unit, "min": minimum, "max": maximum, **extra}
    return field(default=default, metadata=meta)


def settings_to_dict(settings) -> dict:
    return {f.name: (v.value if isinstance(v := getattr(settings, f.name), Enum) else v) for f in fields(settings)}


def settings_from_dict(cls, data: dict):
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        default = f.default
        try:
            if isinstance(default, Enum):
                value = type(default)(value)
            elif isinstance(default, bool):
                value = value in (True, "true", "True", 1, "1")
            else:
                value = type(default)(value)
        except (TypeError, ValueError):
            continue
        if "choices" in f.metadata and value not in f.metadata["choices"]:
            continue
        kwargs[f.name] = value
    return cls(**kwargs)


# --------------------------------------------------------------------------- spectrogram


@dataclass(frozen=True)
class SpectrogramSettings:
    title = "Spectrogram"
    view_range: float = setting(5000.0, "Maximum frequency", "Hz", 100.0, 50000.0)
    window_length: float = setting(0.005, "Window length", "s", 0.0005, 1.0, decimals=4)
    dynamic_range: float = setting(50.0, "Dynamic range", "dB", 10.0, 120.0)
    time_steps: int = setting(1000, "Number of time steps", "", 50, 5000)
    frequency_steps: int = setting(250, "Number of frequency steps", "", 20, 1000)
    colormap: str = setting(
        "Grey (Praat)", "Colour map", choices=("Grey (Praat)", "Blues", "Viridis", "Magma", "Inferno")
    )


@dataclass(frozen=True)
class SpectrogramResult:
    times: np.ndarray  # frame centres (s)
    frequencies: np.ndarray  # bin centres (Hz)
    db: np.ndarray  # (n_freq, n_time), dB re 2e-5 Pa
    max_db: float


def compute_spectrogram(
    sound: Sound, s: SpectrogramSettings, start: float = 0.0, end: float | None = None
) -> SpectrogramResult:
    """Spectrogram of ``[start, end]`` at roughly ``s.time_steps`` frames."""
    end = sound.duration if end is None else min(end, sound.duration)
    start = max(0.0, start)
    # Pad by one window so frames reach the edges of the requested range.
    pad = s.window_length
    snd = sound.praat
    if start > 0 or end < sound.duration:
        snd = snd.extract_part(
            from_time=max(0.0, start - pad),
            to_time=min(sound.duration, end + pad),
            preserve_times=True,
        )
    nyquist = sound.sampling_rate / 2
    max_freq = min(s.view_range, nyquist)
    # Like Praat's editor: derive step sizes from the requested resolution, but
    # never finer than what the window supports.
    time_step = max((end - start) / s.time_steps, s.window_length / 8)
    freq_step = max(max_freq / s.frequency_steps, 1.0 / (s.window_length * 8))
    spec = snd.to_spectrogram(
        window_length=s.window_length,
        maximum_frequency=max_freq,
        time_step=time_step,
        frequency_step=freq_step,
    )
    power = np.asarray(spec.values)
    db = 10.0 * np.log10(np.maximum(power, 1e-30) / 4e-10)
    return SpectrogramResult(np.asarray(spec.xs()), np.asarray(spec.ys()), db, float(db.max()))


# --------------------------------------------------------------------------- pitch


class PitchMethod(Enum):
    AUTOCORRELATION = "autocorrelation"
    CROSS_CORRELATION = "cross-correlation"
    SUBHARMONIC_SUMMATION = "subharmonic summation (SHS)"


@dataclass(frozen=True)
class PitchSettings:
    title = "Pitch"
    floor: float = setting(75.0, "Pitch floor", "Hz", 10.0, 1000.0)
    ceiling: float = setting(500.0, "Pitch ceiling", "Hz", 50.0, 3000.0)
    method: PitchMethod = setting(PitchMethod.AUTOCORRELATION, "Method")
    very_accurate: bool = setting(False, "Very accurate")
    max_candidates: int = setting(15, "Max. number of candidates", "", 2, 50)
    silence_threshold: float = setting(0.03, "Silence threshold", "", 0.0, 1.0, decimals=3)
    voicing_threshold: float = setting(0.45, "Voicing threshold", "", 0.0, 1.0, decimals=3)
    octave_cost: float = setting(0.01, "Octave cost", "", 0.0, 1.0, decimals=3)
    octave_jump_cost: float = setting(0.35, "Octave-jump cost", "", 0.0, 1.0, decimals=3)
    voiced_unvoiced_cost: float = setting(0.14, "Voiced/unvoiced cost", "", 0.0, 1.0, decimals=3)


@dataclass(frozen=True)
class PitchResult:
    times: np.ndarray
    frequencies: np.ndarray  # Hz; NaN where unvoiced
    strengths: np.ndarray


def praat_pitch(snd: parselmouth.Sound, s: PitchSettings) -> parselmouth.Pitch:
    """A Praat Pitch object for ``snd`` with these settings."""
    if s.method is PitchMethod.SUBHARMONIC_SUMMATION:
        # Praat's defaults for the SHS-specific parameters (Hermes 1988).
        max_frequency_component, max_subharmonics, compression, points_per_octave = 1250.0, 15, 0.84, 48
        return call(
            snd, "To Pitch (shs)", 0.01, s.floor, s.max_candidates, max_frequency_component,
            max_subharmonics, compression, s.ceiling, points_per_octave,
        )  # fmt: skip
    method = snd.to_pitch_ac if s.method is PitchMethod.AUTOCORRELATION else snd.to_pitch_cc
    return method(
        pitch_floor=s.floor,
        pitch_ceiling=s.ceiling,
        max_number_of_candidates=s.max_candidates,
        very_accurate=s.very_accurate,
        silence_threshold=s.silence_threshold,
        voicing_threshold=s.voicing_threshold,
        octave_cost=s.octave_cost,
        octave_jump_cost=s.octave_jump_cost,
        voiced_unvoiced_cost=s.voiced_unvoiced_cost,
    )


def compute_pitch(sound: Sound, s: PitchSettings) -> PitchResult:
    pitch = praat_pitch(sound.praat, s)
    sel = pitch.selected_array
    freqs = sel["frequency"].astype(float)
    freqs[freqs == 0] = np.nan
    return PitchResult(np.asarray(pitch.xs()), freqs, sel["strength"].astype(float))


# --------------------------------------------------------------------------- formants


class FormantMethod(Enum):
    BURG = "Burg"
    ROBUST = "robust (iterative LPC)"


@dataclass(frozen=True)
class FormantSettings:
    title = "Formants"
    method: FormantMethod = setting(FormantMethod.BURG, "Method")
    max_formant: float = setting(5500.0, "Formant ceiling", "Hz", 1000.0, 20000.0)
    n_formants: float = setting(5.0, "Number of formants", "", 1.0, 7.0, decimals=1)
    window_length: float = setting(0.025, "Window length", "s", 0.001, 1.0, decimals=4)
    pre_emphasis_from: float = setting(50.0, "Pre-emphasis from", "Hz", 1.0, 10000.0)
    dynamic_range: float = setting(30.0, "Dot dynamic range", "dB", 1.0, 120.0)


@dataclass(frozen=True)
class FormantResult:
    times: np.ndarray
    frequencies: np.ndarray  # (n_formants, n_frames) Hz; NaN where undefined
    intensity_db: np.ndarray  # per-frame intensity, used to hide dots in silence


def praat_formant(snd: parselmouth.Sound, s: FormantSettings) -> parselmouth.Formant:
    """A Praat Formant object for ``snd`` with these settings."""
    if s.method is FormantMethod.ROBUST:
        n_sigma, iterations, tolerance = 1.5, 5, 1e-6  # Praat's defaults
        return call(
            snd, "To Formant (robust)", 0.0, s.n_formants, s.max_formant, s.window_length,
            s.pre_emphasis_from, n_sigma, iterations, tolerance,
        )  # fmt: skip
    return snd.to_formant_burg(
        max_number_of_formants=s.n_formants,
        maximum_formant=s.max_formant,
        window_length=s.window_length,
        pre_emphasis_from=s.pre_emphasis_from,
    )


def compute_formants(sound: Sound, s: FormantSettings) -> FormantResult:
    formant = praat_formant(sound.praat, s)
    times = np.asarray(formant.xs())
    n = int(np.ceil(s.n_formants))
    freqs = np.vstack([call(formant, "To Matrix", i + 1).values[0] for i in range(n)])
    freqs[freqs <= 0] = np.nan
    # Frame intensity for Praat-style dot suppression in quiet regions.
    intensity = sound.praat.to_intensity(minimum_pitch=100.0, subtract_mean=False)
    frame_db = np.interp(times, intensity.xs(), intensity.values[0])
    return FormantResult(times, freqs, frame_db)


# --------------------------------------------------------------------------- intensity


@dataclass(frozen=True)
class IntensitySettings:
    title = "Intensity"
    minimum_pitch: float = setting(100.0, "Minimum pitch", "Hz", 10.0, 1000.0)
    subtract_mean: bool = setting(True, "Subtract mean pressure")
    view_min: float = setting(50.0, "View range minimum", "dB", -100.0, 200.0)
    view_max: float = setting(100.0, "View range maximum", "dB", -100.0, 200.0)


@dataclass(frozen=True)
class IntensityResult:
    times: np.ndarray
    db: np.ndarray


def compute_intensity(sound: Sound, s: IntensitySettings) -> IntensityResult:
    # Praat needs at least 6.4 / minimum_pitch seconds of signal.
    if sound.duration < 6.4 / s.minimum_pitch:
        return IntensityResult(np.array([]), np.array([]))
    intensity = sound.praat.to_intensity(minimum_pitch=s.minimum_pitch, subtract_mean=s.subtract_mean)
    return IntensityResult(np.asarray(intensity.xs()), np.asarray(intensity.values[0]))
