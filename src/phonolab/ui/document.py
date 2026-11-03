"""An open document: one Sound, an optional TextGrid, and its undo history."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from phonolab.core.sound import Sound
from phonolab.core.textgrid import TextGrid, TextGridError


class Document(QObject):
    # Emitted after any TextGrid mutation (including undo/redo and replacement).
    textgrid_changed = pyqtSignal()
    title_changed = pyqtSignal(str)

    def __init__(self, sound: Sound, parent=None):
        super().__init__(parent)
        self.sound = sound
        self.textgrid: TextGrid | None = None
        self.textgrid_path: Path | None = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(lambda _: self.title_changed.emit(self.title))

    @property
    def title(self) -> str:
        return self.sound.name + ("*" if self.is_dirty else "")

    @property
    def is_dirty(self) -> bool:
        return self.textgrid_dirty or self.sound_unsaved

    @property
    def textgrid_dirty(self) -> bool:
        return self.textgrid is not None and not self.undo_stack.isClean()

    @property
    def sound_unsaved(self) -> bool:
        """True for sounds made inside PhonoLab (recorded, generated, filtered…) and not saved yet."""
        return self.sound.path is None

    def save_sound(self, path: Path) -> None:
        self.sound.save_as(path)
        self.title_changed.emit(self.title)

    def set_textgrid(self, textgrid: TextGrid | None, path: Path | None = None) -> None:
        self.textgrid = textgrid
        self.textgrid_path = path
        self.undo_stack.clear()
        self.textgrid_changed.emit()
        self.title_changed.emit(self.title)

    def save_textgrid(self, path: Path, short: bool = False) -> None:
        self.textgrid.write(path, short=short)
        self.textgrid_path = path
        self.undo_stack.setClean()

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
