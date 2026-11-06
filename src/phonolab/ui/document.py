"""An open document: one Sound, an optional TextGrid, and its undo history."""

from __future__ import annotations

from itertools import count
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from phonolab.core.corrections import Corrections
from phonolab.core.sound import LongSoundError, Sound
from phonolab.core.textgrid import TextGrid, TextGridError
from phonolab.core.time_edit import Splice

_revisions = count(1)


class Document(QObject):
    # Emitted after any TextGrid mutation (including undo/redo and replacement).
    textgrid_changed = pyqtSignal()
    title_changed = pyqtSignal(str)
    corrections_changed = pyqtSignal()
    sound_changed = pyqtSignal()  # the audio itself was edited, undone or redone

    def __init__(self, sound: Sound, parent=None):
        super().__init__(parent)
        self.sound = sound
        self.textgrid: TextGrid | None = None
        self.textgrid_path: Path | None = None
        self._saved_textgrid: TextGrid | None = None  # as last loaded/saved; None = never saved
        self.manipulation = None  # ManipulationState once the user opens manipulation
        self.corrections = Corrections.load_for(sound.path)
        self._saved_corrections = self.corrections
        self._audio_revision = self._saved_audio_revision = 0
        self.analysis_channel: int | None = None  # None analyses the mix of all channels
        self._channel_sound: Sound | None = None
        self._channel_source: tuple | None = None
        # One undo history per document, shared by annotation and pitch/duration edits.
        self.undo_stack = QUndoStack(self)
        self.textgrid_changed.connect(lambda: self.title_changed.emit(self.title))

    @property
    def title(self) -> str:
        return self.sound.name + ("*" if self.is_dirty else "")

    @property
    def is_dirty(self) -> bool:
        return self.textgrid_dirty or self.sound_needs_saving or self.corrections_dirty

    @property
    def analysis_sound(self) -> Sound:
        """What measurements see: the mix of all channels, or the one chosen. Everything analysing audio uses this."""
        sound, channel = self.sound, self.analysis_channel
        if channel is None or sound.is_long:
            return sound
        if self._channel_source != (sound.id, channel):
            self._channel_sound = Sound(sound.samples[:, channel : channel + 1], sound.sampling_rate, title=sound.name)
            self._channel_source = (sound.id, channel)
        return self._channel_sound

    @property
    def corrections_dirty(self) -> bool:
        return self.corrections != self._saved_corrections

    def correct(self, description: str, corrections: Corrections) -> None:
        """Change the corrections as one undoable step."""
        if corrections != self.corrections:
            self.undo_stack.push(_CorrectionsCommand(self, description, self.corrections, corrections))

    def _set_corrections(self, corrections: Corrections) -> None:
        self.corrections = corrections
        self.corrections_changed.emit()
        self.title_changed.emit(self.title)

    def save_corrections(self) -> Path:
        """Save next to the sound (or delete the file if nothing is corrected any more)."""
        path = Corrections.path_for(self.sound.path)
        if self.corrections.is_empty:
            path.unlink(missing_ok=True)
        else:
            self.corrections.save(path)
        self._saved_corrections = self.corrections
        self.title_changed.emit(self.title)
        return path

    @property
    def textgrid_dirty(self) -> bool:
        return self.textgrid is not None and self.textgrid != self._saved_textgrid

    @property
    def sound_unsaved(self) -> bool:
        """True for sounds made inside PhonoLab (recorded, generated, filtered…) and not saved yet."""
        return self.sound.path is None

    @property
    def audio_dirty(self) -> bool:
        """True if the audio was edited since it was opened or saved."""
        return self._audio_revision != self._saved_audio_revision

    @property
    def sound_needs_saving(self) -> bool:
        return self.sound_unsaved or self.audio_dirty

    def save_sound(self, path: Path) -> None:
        moved = self.sound.path != path
        self.sound.save_as(path)
        self._saved_audio_revision = self._audio_revision
        if moved:  # corrections live next to the sound, so compare with what's beside the new file
            self._saved_corrections = Corrections.load_for(path)
        self.title_changed.emit(self.title)

    def splice_audio(self, description: str, start: int, end: int, inserted: np.ndarray | None = None) -> None:
        """Replace samples ``[start, end)`` with ``inserted`` as one undoable step, annotations included.

        Raises TextGridError or LongSoundError (and changes nothing) if the edit can't be made.
        """
        sound = self.sound
        if sound.is_long:
            raise LongSoundError("Long recordings can't be edited: extract a part first")
        added = 0 if inserted is None else len(inserted)
        if end == start and added == 0:
            return
        if added == 0 and end - start >= sound.n_samples:
            raise TextGridError("Can't cut the whole sound")
        rate = sound.sampling_rate
        splice = Splice(start / rate, (end - start) / rate, added / rate)
        grid = None if self.textgrid is None else splice.applied_to(self.textgrid)
        self.undo_stack.push(
            _AudioCommand(self, description, start, end, inserted, grid, self.corrections.spliced(splice))
        )

    def _set_audio(self, sound: Sound, grid: TextGrid | None, corrections: Corrections, manipulation, revision: int):
        self.sound, self.textgrid, self.corrections, self.manipulation = sound, grid, corrections, manipulation
        self._audio_revision = revision
        self.sound_changed.emit()
        self.corrections_changed.emit()
        self.textgrid_changed.emit()

    def set_textgrid(self, textgrid: TextGrid | None, path: Path | None = None, saved: bool = True) -> None:
        """Replace the TextGrid. ``saved=False`` marks a new grid as unsaved work."""
        self.textgrid = textgrid
        self.textgrid_path = path
        self._saved_textgrid = textgrid.copy() if textgrid is not None and saved else None
        self.undo_stack.clear()
        self.textgrid_changed.emit()

    def save_textgrid(self, path: Path, short: bool = False) -> None:
        self.textgrid.write(path, short=short)
        self.textgrid_path = path
        self._saved_textgrid = self.textgrid.copy()
        self.title_changed.emit(self.title)

    # ------------------------------------------------------------------ edits

    def edit(self, description: str, fn) -> object:
        """Apply ``fn(textgrid)`` as one undoable step. Returns fn's result.

        Raises TextGridError (and records nothing) if the edit is invalid.
        """
        before = self.begin_edit()
        result = fn(self.textgrid)  # may raise TextGridError
        self.commit_edit(description, before)
        return result

    def begin_edit(self) -> TextGrid:
        """Snapshot for an edit applied incrementally (e.g. dragging a boundary)."""
        return self.textgrid.copy()

    def commit_edit(self, description: str, before: TextGrid) -> None:
        self.undo_stack.push(_SnapshotCommand(self, description, before, self.textgrid.copy()))

    def set_label(self, tier: int, index: int, text: str) -> None:
        """Change a label; consecutive keystrokes on the same item merge into one undo step."""
        t = self.textgrid.tiers[tier]
        if not 0 <= index < len(t.items):
            raise TextGridError("No such interval")
        old = t.get_text(index)
        if old != text:
            self.undo_stack.push(_SetLabelCommand(self, tier, index, old, text))


class _AudioCommand(QUndoCommand):
    """Keeps only the samples that changed, so undo history stays small on long edits."""

    def __init__(self, doc: Document, text: str, start: int, end: int, inserted, grid, corrections: Corrections):
        super().__init__(text)
        self.doc, self.start, self.end = doc, start, end
        self.removed = np.array(doc.sound.samples[start:end])
        self.inserted = doc.sound.samples[:0] if inserted is None else np.array(inserted)
        self.grid_before = doc.textgrid.copy() if doc.textgrid is not None else None
        self.grid_after = grid
        self.corrections_before, self.corrections_after = doc.corrections, corrections
        self.manipulation_before = doc.manipulation
        self.manipulation_after = None  # the pitch points came from the old audio
        self.revision_before, self.revision_after = doc._audio_revision, next(_revisions)

    def redo(self):
        doc = self.doc
        self.manipulation_before = doc.manipulation
        grid = None if self.grid_after is None else self.grid_after.copy()
        sound = doc.sound.spliced(self.start, self.end, self.inserted)
        doc._set_audio(sound, grid, self.corrections_after, self.manipulation_after, self.revision_after)

    def undo(self):
        doc = self.doc
        self.manipulation_after = doc.manipulation  # later manipulation commands refer to this one
        grid = None if self.grid_before is None else self.grid_before.copy()
        sound = doc.sound.spliced(self.start, self.start + len(self.inserted), self.removed)
        doc._set_audio(sound, grid, self.corrections_before, self.manipulation_before, self.revision_before)


class _CorrectionsCommand(QUndoCommand):
    def __init__(self, doc: Document, text: str, before: Corrections, after: Corrections):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after

    def redo(self):
        self.doc._set_corrections(self.after)

    def undo(self):
        self.doc._set_corrections(self.before)


class _SnapshotCommand(QUndoCommand):
    def __init__(self, doc: Document, text: str, before: TextGrid, after: TextGrid):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after
        self._first = True

    def redo(self):
        if self._first:  # the edit was already applied by Document.edit
            self._first = False
        else:
            self.doc.textgrid = self.after.copy()
        self.doc.textgrid_changed.emit()

    def undo(self):
        self.doc.textgrid = self.before.copy()
        self.doc.textgrid_changed.emit()


class _SetLabelCommand(QUndoCommand):
    ID = 1

    def __init__(self, doc: Document, tier: int, index: int, old: str, new: str):
        super().__init__("Edit label")
        self.doc, self.tier, self.index, self.old, self.new = doc, tier, index, old, new

    def id(self):
        return self.ID

    def mergeWith(self, other):  # noqa: N802 - Qt API
        if (other.tier, other.index) != (self.tier, self.index):
            return False
        self.new = other.new
        return True

    def _apply(self, text):
        self.doc.textgrid.tiers[self.tier].set_text(self.index, text)
        self.doc.textgrid_changed.emit()

    def redo(self):
        self._apply(self.new)

    def undo(self):
        self._apply(self.old)
