"""Shared time state for every pane of one editor: visible window, cursor, selection."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

MIN_VIEW = 0.001  # s; don't zoom in further than 1 ms


class TimeAxisController(QObject):
    view_changed = pyqtSignal(float, float)
    cursor_changed = pyqtSignal(float)
    selection_changed = pyqtSignal(object)  # (start, end) or None
    hover_changed = pyqtSignal(object, object)  # time or None, frequency (Hz) or None

    def __init__(self, duration: float, parent=None):
        super().__init__(parent)
        self.duration = duration
        self.view = (0.0, duration)
        self.cursor = 0.0
        self.selection: tuple[float, float] | None = None

    def set_duration(self, duration: float, view: tuple[float, float] | None = None) -> None:
        """The sound changed length. Tells everyone, because what's on screen changed even if the view didn't."""
        was_whole = self.view == (0.0, self.duration)
        self.duration = duration
        width = duration if was_whole else min(self.view[1] - self.view[0], duration)
        start = min(max(self.view[0], 0.0), duration - width)
        self.view = view or (start, start + width)
        self.cursor = min(self.cursor, duration)
        if self.selection and self.selection[1] > duration:
            self.selection = None
        self.view_changed.emit(*self.view)
        self.cursor_changed.emit(self.cursor)
        self.selection_changed.emit(self.selection)

    # ------------------------------------------------------------------ view

    def set_view(self, start: float, end: float) -> None:
        width = min(max(end - start, MIN_VIEW), self.duration)
        start = min(max(start, 0.0), self.duration - width)
        new = (start, start + width)
        if new != self.view:
            self.view = new
            self.view_changed.emit(*new)

    def zoom(self, factor: float, center: float | None = None) -> None:
        """factor < 1 zooms in. The time under ``center`` stays put."""
        start, end = self.view
        if center is None:
            center = self.cursor if start <= self.cursor <= end else (start + end) / 2
        self.set_view(center - (center - start) * factor, center + (end - center) * factor)

    def scroll(self, fraction: float) -> None:
        start, end = self.view
        shift = (end - start) * fraction
        self.set_view(start + shift, end + shift)

    def show_all(self) -> None:
        self.set_view(0.0, self.duration)

    def zoom_to_selection(self) -> None:
        if self.selection:
            self.set_view(*self.selection)

    def ensure_visible(self, t: float) -> None:
        """Page the view so ``t`` is on screen (used to follow the playhead)."""
        start, end = self.view
        if not start <= t <= end:
            self.set_view(t, t + (end - start))

    # ------------------------------------------------------------------ cursor / selection

    def clamp(self, t: float) -> float:
        return min(max(t, 0.0), self.duration)

    def set_cursor(self, t: float) -> None:
        self.cursor = self.clamp(t)
        self.cursor_changed.emit(self.cursor)

    def set_selection(self, start: float, end: float) -> None:
        start, end = sorted((self.clamp(start), self.clamp(end)))
        if end - start <= 0:
            self.clear_selection()
            return
        self.selection = (start, end)
        self.selection_changed.emit(self.selection)

    def clear_selection(self) -> None:
        if self.selection is not None:
            self.selection = None
            self.selection_changed.emit(None)

    def select_all(self) -> None:
        self.set_selection(0.0, self.duration)

    def play_range(self) -> tuple[float, float]:
        """Selection if there is one, else from the cursor to the end of the visible window."""
        if self.selection:
            return self.selection
        start, end = self.view
        begin = self.cursor if start <= self.cursor < end else start
        return begin, end

    def set_hover(self, t: float | None, freq: float | None = None) -> None:
        self.hover_changed.emit(t, freq)
