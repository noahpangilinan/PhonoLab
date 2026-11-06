"""Editable pitch, duration and loudness tiers of a document, with undo."""

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
        self.gain = Tier.empty()  # dB
        self.undo_stack = undo_stack

    @property
    def is_modified(self) -> bool:
        return self.pitch != self.original or len(self.duration) > 0 or len(self.gain) > 0

    def apply(
        self, description: str, pitch: Tier | None = None, duration: Tier | None = None, gain: Tier | None = None
    ) -> None:
        """Record a change of either tier as one undoable step."""
        before = (self.pitch, self.duration, self.gain)
        after = tuple(new if new is not None else old for new, old in zip((pitch, duration, gain), before, strict=True))
        if all(a == b for a, b in zip(after, before, strict=True)):
            return
        self.undo_stack.push(_ManipulationCommand(self, description, before, after))

    def _set(self, pitch: Tier, duration: Tier, gain: Tier) -> None:
        self.pitch, self.duration, self.gain = pitch, duration, gain
        self.changed.emit()

    def reset(self) -> None:
        self.apply("Reset manipulation", self.original, Tier.empty(), Tier.empty())


class _ManipulationCommand(QUndoCommand):
    def __init__(self, state: ManipulationState, text: str, before, after):
        super().__init__(text)
        self.state, self.before, self.after = state, before, after

    def redo(self):
        self.state._set(*self.after)

    def undo(self):
        self.state._set(*self.before)
