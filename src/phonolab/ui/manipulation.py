"""Editable pitch and duration tiers of a document, with undo."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from phonolab.core.manipulation import ManipulationSettings, Tier


class ManipulationState(QObject):
    changed = pyqtSignal()

    def __init__(self, original: Tier, settings: ManipulationSettings, undo_stack: QUndoStack, parent=None):
        super().__init__(parent)
        self.original = original
        self.settings = settings
        self.pitch = original
        self.duration = Tier.empty()
        self.undo_stack = undo_stack

    @property
    def is_modified(self) -> bool:
        return self.pitch != self.original or len(self.duration) > 0

    def apply(self, description: str, pitch: Tier | None = None, duration: Tier | None = None) -> None:
        """Record a change of either tier as one undoable step."""
        after = (pitch if pitch is not None else self.pitch, duration if duration is not None else self.duration)
        before = (self.pitch, self.duration)
        if after[0] == before[0] and after[1] == before[1]:
            return
        self.undo_stack.push(_ManipulationCommand(self, description, before, after))

    def _set(self, pitch: Tier, duration: Tier) -> None:
        self.pitch, self.duration = pitch, duration
        self.changed.emit()

    def reset(self) -> None:
        self.apply("Reset manipulation", self.original, Tier.empty())


class _ManipulationCommand(QUndoCommand):
    def __init__(self, state: ManipulationState, text: str, before, after):
        super().__init__(text)
        self.state, self.before, self.after = state, before, after

    def redo(self):
        self.state._set(*self.after)

    def undo(self):
        self.state._set(*self.before)
