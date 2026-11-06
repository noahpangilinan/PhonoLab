"""Run analyses in worker processes and cache their results per document.

Parselmouth holds the GIL while Praat computes, so threads would freeze the GUI.
Instead each sound's mono samples are placed in shared memory once and analyses
run in worker processes that attach to it. Spectrograms (requested on every
scroll/zoom) get their own worker so they never queue behind a slow formant job.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import multiprocessing as mp
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import replace
from multiprocessing import shared_memory

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from phonolab.core import registry
from phonolab.core.analysis import shift_times
from phonolab.core.corrections import Corrections
from phonolab.core.sound import MAX_WINDOW_SECONDS, LongSoundError, Sound

log = logging.getLogger(__name__)

CORRECTED = {"pitch", "pulses", "voicing"}  # analyses that hand corrections change
ZOOM_HINT = f"Zoom in to {MAX_WINDOW_SECONDS:.0f} seconds or less to see analyses"

# ---------------------------------------------------------------- worker process side

_MAX_CACHED_SOUNDS = 2
_worker_sounds: OrderedDict[str, tuple[shared_memory.SharedMemory, Sound]] = OrderedDict()


def _attach(shm_name: str, n_samples: int, sampling_rate: float) -> Sound:
    if shm_name in _worker_sounds:
        _worker_sounds.move_to_end(shm_name)
        return _worker_sounds[shm_name][1]
    # track=False: the GUI process owns (and unlinks) the block, not this worker.
    shm = shared_memory.SharedMemory(name=shm_name, track=False)
    samples = np.ndarray((n_samples,), dtype=np.float64, buffer=shm.buf)
    sound = Sound(samples, sampling_rate)
    _worker_sounds[shm_name] = (shm, sound)
    while len(_worker_sounds) > _MAX_CACHED_SOUNDS:
        old_shm, old_sound = _worker_sounds.popitem(last=False)[1]
        del old_sound
        # BufferError: a numpy view is still alive; the OS frees the block at exit.
        with contextlib.suppress(BufferError):
            old_shm.close()
    return sound


def _run_analysis(shm_name: str, n_samples: int, sampling_rate: float, name: str, args: tuple):
    sound = _attach(shm_name, n_samples, sampling_rate)
    _, fn = registry.ANALYSES[name]
    return fn(sound, *args)


def _run_job(shm_name: str, n_samples: int, sampling_rate: float, fn, args: tuple):
    """Run ``fn(sound, *args)`` (a module-level function) on the shared sound."""
    return fn(_attach(shm_name, n_samples, sampling_rate), *args)


def _run_long_analysis(sound: Sound, name: str, args: tuple, start: float, end: float):
    """Analyse one stretch of a long sound. ``sound`` arrives as a file name, not as samples."""
    _, fn = registry.ANALYSES[name]
    return shift_times(fn(sound.extract(start, end), *args), start)


def _run_on_sound(sound: Sound, fn, args: tuple):
    return fn(sound, *args)


# ---------------------------------------------------------------- GUI process side

_executors: dict[str, ProcessPoolExecutor] = {}


def _executor(kind: str) -> ProcessPoolExecutor:
    if kind not in _executors:
        _executors[kind] = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
    return _executors[kind]


def warm_up() -> None:
    """Start the worker processes early so the first analysis isn't delayed by start-up."""
    for kind in ("spectrogram", "analysis"):
        _executor(kind).submit(int, 0)


def run_in_worker(kind: str, fn, *args) -> Future:
    """Run a picklable call in the named worker process (started on first use)."""
    return _executor(kind).submit(fn, *args)


def kill_worker(kind: str) -> None:
    """Terminate a worker that may be stuck (e.g. a script in an endless loop); it restarts on next use."""
    ex = _executors.pop(kind, None)
    if ex is None:
        return
    # ProcessPoolExecutor has no public way to stop a running task, so end its processes directly.
    for process in list(getattr(ex, "_processes", {}).values()):
        process.terminate()
    ex.shutdown(wait=False, cancel_futures=True)


@atexit.register
def shutdown() -> None:
    for ex in _executors.values():
        ex.shutdown(wait=False, cancel_futures=True)
    _executors.clear()


class SharedSound:
    """The mono samples of a Sound in shared memory, readable by worker processes."""

    def __init__(self, sound: Sound):
        mono = np.ascontiguousarray(sound.mono, dtype=np.float64)
        self.n_samples = len(mono)
        self.sampling_rate = sound.sampling_rate
        self.shm = shared_memory.SharedMemory(create=True, size=max(mono.nbytes, 8))
        np.ndarray(mono.shape, dtype=np.float64, buffer=self.shm.buf)[:] = mono

    def close(self) -> None:
        if self.shm is not None:
            self.shm.close()
            self.shm.unlink()
            self.shm = None


class _Signals(QObject):
    done = pyqtSignal(str, int, object)  # name, token, result
    failed = pyqtSignal(str, int, str)


class AnalysisManager(QObject):
    """Holds the latest result and settings of every analysis for one sound.

    Pitch, formants and intensity are computed once over the whole sound; the
    spectrogram is computed for the visible window so it stays sharp when zoomed.

    Long sounds are too big to analyse whole, so every analysis covers ``analysis_window``:
    a stretch around the view, or None when the view is wider than MAX_WINDOW_SECONDS.
    """

    result_ready = pyqtSignal(str)
    job_done = pyqtSignal(str, object)  # key, result of submit()
    job_failed = pyqtSignal(str, str)
    busy_changed = pyqtSignal(str, bool)  # name, busy
    error = pyqtSignal(str, str)
    window_changed = pyqtSignal(bool)  # long sounds: whether analyses are available at this zoom

    def __init__(self, sound: Sound, settings: dict, parent=None):
        super().__init__(parent)
        self.sound = sound
        self.settings = dict(settings)
        self.results: dict[str, object] = {}  # what the rest of the app sees, with corrections applied
        self.raw_results: dict[str, object] = {}
        self.corrections = Corrections()
        self.enabled: set[str] = set()
        self._tokens: dict[str, int] = {}
        self._futures: dict[str, Future] = {}
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._job_signals = _Signals()
        self._job_signals.done.connect(self._on_job_done)
        self._job_signals.failed.connect(self._on_job_failed)
        self._spectrogram_range = (0.0, sound.duration)
        self.analysis_window: tuple[float, float] | None = None
        self._shared = None if sound.is_long else SharedSound(sound)
        self._open = [True]  # shared with job callbacks, which can outlive this object

    def close(self) -> None:
        """Release shared memory; call when the document closes."""
        self._open[0] = False
        for fut in self._futures.values():
            fut.cancel()
        self._tokens.clear()
        if self._shared is not None:
            self._shared.close()

    @property
    def analyses_available(self) -> bool:
        return not self.sound.is_long or self.analysis_window is not None

    def covers(self, start: float, end: float) -> bool:
        """Whether current results span ``[start, end]``, so statistics over it would be complete."""
        if not self.sound.is_long:
            return True
        window = self.analysis_window
        return window is not None and window[0] <= start and end <= window[1]

    def set_sound(self, sound: Sound) -> None:
        """Start over on edited audio. Whatever is still running answers for the old sound, so drop it."""
        for key in self._tokens:
            self._tokens[key] += 1
            self.busy_changed.emit(key, False)
        for future in self._futures.values():
            future.cancel()
        self._futures.clear()
        self.results.clear()
        self.raw_results.clear()
        self.sound = sound
        start, end = self._spectrogram_range
        self._spectrogram_range = (min(start, sound.duration), min(end, sound.duration))
        if self._shared is not None:
            self._shared.close()
        self._shared = SharedSound(sound)
        for name in self.enabled:
            self.request(name)

    def set_corrections(self, corrections: Corrections) -> None:
        """Apply new corrections to existing results; no need to re-analyse."""
        self.corrections = corrections
        for name in CORRECTED & set(self.raw_results):
            self._store(name, self.raw_results[name])
            self.result_ready.emit(name)

    def _store(self, name: str, raw) -> None:
        self.raw_results[name] = raw
        c = self.corrections
        if name == "pitch":
            self.results[name] = c.apply_pitch(raw)
        elif name == "pulses":
            self.results[name] = replace(raw, times=c.apply_pulses(raw.times))
        elif name == "voicing":
            self.results[name] = c.apply_voicing(raw)
        else:
            self.results[name] = raw

    def set_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.enabled.add(name)
            if name not in self.results:
                self.request(name)
        else:
            self.enabled.discard(name)

    def update_settings(self, name: str, settings) -> None:
        self.settings[name] = settings
        for affected in (name, *registry.dependents(name)):
            self.results.pop(affected, None)
            self.raw_results.pop(affected, None)
            if affected in self.enabled:
                self.request(affected)

    def set_spectrogram_range(self, start: float, end: float) -> None:
        self._spectrogram_range = (start, end)
        if self.sound.is_long:
            self._follow_view(start, end)
        if "spectrogram" in self.enabled and self.analyses_available:
            self.request("spectrogram")

    def _follow_view(self, start: float, end: float) -> None:
        """Keep the analysis window around the view, with room to scroll before re-analysing."""
        width = end - start
        if width > MAX_WINDOW_SECONDS:
            if self.analysis_window is not None:
                self.analysis_window = None
                for name in self.enabled | set(self.results):
                    self._tokens[name] = self._tokens.get(name, 0) + 1  # drop anything still running
                self.results.clear()
                self.raw_results.clear()
                self.window_changed.emit(False)
            return
        if self.covers(start, end):
            return
        first = self.analysis_window is None
        margin = width / 2 + 1.0  # the extra second gives analyses context at the edges
        self.analysis_window = (max(0.0, start - margin), min(self.sound.duration, end + margin))
        if first:
            self.window_changed.emit(True)
        # Results from the old window must not answer for this one, even while the new ones are computing.
        self.results = {k: v for k, v in self.results.items() if k == "spectrogram"}
        self.raw_results = {k: v for k, v in self.raw_results.items() if k == "spectrogram"}
        for name in self.enabled - {"spectrogram"}:
            self.request(name)

    def request(self, name: str) -> None:
        if not self._open[0] or not self.analyses_available:
            return
        extra = self._spectrogram_range if name == "spectrogram" else ()
        token = self._tokens.get(name, 0) + 1
        self._tokens[name] = token
        if (old := self._futures.get(name)) is not None:
            old.cancel()  # only succeeds if it hasn't started; stale results are dropped anyway
        kind = "spectrogram" if name == "spectrogram" else "analysis"
        shared, args = self._shared, registry.compute_args(name, self.settings)
        try:
            if self.sound.is_long:
                span = self._spectrogram_range if name == "spectrogram" else self.analysis_window
                fut = _executor(kind).submit(_run_long_analysis, self.sound, name, args, *span)
            else:
                fut = _executor(kind).submit(
                    _run_analysis, shared.shm.name, shared.n_samples, shared.sampling_rate,
                    name, (*args, *extra),
                )  # fmt: skip
        except RuntimeError as e:  # pool shut down or broken
            self.error.emit(name, str(e))
            return
        self._futures[name] = fut
        self.busy_changed.emit(name, True)
        signals, is_open = self._signals, self._open

        def finished(f: Future):
            # Runs on the executor's management thread; Qt queues the signal to the GUI thread.
            # A closed document's shared memory is gone, so its pending jobs fail: ignore them.
            if f.cancelled() or not is_open[0]:
                return
            try:
                if (exc := f.exception()) is not None:
                    log.warning("analysis %s failed: %r", name, exc)
                    signals.failed.emit(name, token, str(exc))
                else:
                    signals.done.emit(name, token, f.result())
            except RuntimeError:  # the document was closed meanwhile
                pass

        fut.add_done_callback(finished)

    def submit(self, key: str, fn, *args) -> None:
        """Run ``fn(sound, *args)`` in the analysis worker; emits job_done/job_failed with ``key``.

        A newer submit with the same key supersedes an older one.
        """
        if not self._open[0]:
            return
        token = self._tokens.get(key, 0) + 1
        self._tokens[key] = token
        shared = self._shared
        if self.sound.is_long:
            fut = _executor("analysis").submit(_run_on_sound, self.sound, fn, args)
        else:
            fut = _executor("analysis").submit(
                _run_job, shared.shm.name, shared.n_samples, shared.sampling_rate, fn, args
            )
        self.busy_changed.emit(key, True)
        signals, is_open = self._job_signals, self._open

        def finished(f: Future):
            if f.cancelled() or not is_open[0]:  # cancelled, or the document closed
                return
            try:
                if (exc := f.exception()) is not None:
                    signals.failed.emit(key, token, str(exc))
                else:
                    signals.done.emit(key, token, f.result())
            except RuntimeError:  # the document was closed meanwhile
                pass

        fut.add_done_callback(finished)

    def _on_job_done(self, key: str, token: int, result):
        if token == self._tokens.get(key):
            self.busy_changed.emit(key, False)
            self.job_done.emit(key, result)

    def _on_job_failed(self, key: str, token: int, message: str):
        if token == self._tokens.get(key):
            self.busy_changed.emit(key, False)
            self.job_failed.emit(key, message)

    def compute_now(self, name: str):
        """Compute synchronously in this process (for queries on hidden layers)."""
        if self.sound.is_long:
            if self.analysis_window is None:
                raise LongSoundError(ZOOM_HINT)
            start, end = self.analysis_window
            part = self.sound.extract(start, end)
            self._store(name, shift_times(registry.compute(name, part, self.settings), start))
        else:
            self._store(name, registry.compute(name, self.sound, self.settings))
        return self.results[name]

    def _on_done(self, name: str, token: int, result):
        if token != self._tokens.get(name):
            return  # superseded by a newer request
        self._store(name, result)
        self.busy_changed.emit(name, False)
        self.result_ready.emit(name)

    def _on_failed(self, name: str, token: int, message: str):
        if token != self._tokens.get(name):
            return
        self.busy_changed.emit(name, False)
        self.error.emit(name, message)
