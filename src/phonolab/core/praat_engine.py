"""Run the bundled Praat program headless, for everything newer than Parselmouth's Praat.

Parselmouth 0.4.7 embeds Praat 6.1.38 (2021). The official Praat program is bundled alongside
it and driven with ``--run``: each call starts a fresh process (about 0.07 s) and exchanges
data through temporary files. Without the program, callers fall back to Parselmouth.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import weakref
from pathlib import Path

import numpy as np
import platformdirs
import soundfile as sf

from phonolab.core.sound import Sound

PRAAT_VERSION = "7.0.02"  # the version packaging/fetch_praat.py installs
DEFAULT_TIMEOUT = 600.0  # s; transcription of long recordings is slow
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash from a windowed app

_RELATIVE_PATHS = {"win32": "praat/Praat.exe", "darwin": "praat/Praat.app/Contents/MacOS/Praat"}

# Saves the selected object as text, under a name the caller reads back with ``read_matrix``.
_PRELUDE = """procedure export: .name$
    Save as short text file: folder$ + "/" + .name$ + ".Matrix"
endproc
"""


class PraatEngineError(Exception):
    pass


def find_praat() -> Path | None:
    """The Praat program to use: $PHONOLAB_PRAAT, then bundled, then fetched for development.

    Setting PHONOLAB_PRAAT to "none" forces the Parselmouth fallback.
    """
    override = os.environ.get("PHONOLAB_PRAAT")
    if override:
        return None if override == "none" else Path(override)
    relative = _RELATIVE_PATHS.get(sys.platform)
    if relative is None:
        return None
    frozen_root = getattr(sys, "_MEIPASS", None)
    candidates = [Path(frozen_root)] if frozen_root else []
    candidates.append(Path(__file__).resolve().parents[3] / "packaging")
    return next((root / relative for root in candidates if (root / relative).exists()), None)


def available() -> bool:
    return find_praat() is not None


def preferences_folder() -> Path:
    """PhonoLab's own Praat preferences, which is also where Praat looks for Whisper models."""
    folder = Path(platformdirs.user_data_dir("PhonoLab", appauthor=False)) / "praat"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _quote(text: str | Path) -> str:
    """A Praat string literal; paths use forward slashes on every platform."""
    value = text.as_posix() if isinstance(text, Path) else text
    return '"' + value.replace('"', '""') + '"'


def _clean_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line.removeprefix("Error: ") for line in lines if line.startswith("Error:")]
    return errors[0] if errors else lines[-1] if lines else "Praat stopped unexpectedly"


def run_script(script: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Run Praat script text and return its Info output. Raises PraatEngineError on failure.

    Only the exit code signals failure: Praat also logs progress to stderr during transcription.
    ``--FULL-TRUST`` is needed for scripts to save files, which is how results come back.
    """
    program = find_praat()
    if program is None:
        raise PraatEngineError("The Praat program is not available")
    with tempfile.TemporaryDirectory(prefix="phonolab-") as folder:
        path = Path(folder) / "script.praat"
        path.write_text(script, encoding="utf-8")
        command = [
            str(program), "--run", "-8", "--no-plugins", "--FULL-TRUST",
            f"--pref-dir={preferences_folder()}", str(path),
        ]  # fmt: skip
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise PraatEngineError(f"Praat took longer than {timeout:.0f} s") from None
        except OSError as e:
            raise PraatEngineError(f"Could not start Praat: {e}") from e
    if done.returncode != 0:
        raise PraatEngineError(_clean_error(done.stderr.decode("utf-8", "replace")))
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def version() -> str | None:
    """The version the Praat program reports, or None if it isn't available."""
    program = find_praat()
    if program is None:
        return None
    try:
        done = subprocess.run(
            [str(program), "-8", "--version"], capture_output=True, timeout=30, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = done.stdout.decode("utf-8", "replace").replace("\x00", "").split()
    return words[1] if len(words) > 1 else None


def engine_description() -> str:
    """What produces PhonoLab's measurements, for the About box and logs."""
    return f"Praat {version()}" if available() else "Parselmouth (bundled Praat program not found)"


# Each Sound is written once and reused by every analysis. 64-bit float keeps the samples exact.
_wav_files: weakref.WeakKeyDictionary[Sound, Path] = weakref.WeakKeyDictionary()


def _remove_folder(folder: str) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def sound_file(sound: Sound) -> Path:
    """A mono WAV of ``sound`` for Praat to read; removed along with the Sound."""
    path = _wav_files.get(sound)
    if path is None or not path.exists():
        folder = tempfile.mkdtemp(prefix="phonolab-sound-")
        path = Path(folder) / "sound.wav"
        sf.write(str(path), sound.mono, int(round(sound.sampling_rate)), subtype="DOUBLE")
        _wav_files[sound] = path
        weakref.finalize(sound, _remove_folder, folder)
    return path


def read_matrix(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read Praat's short text Matrix format: returns (x values, rows shaped (ny, nx))."""
    with open(path, encoding="utf-8") as fh:
        tokens = fh.read().split("\n")[3:]
    numbers = [line for line in tokens if line.strip()]
    nx, dx, x1 = int(numbers[2]), float(numbers[3]), float(numbers[4])
    ny = int(numbers[7])
    cells = [float("nan") if n == "--undefined--" else float(n) for n in numbers[10 : 10 + nx * ny]]
    values = np.array(cells, dtype=float).reshape(ny, nx)
    return x1 + dx * np.arange(nx), values


def praat_bool(value: bool) -> str:
    return '"yes"' if value else '"no"'


def analyse(sound: Sound, body: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, dict[str, tuple]]:
    """Run ``body`` with the Sound selected as ``s``. Returns (Info output, exported matrices).

    The body calls ``@export: "name"`` with a Matrix selected; results are keyed by that name.
    """
    with tempfile.TemporaryDirectory(prefix="phonolab-out-") as folder:
        script = (
            f"folder$ = {_quote(Path(folder))}\n{_PRELUDE}s = Read from file: {_quote(sound_file(sound))}\n{body}\n"
        )
        output = run_script(script, timeout)
        return output, {p.stem: read_matrix(p) for p in Path(folder).glob("*.Matrix")}


def analyse_with_files(sound: Sound, body: str, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, Path]:
    """Like ``analyse``, for bodies saving other files to ``folder$``. The caller deletes the folder."""
    folder = tempfile.mkdtemp(prefix="phonolab-out-")
    script = f"folder$ = {_quote(Path(folder))}\ns = Read from file: {_quote(sound_file(sound))}\n{body}\n"
    try:
        return run_script(script, timeout), Path(folder)
    except PraatEngineError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
