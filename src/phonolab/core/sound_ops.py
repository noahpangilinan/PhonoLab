"""Operations that make a new Sound from an existing one (Praat's "Modify"/"Filter"/"Convert").

Each multi-channel operation is applied per channel with Praat, so stereo stays stereo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import parselmouth
from parselmouth.praat import call

from phonolab.core.analysis import setting
from phonolab.core.sound import Sound


def _per_channel(sound: Sound, fn) -> tuple[np.ndarray, float]:
    """Apply ``fn(parselmouth.Sound) -> parselmouth.Sound`` to each channel; stack the results."""
    out = []
    for c in range(sound.n_channels):
        snd = parselmouth.Sound(sound.samples[:, c], sampling_frequency=sound.sampling_rate)
        out.append(fn(snd))
    sr = out[0].sampling_frequency
    n = min(len(s.values[0]) for s in out)
    return np.column_stack([s.values[0][:n] for s in out]), sr


def derived(sound: Sound, samples: np.ndarray, sampling_rate: float, suffix: str) -> Sound:
    return Sound(samples, sampling_rate, title=f"{sound.name}_{suffix}")


# --------------------------------------------------------------------------- settings dataclasses


@dataclass(frozen=True)
class ResampleSettings:
    title = "Resample"
    sampling_rate: float = setting(16000.0, "New sampling frequency", "Hz", 1000.0, 192000.0, decimals=1)
    precision: int = setting(50, "Precision (samples)", "", 1, 1000)


@dataclass(frozen=True)
class BandSettings:
    title = "Filter"
    low: float = setting(80.0, "From frequency", "Hz", 0.0, 100000.0)
    high: float = setting(8000.0, "To frequency", "Hz", 0.0, 100000.0)
    smoothing: float = setting(100.0, "Smoothing", "Hz", 0.0, 10000.0)


@dataclass(frozen=True)
class PreEmphasisSettings:
    title = "Pre-emphasis"
    from_frequency: float = setting(50.0, "From frequency", "Hz", 1.0, 10000.0)


@dataclass(frozen=True)
class ScalePeakSettings:
    title = "Scale peak"
    peak: float = setting(0.99, "New absolute peak", "", 0.01, 1.0)


class Waveform(Enum):
    SINE = "sine"
    SQUARE = "square"
    PULSE_TRAIN = "pulse train"
    WHITE_NOISE = "white noise"
    PINK_NOISE = "pink noise"


@dataclass(frozen=True)
class ToneSettings:
    title = "New sound"
    waveform: Waveform = setting(Waveform.SINE, "Waveform")
    frequency: float = setting(440.0, "Frequency", "Hz", 1.0, 20000.0)
    amplitude: float = setting(0.5, "Amplitude", "", 0.0, 1.0)
    duration: float = setting(1.0, "Duration", "s", 0.01, 3600.0, decimals=3)
    sampling_rate: float = setting(44100.0, "Sampling frequency", "Hz", 1000.0, 192000.0, decimals=1)


# --------------------------------------------------------------------------- operations


def extract(sound: Sound, start: float, end: float) -> Sound:
    part = sound.extract(start, end)
    return derived(sound, part.samples, sound.sampling_rate, "part")


def to_mono(sound: Sound) -> Sound:
    return derived(sound, sound.mono.copy(), sound.sampling_rate, "mono")


def resample(sound: Sound, s: ResampleSettings) -> Sound:
    samples, sr = _per_channel(sound, lambda snd: call(snd, "Resample", s.sampling_rate, s.precision))
    return derived(sound, samples, sr, f"{s.sampling_rate / 1000:g}k")


def pass_band(sound: Sound, s: BandSettings) -> Sound:
    samples, sr = _per_channel(sound, lambda snd: call(snd, "Filter (pass Hann band)", s.low, s.high, s.smoothing))
    return derived(sound, samples, sr, "band")


def stop_band(sound: Sound, s: BandSettings) -> Sound:
    samples, sr = _per_channel(sound, lambda snd: call(snd, "Filter (stop Hann band)", s.low, s.high, s.smoothing))
    return derived(sound, samples, sr, "stop")


def pre_emphasis(sound: Sound, s: PreEmphasisSettings) -> Sound:
    samples, sr = _per_channel(sound, lambda snd: call(snd, "Filter (pre-emphasis)", s.from_frequency))
    return derived(sound, samples, sr, "preemph")


def scale_peak(sound: Sound, s: ScalePeakSettings) -> Sound:
    peak = float(np.max(np.abs(sound.samples))) or 1.0
    return derived(sound, sound.samples * (s.peak / peak), sound.sampling_rate, "scaled")


def reverse(sound: Sound) -> Sound:
    return derived(sound, sound.samples[::-1].copy(), sound.sampling_rate, "reversed")


def concatenate(sounds: list[Sound]) -> Sound:
    """Join sounds end to end. They must share a sampling rate; channel counts are matched up."""
    if not sounds:
        raise ValueError("Nothing to concatenate")
    sr = sounds[0].sampling_rate
    if any(s.sampling_rate != sr for s in sounds):
        raise ValueError("All sounds must have the same sampling frequency (resample them first)")
    channels = max(s.n_channels for s in sounds)
    parts = [s.samples if s.n_channels == channels else np.repeat(s.mono[:, None], channels, axis=1) for s in sounds]
    return Sound(np.concatenate(parts), sr, title="concatenated")


def generate(s: ToneSettings) -> Sound:
    n = int(round(s.duration * s.sampling_rate))
    t = np.arange(n) / s.sampling_rate
    rng = np.random.default_rng()
    if s.waveform is Waveform.SINE:
        x = np.sin(2 * np.pi * s.frequency * t)
    elif s.waveform is Waveform.SQUARE:
        x = np.sign(np.sin(2 * np.pi * s.frequency * t))
    elif s.waveform is Waveform.PULSE_TRAIN:
        x = np.zeros(n)
        idx = np.round(np.arange(0, s.duration, 1 / s.frequency) * s.sampling_rate).astype(int)
        x[idx[idx < n]] = 1.0
    elif s.waveform is Waveform.WHITE_NOISE:
        x = rng.uniform(-1, 1, n)
    else:  # pink noise: shape white noise by 1/sqrt(f) in the frequency domain
        spectrum = np.fft.rfft(rng.normal(size=n))
        f = np.fft.rfftfreq(n, 1 / s.sampling_rate)
        spectrum[1:] /= np.sqrt(f[1:])
        spectrum[0] = 0
        x = np.fft.irfft(spectrum, n)
        x /= np.max(np.abs(x)) or 1.0
    name = s.waveform.value.replace(" ", "_")
    periodic = s.waveform in (Waveform.SINE, Waveform.SQUARE, Waveform.PULSE_TRAIN)
    title = f"{name}_{s.frequency:g}Hz" if periodic else name
    return Sound(s.amplitude * x, s.sampling_rate, title=title)
