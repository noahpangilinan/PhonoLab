"""Sound document: audio samples plus the parselmouth object used for analysis."""

from __future__ import annotations

import contextlib
import gc
import shutil
import tempfile
import time
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

# Files with more sample values than this are kept on disk rather than in memory (about 20 minutes of
# 44.1 kHz stereo). Long sounds are analysed one window at a time, like Praat's LongSound.
LONG_SOUND_VALUES = 100_000_000
MAX_WINDOW_SECONDS = 60.0  # longest stretch of a long sound to analyse at once
MAX_PART_SECONDS = 600.0  # longest stretch to load into memory as an ordinary Sound
ENVELOPE_BLOCK = 256  # samples per block of the waveform's coarse min/max level
_CHUNK_FRAMES = ENVELOPE_BLOCK * 4096  # frames per streaming read; a whole number of blocks
_LONG_FOLDER_PREFIX = "phonolab-long-"
_SOUNDFILE_LONG_FORMATS = (".wav", ".flac", ".aiff", ".aif", ".ogg")
_STALE_SECONDS = 12 * 3600

_ids = count(1)


class SoundLoadError(Exception):
    pass


class SoundLoadCancelledError(Exception):
    pass


class LongSoundError(Exception):
    """The operation needs the whole sound in memory, or a shorter stretch of it."""


def remove_stale_long_files() -> None:
    """Delete working files left by earlier sessions (Windows can't delete a file while it's mapped)."""
    for folder in Path(tempfile.gettempdir()).glob(_LONG_FOLDER_PREFIX + "*"):
        with contextlib.suppress(OSError):
            if time.time() - folder.stat().st_mtime > _STALE_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)


def _estimated_values(path: Path) -> int:
    """Roughly how many sample values a file holds, without decoding it. 0 if unknown."""
    try:
        info = sf.info(str(path))
        return int(info.frames) * int(info.channels)
    except Exception:  # noqa: S110 - not a libsndfile format; FFmpeg may know
        pass
    try:
        import av

        with av.open(str(path)) as container:
            stream = container.streams.audio[0]
            return int(container.duration / av.time_base * stream.rate * stream.channels)
    except Exception:  # unreadable or no duration: the normal loading path will report it
        return 0


def _soundfile_blocks(path: Path):
    """Yield (float32 block shaped (n, channels), fraction done, sampling rate)."""
    with sf.SoundFile(str(path)) as f:
        total = max(f.frames, 1)
        done = 0
        for block in f.blocks(blocksize=_CHUNK_FRAMES, dtype="float32", always_2d=True):
            done += len(block)
            yield block, done / total, float(f.samplerate)


def _ffmpeg_blocks(path: Path):
    import av

    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        total = max(container.duration / av.time_base * stream.rate, 1.0)
        resampler = av.AudioResampler(format="fltp", layout=stream.layout, rate=stream.rate)
        pending, pending_frames, done = [], 0, 0
        for frame in (*container.decode(stream), None):
            for out in resampler.resample(frame):
                pending.append(out.to_ndarray().T)
                pending_frames += out.samples
            if pending_frames >= _CHUNK_FRAMES or (frame is None and pending):
                block = np.concatenate(pending)
                # Keep blocks a whole number of envelope blocks long, except the last.
                keep = len(block) if frame is None else len(block) // ENVELOPE_BLOCK * ENVELOPE_BLOCK
                done += keep
                yield np.ascontiguousarray(block[:keep], dtype=np.float32), min(done / total, 1.0), float(stream.rate)
                pending = [block[keep:]] if keep < len(block) else []
                pending_frames = len(block) - keep


def _load_long(path: Path, progress) -> Sound:
    """Stream a file into a memory-mapped float32 file, collecting the peak and waveform envelope on the way."""
    needed = _estimated_values(path) * 4
    free = shutil.disk_usage(tempfile.gettempdir()).free
    if needed * 1.05 > free:
        raise SoundLoadError(f"{path.name} needs {needed / 1e9:.1f} GB of free disk space to open")
    folder = Path(tempfile.mkdtemp(prefix=_LONG_FOLDER_PREFIX))
    raw = folder / "samples.f32"
    frames, channels, rate, peak = 0, 0, 0.0, 0.0
    lows, highs = [], []
    blocks = _soundfile_blocks if path.suffix.lower() in _SOUNDFILE_LONG_FORMATS else _ffmpeg_blocks
    try:
        with open(raw, "wb") as fh:
            for block, fraction, block_rate in blocks(path):
                rate = block_rate
                block.tofile(fh)
                frames += len(block)
                channels = block.shape[1]
                peak = max(peak, float(np.abs(block).max(initial=0.0)))
                n = len(block) // ENVELOPE_BLOCK * ENVELOPE_BLOCK
                grouped = block[:n].reshape(-1, ENVELOPE_BLOCK, channels)
                lows.append(grouped.min(axis=1))
                highs.append(grouped.max(axis=1))
                if progress is not None and progress(fraction) is False:
                    raise SoundLoadCancelledError
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if frames == 0:
        shutil.rmtree(folder, ignore_errors=True)
        raise SoundLoadError(f"{path.name} contains no audio")
    sound = Sound(np.memmap(raw, dtype=np.float32, mode="r", shape=(frames, channels)), rate, path)
    sound.peak_value = peak
    sound.block_envelope = (np.concatenate(lows), np.concatenate(highs))
    sound.long_folder = folder
    return sound


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

    samples: np.ndarray  # a read-only np.memmap for long sounds
    sampling_rate: float
    path: Path | None = None
    title: str | None = None  # name for sounds not (yet) saved to a file
    id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self):
        if not isinstance(self.samples, np.memmap):
            samples = np.asarray(self.samples, dtype=np.float64)
            if samples.ndim == 1:
                samples = samples[:, np.newaxis]
            self.samples = samples
        self._praat: parselmouth.Sound | None = None
        self.peak_value: float | None = None
        self.block_envelope: tuple[np.ndarray, np.ndarray] | None = None  # (min, max), each (blocks, channels)
        self.long_folder: Path | None = None

    @property
    def is_long(self) -> bool:
        return isinstance(self.samples, np.memmap)

    @property
    def peak(self) -> float:
        if self.peak_value is None:
            self.peak_value = float(np.max(np.abs(self.samples), initial=0.0))
        return self.peak_value

    def __getstate__(self):
        # Caches (the parselmouth copy, the mono mix) are rebuilt on demand after unpickling.
        state = self.__dict__.copy()
        state["_praat"] = None
        state.pop("mono", None)
        state["block_envelope"] = None
        if self.is_long:  # workers map the same file instead of receiving the samples
            state["samples"] = (self.samples.filename, self.samples.shape)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        if isinstance(self.samples, tuple):
            filename, shape = self.samples
            self.samples = np.memmap(filename, dtype=np.float32, mode="r", shape=shape)

    @classmethod
    def from_file(cls, path: str | Path, progress=None) -> Sound:
        """Load with libsndfile, then FFmpeg (M4A/AAC and more), then Praat's own reader.

        Very long files are streamed to a working file instead; ``progress(fraction)`` is called
        along the way and can return False to cancel (raising SoundLoadCancelledError).
        """
        path = Path(path)
        if _estimated_values(path) > LONG_SOUND_VALUES:
            return _load_long(path, progress)
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
        if self.is_long:
            raise LongSoundError("This recording is too long to process as a whole")
        if self.n_channels == 1:
            return self.samples[:, 0]
        return self.samples.mean(axis=1)

    @property
    def praat(self) -> parselmouth.Sound:
        """Mono parselmouth Sound used for all analyses (created lazily)."""
        if self.is_long:
            raise LongSoundError("This recording is too long to process as a whole")
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
        if self.is_long and (b - a) / self.sampling_rate > MAX_PART_SECONDS:
            raise LongSoundError(f"Select {MAX_PART_SECONDS / 60:.0f} minutes or less of this long recording")
        return Sound(np.array(self.samples[a:b], dtype=np.float64), self.sampling_rate)

    def part(self, start: float, end: float) -> tuple[Sound, float, float]:
        """This Sound for ordinary sounds; a loaded stretch of a long one. Returns (sound, start, end) in its time."""
        if not self.is_long:
            return self, start, end
        return self.extract(start, end), 0.0, abs(end - start)

    def release(self) -> None:
        """Try to delete a long sound's working file. On Windows it survives until nothing maps it;
        ``remove_stale_long_files`` then clears it in a later session."""
        if self.long_folder is not None:
            gc.collect()
            shutil.rmtree(self.long_folder, ignore_errors=True)

    def save(self, path: str | Path) -> None:
        """Write to ``path``; the format (WAV, FLAC, AIFF, OGG, MP3) follows the extension."""
        if not self.is_long:
            sf.write(str(path), np.clip(self.samples, -1.0, 1.0), int(round(self.sampling_rate)))
            return
        with sf.SoundFile(str(path), "w", int(round(self.sampling_rate)), self.n_channels) as out:
            for i in range(0, self.n_samples, _CHUNK_FRAMES):
                out.write(np.clip(self.samples[i : i + _CHUNK_FRAMES], -1.0, 1.0))

    def save_as(self, path: str | Path) -> None:
        """Save and adopt ``path`` as this sound's file (its name follows the file from now on)."""
        self.save(path)
        self.path, self.title = Path(path), None
