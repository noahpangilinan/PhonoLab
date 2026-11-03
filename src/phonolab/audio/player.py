"""Audio playback of a time range, with a Qt signal when playback ends."""

from __future__ import annotations

import logging
import time

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

try:
    import sounddevice as sd
except OSError:  # PortAudio missing
    sd = None

log = logging.getLogger(__name__)


class PlaybackBuffer:
    """Hands out consecutive blocks of ``samples[start:end]``; no audio device needed."""

    def __init__(self, samples: np.ndarray, start: int, end: int):
        self.samples = samples
        self.start = max(0, start)
        self.end = min(len(samples), end)
        self.frame = self.start

    @property
    def done(self) -> bool:
        return self.frame >= self.end

    def fill(self, out: np.ndarray) -> int:
        """Copy the next block into ``out`` (zero-padded). Returns frames written."""
        n = max(0, min(len(out), self.end - self.frame))
        out[:n] = self.samples[self.frame : self.frame + n]
        out[n:] = 0
        self.frame += n
        return n


class AudioPlayer(QObject):
    started = pyqtSignal()
    # Emitted once per play(), when the range ends or stop() is called. May come
    # from the audio thread; Qt queues it to the receiver's thread.
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._buffer: PlaybackBuffer | None = None
        self._sr = 1.0
        self._latency = 0.0
        self._started_at = 0.0  # time.monotonic() when the stream started
        self._generation = 0
        self._active: int | None = None  # generation whose finished hasn't fired yet

    @property
    def available(self) -> bool:
        return sd is not None

    @property
    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active

    @property
    def position(self) -> float:
        """Time (s) of the sample currently audible.

        Uses the wall clock rather than the callback's frame counter, which runs
        ahead of the speaker by the output latency and advances in bursts.
        """
        if self._buffer is None:
            return 0.0
        elapsed = max(0.0, time.monotonic() - self._started_at - self._latency)
        start, end = self._buffer.start / self._sr, self._buffer.end / self._sr
        return min(start + elapsed, end)

    def play(self, samples: np.ndarray, sampling_rate: float, start: float, end: float) -> None:
        if sd is None:
            raise RuntimeError("Audio output is unavailable (PortAudio not found)")
        self.stop()
        if samples.ndim == 1:
            samples = samples[:, np.newaxis]
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        self._sr = float(sampling_rate)
        buffer = PlaybackBuffer(samples, int(start * self._sr), int(end * self._sr))
        if buffer.done:
            return
        self._buffer = buffer
        self._generation += 1
        generation = self._active = self._generation

        def on_finished():
            # Ignore streams that were superseded or stopped explicitly.
            if self._active == generation:
                self._active = None
                self.finished.emit()

        def callback(outdata, frames, _time, status):
            if status:
                log.debug("playback status: %s", status)
            buffer.fill(outdata)
            if buffer.done:
                raise sd.CallbackStop

        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=samples.shape[1],
            dtype="float32",
            callback=callback,
            finished_callback=on_finished,
        )
        self._latency = float(self._stream.latency)
        self._stream.start()
        self._started_at = time.monotonic()
        self.started.emit()

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        active, self._active = self._active, None
        # abort() discards queued audio so stopping feels instant.
        stream.abort()
        stream.close()
        if active is not None:
            self.finished.emit()
