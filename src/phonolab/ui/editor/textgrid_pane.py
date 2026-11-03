"""TextGrid annotation view: one row per tier, aligned with the plot panes above it."""

from __future__ import annotations

import bisect
from copy import deepcopy

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QInputDialog, QMenu, QMessageBox, QSizePolicy, QWidget

from phonolab.core.ipa import to_unicode
from phonolab.core.textgrid import IntervalTier, PointTier, TextGridError
from phonolab.ui.document import Document
from phonolab.ui.editor.time_axis import TimeAxisController
from phonolab.ui.theme import COLORS

TIER_HEIGHT = 46
GRAB_PX = 5  # how close (pixels) the mouse must be to grab a boundary or point


class TextGridView(QWidget):
    """Draws and edits the document's TextGrid.

    Click selects an interval (or point), drag moves a boundary, double-click adds
    one, Enter adds one at the cursor, Delete/Alt+Backspace removes the nearest one.
    """

    item_selected = pyqtSignal()  # selected tier/item changed
    message = pyqtSignal(str)
    type_text = pyqtSignal(str)  # printable keys typed while the view has focus

    def __init__(self, axis: TimeAxisController, doc: Document, plot_area, parent=None):
        super().__init__(parent)
        self.axis = axis
        self.doc = doc
        self.plot_area = plot_area  # callable -> (left_px, right_px)
        self.selected_tier = 0
        self.selected_item: int | None = None
        self.playhead: float | None = None
        self._drag = None  # (tier, index, snapshot) while dragging
        self._hover = None  # (tier, index) of the boundary/point under the mouse
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.label_font = QFont(self.font())
        self.label_font.setPointSizeF(self.font().pointSizeF() * 1.15)
        for sig in (axis.view_changed, axis.cursor_changed, axis.selection_changed):
            sig.connect(self.update)
        doc.textgrid_changed.connect(self._on_textgrid_changed)
        self._on_textgrid_changed()

    # ------------------------------------------------------------------ helpers

    @property
    def tiers(self):
        return self.doc.textgrid.tiers if self.doc.textgrid else []

    def current_tier(self):
        if 0 <= self.selected_tier < len(self.tiers):
            return self.tiers[self.selected_tier]
        return None

    def _on_textgrid_changed(self):
        n = len(self.tiers)
        self.setFixedHeight(max(n, 1) * TIER_HEIGHT + 1 if n else 0)
        self.setVisible(n > 0)
        self.selected_tier = min(self.selected_tier, max(n - 1, 0))
        tier = self.current_tier()
        if tier is None or (self.selected_item is not None and self.selected_item >= len(tier.items)):
            self.selected_item = None
        self.update()
        self.item_selected.emit()

    def _x(self, t: float) -> float:
        left, right = self.plot_area()
        v0, v1 = self.axis.view
        return left + (t - v0) / (v1 - v0) * (right - left)

    def _t(self, x: float) -> float:
        left, right = self.plot_area()
        v0, v1 = self.axis.view
        return v0 + (x - left) / max(right - left, 1) * (v1 - v0)

    def _tier_at(self, y: float) -> int | None:
        i = int(y // TIER_HEIGHT)
        return i if 0 <= i < len(self.tiers) else None

    def _grab_tolerance(self) -> float:
        left, right = self.plot_area()
        v0, v1 = self.axis.view
        return GRAB_PX * (v1 - v0) / max(right - left, 1)

    def _handle_near(self, tier_index: int, t: float, tolerance=None) -> int | None:
        tier = self.tiers[tier_index]
        tol = self._grab_tolerance() if tolerance is None else tolerance
        if isinstance(tier, IntervalTier):
            return tier.boundary_near(t, tol)
        return tier.point_near(t, tol)

    def _try(self, description: str, fn):
        try:
            return self.doc.edit(description, fn)
        except TextGridError as e:
            self.message.emit(str(e))
            return None

    # ------------------------------------------------------------------ selection

    def select(self, tier: int, item: int | None):
        self.selected_tier, self.selected_item = tier, item
        t = self.tiers[tier]
        if item is not None and isinstance(t, IntervalTier):
            iv = t.intervals[item]
            self.axis.set_selection(iv.xmin, iv.xmax)
            self.axis.set_cursor(iv.xmin)
        elif item is not None:
            self.axis.clear_selection()
            self.axis.set_cursor(t.points[item].time)
        self.update()
        self.item_selected.emit()

    def select_adjacent(self, step: int):
        tier = self.current_tier()
        if tier is None or not tier.items:
            return
        if self.selected_item is None:
            idx = tier.interval_at(self.axis.cursor) if isinstance(tier, IntervalTier) else 0
        else:
            idx = min(max(self.selected_item + step, 0), len(tier.items) - 1)
        self.select(self.selected_tier, idx)
        t0 = tier.intervals[idx].xmin if isinstance(tier, IntervalTier) else tier.points[idx].time
        self.axis.ensure_visible(t0)

    # ------------------------------------------------------------------ editing

    def add_at_cursor(self):
        tier = self.current_tier()
        if tier is None:
            return
        self._add(self.selected_tier, self.axis.cursor)

    def _add(self, tier_index: int, t: float):
        tier = self.tiers[tier_index]
        if isinstance(tier, IntervalTier):
            idx = self._try("Add boundary", lambda tg: tg.tiers[tier_index].add_boundary(t))
            if idx is not None:
                self.select(tier_index, idx - 1)
                # Keep the cursor on the new boundary, so Delete right away removes it again.
                self.axis.set_cursor(t)
        else:
            idx = self._try("Add point", lambda tg: tg.tiers[tier_index].add_point(t))
            if idx is not None:
                self.select(tier_index, idx)

    def remove_near_cursor(self):
        tier = self.current_tier()
        if tier is None:
            return
        ti = self.selected_tier
        if isinstance(tier, PointTier) and self.selected_item is not None:
            idx = self.selected_item
        else:
            idx = self._handle_near(ti, self.axis.cursor, self._grab_tolerance() * 3)
        if idx is None:
            self.message.emit("No boundary or point at the cursor")
            return
        if isinstance(tier, IntervalTier):
            self._try("Remove boundary", lambda tg: tg.tiers[ti].remove_boundary(idx))
            self.select(ti, idx - 1)
        else:
            self._try("Remove point", lambda tg: tg.tiers[ti].remove_point(idx))
            self.selected_item = None
            self.item_selected.emit()

    def add_tier(self, kind: str = "interval", name: str | None = None, position: int | None = None):
        tg = self.doc.textgrid
        if tg is None:
            return
        if name is None:
            label = "interval" if kind == "interval" else "point"
            name, ok = QInputDialog.getText(self, f"Add {label} tier", "Tier name:")
            if not ok or not name.strip():
                return
            name = name.strip()
        pos = len(tg.tiers) if position is None else position
        cls = IntervalTier if kind == "interval" else PointTier
        self._try("Add tier", lambda g: g.tiers.insert(pos, cls(name, g.xmin, g.xmax)))
        self.selected_tier, self.selected_item = pos, None
        self._on_textgrid_changed()

    def rename_tier(self, index: int | None = None):
        index = self.selected_tier if index is None else index
        if not 0 <= index < len(self.tiers):
            return
        old = self.tiers[index].name
        name, ok = QInputDialog.getText(self, "Rename tier", "Tier name:", text=old)
        if ok and name.strip() and name != old:
            self._try("Rename tier", lambda g: setattr(g.tiers[index], "name", name.strip()))

    def duplicate_tier(self, index: int | None = None):
        index = self.selected_tier if index is None else index
        if not 0 <= index < len(self.tiers):
            return

        def duplicate(g):
            copy = deepcopy(g.tiers[index])
            copy.name = f"{copy.name}_copy"
            g.tiers.insert(index + 1, copy)

        self._try("Duplicate tier", duplicate)
        self.selected_tier, self.selected_item = index + 1, None
        self._on_textgrid_changed()

    def remove_tier(self, index: int | None = None):
        index = self.selected_tier if index is None else index
        if not 0 <= index < len(self.tiers):
            return
        name = self.tiers[index].name
        answer = QMessageBox.question(self, "Remove tier", f"Remove tier “{name}” and all its labels?")
        if answer == QMessageBox.StandardButton.Yes:
            self._try("Remove tier", lambda g: g.tiers.pop(index))
            self.selected_item = None
            self._on_textgrid_changed()

    def move_tier(self, index: int, step: int):
        j = index + step
        if 0 <= index < len(self.tiers) and 0 <= j < len(self.tiers):

            def swap(g):
                g.tiers[index], g.tiers[j] = g.tiers[j], g.tiers[index]

            self._try("Move tier", swap)
            self.selected_tier = j
            self.update()

    # ------------------------------------------------------------------ painting

    def paintEvent(self, ev):  # noqa: N802
        if not self.tiers:
            return
        p = QPainter(self)
        left, right = self.plot_area()
        w = self.width()
        v0, v1 = self.axis.view
        fm = QFontMetrics(self.label_font)
        p.fillRect(self.rect(), QColor(COLORS["background"]))

        for ti, tier in enumerate(self.tiers):
            top = ti * TIER_HEIGHT
            row = QRectF(left, top, right - left, TIER_HEIGHT)
            if ti == self.selected_tier:
                p.fillRect(QRectF(0, top, w, TIER_HEIGHT), QColor(*COLORS["tier_selected"]))
            p.setClipRect(row)
            if isinstance(tier, IntervalTier):
                self._paint_intervals(p, ti, tier, top, fm, v0, v1)
            else:
                self._paint_points(p, ti, tier, top, fm, v0, v1)
            p.setClipping(False)
            # Tier name in the left margin, kind marker in the right margin.
            p.setPen(QColor(COLORS["foreground"]))
            name_rect = QRectF(4, top, left - 8, TIER_HEIGHT)
            p.drawText(
                name_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                p.fontMetrics().elidedText(tier.name, Qt.TextElideMode.ElideRight, int(left - 8)),
            )
            p.setPen(QColor(COLORS["muted"]))
            p.drawText(
                QRectF(right + 4, top, w - right - 6, TIER_HEIGHT),
                Qt.AlignmentFlag.AlignVCenter,
                "intervals" if isinstance(tier, IntervalTier) else "points",
            )
            p.setPen(QPen(QColor(COLORS["muted"]), 1))
            p.drawLine(QPointF(0, top + TIER_HEIGHT), QPointF(w, top + TIER_HEIGHT))
        p.drawLine(QPointF(left, 0), QPointF(left, self.height()))
        p.drawLine(QPointF(right, 0), QPointF(right, self.height()))

        # Cursor, selection and playhead, matching the plot panes.
        if self.axis.selection:
            s0, s1 = self.axis.selection
            p.fillRect(QRectF(self._x(s0), 0, self._x(s1) - self._x(s0), self.height()), QColor(*COLORS["selection"]))
        if v0 <= self.axis.cursor <= v1:
            p.setPen(QPen(QColor(COLORS["cursor"]), 1, Qt.PenStyle.DashLine))
            x = self._x(self.axis.cursor)
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        if self.playhead is not None and v0 <= self.playhead <= v1:
            p.setPen(QPen(QColor(COLORS["playhead"]), 2))
            x = self._x(self.playhead)
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.end()

    def _paint_intervals(self, p, ti, tier: IntervalTier, top, fm, v0, v1):
        ivs = tier.intervals
        first = bisect.bisect_right(ivs, v0, key=lambda iv: iv.xmax)
        p.setFont(self.label_font)
        for i in range(first, len(ivs)):
            iv = ivs[i]
            if iv.xmin > v1:
                break
            x0, x1 = self._x(iv.xmin), self._x(iv.xmax)
            if ti == self.selected_tier and i == self.selected_item:
                p.fillRect(QRectF(x0, top, x1 - x0, TIER_HEIGHT), QColor(*COLORS["interval_selected"]))
            if iv.text and x1 - x0 > 6:
                p.setPen(QColor(COLORS["foreground"]))
                text = fm.elidedText(to_unicode(iv.text), Qt.TextElideMode.ElideRight, int(x1 - x0 - 4))
                p.drawText(QRectF(x0, top, x1 - x0, TIER_HEIGHT), Qt.AlignmentFlag.AlignCenter, text)
            if i > 0:
                hot = self._hover == (ti, i) or (self._drag and self._drag[:2] == (ti, i))
                p.setPen(QPen(QColor(COLORS["boundary_hover" if hot else "boundary"]), 3 if hot else 1.5))
                p.drawLine(QPointF(x0, top), QPointF(x0, top + TIER_HEIGHT))

    def _paint_points(self, p, ti, tier: PointTier, top, fm, v0, v1):
        p.setFont(self.label_font)
        mid = top + TIER_HEIGHT / 2
        first = bisect.bisect_left(tier.points, v0, key=lambda pt: pt.time)
        for i in range(first, len(tier.points)):
            pt = tier.points[i]
            if pt.time > v1:
                break
            x = self._x(pt.time)
            selected = ti == self.selected_tier and i == self.selected_item
            hot = selected or self._hover == (ti, i) or (self._drag and self._drag[:2] == (ti, i))
            p.setPen(QPen(QColor(COLORS["boundary_hover" if hot else "boundary"]), 3 if hot else 1.5))
            p.drawLine(QPointF(x, top), QPointF(x, top + TIER_HEIGHT * 0.3))
            p.drawLine(QPointF(x, top + TIER_HEIGHT * 0.7), QPointF(x, top + TIER_HEIGHT))
            if pt.mark:
                p.setPen(QColor(COLORS["foreground"]))
                p.drawText(QRectF(x - 60, mid - 10, 120, 20), Qt.AlignmentFlag.AlignCenter, to_unicode(pt.mark))

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, ev):  # noqa: N802
        ti = self._tier_at(ev.position().y())
        if ti is None or ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        self.setFocus()
        left, right = self.plot_area()
        x = ev.position().x()
        if not left <= x <= right:
            self.selected_tier, self.selected_item = ti, None
            self.update()
            self.item_selected.emit()
            return
        t = self._t(x)
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            sel = self.axis.selection or (self.axis.cursor, self.axis.cursor)
            near_start = abs(t - sel[0]) < abs(t - sel[1])
            self.axis.set_selection(t, sel[1]) if near_start else self.axis.set_selection(sel[0], t)
            return
        handle = self._handle_near(ti, t)
        tier = self.tiers[ti]
        if handle is not None:
            self._drag = (ti, handle, self.doc.begin_edit(), False)
            if isinstance(tier, PointTier):
                self.select(ti, handle)
            else:
                self.selected_tier = ti
            return
        if isinstance(tier, IntervalTier):
            self.select(ti, tier.interval_at(t))
            self.axis.set_cursor(t)
        else:
            self.selected_tier, self.selected_item = ti, None
            self.axis.clear_selection()
            self.axis.set_cursor(t)
            self.item_selected.emit()
        self.update()

    def mouseMoveEvent(self, ev):  # noqa: N802
        x = ev.position().x()
        t = self._t(x)
        if self._drag:
            ti, idx, snapshot, _ = self._drag
            tier = self.tiers[ti]
            t = self.axis.clamp(t)
            if isinstance(tier, IntervalTier):
                tier.move_boundary(idx, t)
            else:
                tier.move_point(idx, t)
            self._drag = (ti, idx, snapshot, True)
            self.update()
            return
        ti = self._tier_at(ev.position().y())
        hover = None
        if ti is not None:
            idx = self._handle_near(ti, t)
            hover = (ti, idx) if idx is not None else None
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.SplitHCursor if hover else Qt.CursorShape.ArrowCursor)
            self.update()
        self.axis.set_hover(t if ti is not None else None)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if not self._drag:
            return super().mouseReleaseEvent(ev)
        ti, idx, snapshot, moved = self._drag
        self._drag = None
        if moved:
            kind = "boundary" if isinstance(self.tiers[ti], IntervalTier) else "point"
            self.doc.commit_edit(f"Move {kind}", snapshot)
        if isinstance(self.tiers[ti], IntervalTier):
            self.select(ti, idx)
        self.update()

    def mouseDoubleClickEvent(self, ev):  # noqa: N802
        ti = self._tier_at(ev.position().y())
        left, right = self.plot_area()
        if ti is None or not left <= ev.position().x() <= right:
            return
        t = self._t(ev.position().x())
        if self._handle_near(ti, t) is None:
            self._add(ti, t)

    def leaveEvent(self, ev):  # noqa: N802
        self._hover = None
        self.axis.set_hover(None)
        self.update()

    def contextMenuEvent(self, ev):  # noqa: N802
        ti = self._tier_at(ev.pos().y())
        menu = QMenu(self)
        if ti is not None:
            t = self._t(ev.pos().x())
            self.selected_tier = ti
            menu.addAction(
                "Add boundary here" if isinstance(self.tiers[ti], IntervalTier) else "Add point here",
                lambda: self._add(ti, t),
            )
            menu.addSeparator()
            menu.addAction("Rename tier…", lambda: self.rename_tier(ti))
            menu.addAction("Duplicate tier", lambda: self.duplicate_tier(ti))
            menu.addAction("Move tier up", lambda: self.move_tier(ti, -1)).setEnabled(ti > 0)
            menu.addAction("Move tier down", lambda: self.move_tier(ti, 1)).setEnabled(ti < len(self.tiers) - 1)
            menu.addAction("Remove tier…", lambda: self.remove_tier(ti))
            menu.addSeparator()
        menu.addAction("Add interval tier…", lambda: self.add_tier("interval"))
        menu.addAction("Add point tier…", lambda: self.add_tier("point"))
        menu.exec(ev.globalPos())

    # ------------------------------------------------------------------ keyboard

    def keyPressEvent(self, ev):  # noqa: N802
        key, mods = ev.key(), ev.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.add_at_cursor()
        elif key == Qt.Key.Key_Delete or (key == Qt.Key.Key_Backspace and mods & Qt.KeyboardModifier.AltModifier):
            self.remove_near_cursor()
        elif key == Qt.Key.Key_Up and self.selected_tier > 0:
            self.selected_tier -= 1
            self.selected_item = None
            self.update()
            self.item_selected.emit()
        elif key == Qt.Key.Key_Down and self.selected_tier < len(self.tiers) - 1:
            self.selected_tier += 1
            self.selected_item = None
            self.update()
            self.item_selected.emit()
        elif key == Qt.Key.Key_Left and mods & Qt.KeyboardModifier.AltModifier:
            self.select_adjacent(-1)
        elif key == Qt.Key.Key_Right and mods & Qt.KeyboardModifier.AltModifier:
            self.select_adjacent(1)
        elif (
            ev.text()
            and ev.text().isprintable()
            and not mods & Qt.KeyboardModifier.ControlModifier
            and self.selected_item is not None
        ):
            self.type_text.emit(ev.text())
        else:
            super().keyPressEvent(ev)
