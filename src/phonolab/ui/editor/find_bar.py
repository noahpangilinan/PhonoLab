"""Find bar for TextGrid labels (Ctrl+F): Enter = next match, Shift+Enter = previous."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget

from phonolab.core.textgrid import TextGridError, find


class FindBar(QWidget):
    closed = pyqtSignal()

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view  # TextGridView
        self.field = QLineEdit()
        self.field.setPlaceholderText("Find label (Enter: next, Shift+Enter: previous, Esc: close)")
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(self._update_count)
        self.regex = QCheckBox("Regex")
        self.case = QCheckBox("Match case")
        for box in (self.regex, self.case):
            box.toggled.connect(self._update_count)
        self.count = QLabel()
        self.count.setMinimumWidth(90)
        prev_button = QToolButton(text="▲")
        prev_button.setToolTip("Previous match (Shift+Enter)")
        prev_button.clicked.connect(lambda: self.step(-1))
        next_button = QToolButton(text="▼")
        next_button.setToolTip("Next match (Enter)")
        next_button.clicked.connect(lambda: self.step(1))
        close_button = QToolButton(text="✕")
        close_button.setAutoRaise(True)
        close_button.clicked.connect(self.close_bar)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in (self.field, self.regex, self.case, self.count, prev_button, next_button, close_button):
            layout.addWidget(w, 1 if w is self.field else 0)
        self.field.installEventFilter(self)

    def open_bar(self):
        self.show()
        self.field.setFocus()
        self.field.selectAll()
        self._update_count()

    def close_bar(self):
        self.hide()
        self.closed.emit()

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.field and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.step(-1 if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
        return super().eventFilter(obj, ev)

    def matches(self) -> list[tuple[int, int]]:
        tg = self.view.doc.textgrid
        if tg is None or not self.field.text():
            return []
        try:
            return find(tg, self.field.text(), self.regex.isChecked(), self.case.isChecked())
        except TextGridError:
            return []

    def _update_count(self, *_):
        tg = self.view.doc.textgrid
        if tg is None or not self.field.text():
            self.count.setText("")
            return
        try:
            n = len(find(tg, self.field.text(), self.regex.isChecked(), self.case.isChecked()))
        except TextGridError:
            self.count.setText("bad pattern")
            return
        self.count.setText("no matches" if n == 0 else f"{n} match{'es' if n != 1 else ''}")

    def step(self, direction: int) -> bool:
        """Select the next (or previous) match after the current selection. Returns False if none."""
        hits = self.matches()
        if not hits:
            self._update_count()
            return False
        current = (self.view.selected_tier, self.view.selected_item)
        if current in hits:
            index = (hits.index(current) + direction) % len(hits)
        else:
            # Nothing selected among the hits: start at the first match at or after the cursor.
            cursor = self.view.axis.cursor
            starts = [self._start(h) for h in hits]
            after = [i for i, s in enumerate(starts) if s >= cursor]
            index = (after[0] if after else 0) if direction > 0 else ((after[0] - 1) if after else len(hits) - 1)
        tier, item = hits[index]
        self.view.select(tier, item)
        start = self._start(hits[index])
        self.view.axis.ensure_visible(start)
        self.count.setText(f"{index + 1} of {len(hits)}")
        return True

    def _start(self, hit) -> float:
        tier = self.view.tiers[hit[0]]
        item = tier.items[hit[1]]
        return getattr(item, "xmin", getattr(item, "time", 0.0))
