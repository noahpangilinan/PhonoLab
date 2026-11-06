"""Annotations from speech corpora, read by the bundled Praat so they mean what they mean in Praat.

That includes things easily got wrong by hand, such as turning TIMIT's phones into IPA.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from phonolab.core import praat_engine
from phonolab.core.textgrid import TextGrid, TextGridError

CORPORA = ("TIMIT", "Buckeye")
NEEDS_PRAAT = "This needs the bundled Praat program, which wasn't found"


class CorpusError(Exception):
    pass


def _read(command: str) -> TextGrid:
    """Run a command that leaves a TextGrid among the selected objects, and read that TextGrid."""
    if not praat_engine.available():
        raise CorpusError(NEEDS_PRAAT)
    folder = Path(tempfile.mkdtemp(prefix="phonolab-corpus-"))
    target = folder / "out.TextGrid"
    try:
        praat_engine.run_script(
            f'{command}\ngrid = selected ("TextGrid")\nselectObject: grid\nSave as text file: "{target.as_posix()}"\n'
        )
        return TextGrid.read(target)
    except (praat_engine.PraatEngineError, TextGridError) as e:
        raise CorpusError(str(e)) from e
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _path(path: str | Path) -> str:
    return '"' + Path(path).as_posix().replace('"', '""') + '"'


def read_adjacent(sound_path: str | Path, corpus: str) -> TextGrid:
    """The annotations stored beside a corpus recording."""
    if corpus not in CORPORA:
        raise CorpusError(f"Unknown corpus: {corpus}")
    sound_path = Path(sound_path)
    if sound_path.name == sound_path.name.lower():
        return _read(f"Read Sound with adjacent annotation files ({corpus}): {_path(sound_path)}")
    # Praat only takes lower-case names, and original TIMIT discs have SA1.WAV and SA1.PHN.
    folder = Path(tempfile.mkdtemp(prefix="phonolab-corpus-"))
    try:
        for file in sound_path.parent.glob(f"{sound_path.stem}.*"):
            shutil.copy(file, folder / file.name.lower())
        path = folder / sound_path.name.lower()
        return _read(f"Read Sound with adjacent annotation files ({corpus}): {_path(path)}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def read_esps(path: str | Path, points: bool = False) -> TextGrid:
    """An ESPS (xwaves) label file, as intervals ending at each label or as points."""
    return _read(f"Read TextGrid from ESPS label file: {_path(path)}, {praat_engine.praat_bool(points)}, 0")


def read_with_praat(path: str | Path) -> TextGrid:
    """Any annotation file that Praat recognises by itself."""
    return _read(f"Read from file: {_path(path)}")
