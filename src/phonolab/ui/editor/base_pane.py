"""Common machinery for time-aligned plot panes (waveform, spectrogram)."""

from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt

from phonolab.ui.editor.time_axis import TimeAxisController
from phonolab.ui.theme import COLORS

# Every pane reserves the same axis widths so their plot areas line up exactly.
LEFT_AXIS_WIDTH = 64
RIGHT_AXIS_WIDTH = 56
WHEEL_ZOOM = 0.8  # per wheel notch
WHEEL_SCROLL = 0.1  # fraction of the window per wheel notch


class TimeViewBox(pg.ViewBox):
    """ViewBox whose mouse gestures drive a TimeAxisController instead of panning."""

    def __init__(self, axis: TimeAxisController, **kwargs):
        super().__init__(enableMenu=False, **kwargs)
        self.axis = axis
        self.setMouseEnabled(x=False, y=False)

    def mouseClickEvent(self, ev):  # noqa: N802 - pyqtgraph API
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        t = self.mapSceneToView(ev.scenePos()).x()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._extend_selection(t)
        else:
            self.axis.clear_selection()
            self.axis.set_cursor(t)

    def _extend_selection(self, t: float):
        sel = self.axis.selection
        if sel is None:
            self.axis.set_selection(self.axis.cursor, t)
        elif abs(t - sel[0]) < abs(t - sel[1]):
            self.axis.set_selection(t, sel[1])
        else:
            self.axis.set_selection(sel[0], t)

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        t0 = self.mapSceneToView(ev.buttonDownScenePos()).x()
        t1 = self.mapSceneToView(ev.scenePos()).x()
        self.axis.set_selection(t0, t1)
        if ev.isFinish() and self.axis.selection:
            self.axis.set_cursor(self.axis.selection[0])

    def wheelEvent(self, ev, axis=None):  # noqa: N802
        notches = ev.delta() / 120
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            center = self.mapSceneToView(ev.scenePos()).x()
            self.axis.zoom(WHEEL_ZOOM**notches, center)
        else:
            self.axis.scroll(-notches * WHEEL_SCROLL)
        ev.accept()


class TimePane(pg.PlotWidget):
    """A plot whose x-axis follows the controller and shows cursor, selection and playhead."""

    frequency_axis = False  # hover reports y as Hz when True
    viewbox_class = TimeViewBox

    def __init__(self, axis: TimeAxisController, parent=None):
        self.axis = axis
        super().__init__(parent, viewBox=self.viewbox_class(axis))
        self.setBackground(COLORS["background"])
        plot = self.getPlotItem()
        plot.hideButtons()
        plot.setMenuEnabled(False)
        plot.showAxis("right")
        plot.getAxis("left").setWidth(LEFT_AXIS_WIDTH)
        plot.getAxis("right").setWidth(RIGHT_AXIS_WIDTH)
        plot.getAxis("right").setStyle(showValues=False)
        plot.getAxis("bottom").setStyle(showValues=False)
        plot.getAxis("bottom").setHeight(4)
        self.vb = plot.getViewBox()
        self.vb.disableAutoRange()

        self.selection_item = pg.LinearRegionItem(
            movable=False, brush=pg.mkBrush(COLORS["selection"]), pen=pg.mkPen(None)
        )
        self.selection_item.setZValue(-5)
        self.selection_item.hide()
        self.cursor_line = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen(COLORS["cursor"], width=1, style=Qt.PenStyle.DashLine)
        )
        self.playhead = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(COLORS["playhead"], width=2))
        self.playhead.hide()
        # Selection sits behind the data (but above the spectrogram image); lines on top.
        self.addItem(self.selection_item, ignoreBounds=True)
        for line in (self.cursor_line, self.playhead):
            line.setZValue(20)
            self.addItem(line, ignoreBounds=True)

        axis.view_changed.connect(self._on_view)
        axis.cursor_changed.connect(self.cursor_line.setPos)
        axis.selection_changed.connect(self._on_selection)
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._on_view(*axis.view)
        self.cursor_line.setPos(axis.cursor)

    def _on_view(self, start: float, end: float):
        self.vb.setXRange(start, end, padding=0)
        self.view_updated(start, end)

    def view_updated(self, start: float, end: float):
        """Hook for subclasses that re-render on view changes."""

    def _on_selection(self, sel):
        if sel is None:
            self.selection_item.hide()
        else:
            self.selection_item.setRegion(sel)
            self.selection_item.show()

    def set_playhead(self, t: float | None):
        if t is None:
            self.playhead.hide()
        else:
            self.playhead.setPos(t)
            self.playhead.show()

    def _on_mouse_moved(self, pos):
        if not self.vb.sceneBoundingRect().contains(pos):
            self.axis.set_hover(None)
            return
        p = self.vb.mapSceneToView(pos)
        self.axis.set_hover(p.x(), p.y() if self.frequency_axis else None)

    def leaveEvent(self, ev):  # noqa: N802
        self.axis.set_hover(None)
        super().leaveEvent(ev)

    def plot_area_x(self) -> tuple[int, int]:
        """Left and right pixel edges of the plot area, in this widget's coordinates."""
        rect = self.mapFromScene(self.vb.sceneBoundingRect()).boundingRect()
        return rect.left(), rect.right()
