"""The PhonoLab icon, drawn in code: a light-blue tile with a waveform."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0.0, QColor("#6fb1ea"))
    gradient.setColorAt(1.0, QColor("#2f6fb0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(tile, size * 0.22, size * 0.22)

    # A decaying waveform across the tile.
    path = QPainterPath()
    left, right = tile.left() + size * 0.14, tile.right() - size * 0.14
    mid = tile.center().y()
    steps = 120
    for i in range(steps + 1):
        x = left + (right - left) * i / steps
        phase = i / steps
        y = mid - math.sin(phase * math.pi * 5) * size * 0.26 * (1 - 0.65 * phase) * math.sin(phase * math.pi) ** 0.4
        if i == 0:
            path.moveTo(QPointF(x, y))
        else:
            path.lineTo(QPointF(x, y))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor("white"), max(1.5, size * 0.06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(path)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(render(size))
    return icon
