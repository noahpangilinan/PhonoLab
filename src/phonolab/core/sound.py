"""Sound document: audio samples plus the parselmouth object used for analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from itertools import count
from pathlib import Path

import numpy as np
import parselmouth
import soundfile as sf

SUPPORTED_EXTENSIONS = (
    ".wav", ".flac", ".aiff", ".aif", ".ogg", ".opus", ".mp3", ".m4a", ".aac", ".mp4", ".wma", ".webm",
)  # fmt: skip

_ids = count(1)


class SoundLoadError(Exception):
    pass


def _read_soundfile(path: Path) -> tuple[np.ndarray, float]:
    samples, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return samples, sr


def _read_ffmpeg(path: Path) -> tuple[np.ndarray, float]:
    import av  # imported lazily: loading FFmpeg is only needed for compressed formats

    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise SoundLoadError("no audio stream")
        stream = container.streams.audio[0]
        # Planar float keeps each channel in its own row, at the stream's native rate.
        resampler = av.AudioResampler(format="fltp", layout=stream.layout, rate=stream.rate)
        chunks = []
        for frame in container.decode(stream):
            chunks += [f.to_ndarray() for f in resampler.resample(frame)]
        chunks += [f.to_ndarray() for f in resampler.resample(None)]
        if not chunks:
            raise SoundLoadError("no audio decoded")
        return np.concatenate(chunks, axis=1).T.astype(np.float64), float(stream.rate)


def _read_praat(path: Path) -> tuple[np.ndarray, float]:
    snd = parselmouth.Sound(str(path))
    return snd.values.T, snd.sampling_frequency


@dataclass(eq=False)
class Sound:
    """Audio held as a float64 array shaped (n_samples, n_channels)."""

    samples: np.ndarray
    sampling_rate: float
    path: Path | None = None
    title: str | None = None  # name for sounds not (yet) saved to a file
    id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self):
        samples = np.asarray(self.samples, dtype=np.float64)
        if samples.ndim == 1:
            samples = samples[:, np.newaxis]
        self.samples = samples
        self._praat: parselmouth.Sound | None = None

    def __getstate__(self):
        # Caches (the parselmouth copy, the mono mix) are rebuilt on demand after unpickling.
        state = self.__dict__.copy()
        state["_praat"] = None
        state.pop("mono", None)
        return state

    @classmethod
    def from_file(cls, path: str | Path) -> Sound:
        """Load with libsndfile, then FFmpeg (M4A/AAC and more), then Praat's own reader."""
        path = Path(path)
        errors = []
        for reader in (_read_soundfile, _read_ffmpeg, _read_praat):
            try:
                samples, sr = reader(path)
                break
            except Exception as e:  # each reader raises its own error types
                errors.append(e)
        else:
            # FFmpeg understands the most formats, so its message is the most useful one.
            reason = getattr(errors[1], "strerror", None) or errors[1]
            raise SoundLoadError(f"Could not read {path.name}: {reason}") from errors[-1]
        if samples.shape[0] == 0:
            raise SoundLoadError(f"{path.name} contains no audio")
        return cls(samples, float(sr), path)

    @property
    def name(self) -> str:
        if self.title:
            return self.title
        return self.path.stem if self.path else "untitled"

    @property
    def n_samples(self) -> int:
        return self.samples.shape[0]

    @property
    def n_channels(self) -> int:
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        return self.n_samples / self.sampling_rate

    @cached_property
    def mono(self) -> np.ndarray:
        if self.n_channels == 1:
            return self.samples[:, 0]
        return self.samples.mean(axis=1)

    @property
    def praat(self) -> parselmouth.Sound:
        """Mono parselmouth Sound used for all analyses (created lazily)."""
        if self._praat is None:
            self._praat = parselmouth.Sound(self.mono, sampling_frequency=self.sampling_rate)
        return self._praat

    def time_to_index(self, t: float) -> int:
        return int(np.clip(round(t * self.sampling_rate), 0, self.n_samples))

    def amplitude_at(self, t: float, channel: int = 0) -> float:
        i = min(self.time_to_index(t), self.n_samples - 1)
        return float(self.samples[i, channel])

    def extract(self, start: float, end: float) -> Sound:
        a, b = sorted((self.time_to_index(start), self.time_to_index(end)))
        return Sound(self.samples[a:b].copy(), self.sampling_rate)

    def save(self, path: str | Path) -> None:
        """Write to ``path``; the format (WAV, FLAC, AIFF, OGG, MP3) follows the extension."""
        sf.write(str(path), np.clip(self.samples, -1.0, 1.0), int(round(self.sampling_rate)))

    def save_as(self, path: str | Path) -> None:
        """Save and adopt ``path`` as this sound's file (its name follows the file from now on)."""
        self.save(path)
        self.path, self.title = Path(path), None
