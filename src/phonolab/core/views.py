"""Time-frequency views beyond the spectrogram: cepstrogram, cochleagram, MFCC (all from Praat)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from phonolab.core import praat_engine
from phonolab.core.sound import Sound

MAX_SECONDS = 60.0


@dataclass(frozen=True)
class View:
    label: str
    command: str
    y_label: str
    decibels: bool = False  # show 10·log10 of the values
    export: str = "To Matrix"
    y_range: tuple[float, float] | None = None  # rows worth showing
    dynamic_range: float | None = None  # show only this many dB below the peak


VIEWS = {
    # Quefrencies from 500 Hz down to 60 Hz: where the pitch peak can be, without the formant region below it.
    "cepstrogram": View(
        "Cepstrogram",
        "To PowerCepstrogram: 60, 0.002, 5000, 50",
        "Quefrency (s)",
        decibels=True,
        y_range=(0.002, 1 / 60),
        dynamic_range=25.0,
    ),
    "cochleagram": View("Cochleagram", "To Cochleagram: 0.01, 0.1, 0.03, 0.03", "Place (Bark)", decibels=False),
    "mfcc": View("MFCC", "To MFCC: 12, 0.015, 0.005, 100, 100, 0", "Coefficient"),
}


@dataclass(frozen=True)
class ViewResult:
    name: str
    times: np.ndarray
    ys: np.ndarray
    values: np.ndarray  # (len(ys), len(times))


def compute_view(sound: Sound, name: str, start: float, end: float) -> ViewResult:
    """One view of ``[start, end]``, with times on the whole sound's axis."""
    if not praat_engine.available():
        raise ValueError(f"The {VIEWS[name].label.lower()} needs the bundled Praat 7 program")
    if end - start > MAX_SECONDS:
        raise ValueError(f"Choose {MAX_SECONDS:.0f} seconds or less")
    view = VIEWS[name]
    part = sound.extract(start, end)
    body = f'{view.command}\n{view.export}\nSave as short text file: folder$ + "/view.Matrix"'
    _, folder = praat_engine.analyse_with_files(part, body)
    try:
        times, ys, values = praat_engine.read_matrix_with_rows(folder / "view.Matrix")
    finally:
        praat_engine.remove_folder(folder)
    if view.decibels:
        values = 10.0 * np.log10(np.maximum(values, 1e-30))
    if view.y_range is not None:
        keep = (ys >= view.y_range[0]) & (ys <= view.y_range[1])
        ys, values = ys[keep], values[keep]
    if view.dynamic_range is not None:
        values = np.maximum(values, values.max() - view.dynamic_range)
    return ViewResult(name, times + start, ys, values)
