"""Welcome screen shown when no document is open."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from phonolab import __version__
from phonolab.ui.theme import COLORS, TOKENS

CONTENT_WIDTH = 820
ROW_HEIGHT = 50
VISIBLE_RECENT = 6  # more than this scrolls
WAVE_HEIGHT = 130
BAR_PITCH = 4  # px from one waveform bar to the next
TEXT_INSET = 10  # px; row text sits this far in, so hover backgrounds have room


def speech_envelope(n: int = 900) -> np.ndarray:
    """A fixed, speech-like amplitude contour: syllables of varying length and loudness, with pauses."""
    rng = np.random.default_rng(7)
    envelope = np.zeros(n)
    i = 12
    while i < n - 12:
        length = int(rng.integers(14, 46))
        loudness = rng.uniform(0.35, 1.0)
        window = np.sin(np.linspace(0, np.pi, length)) ** 0.7
        envelope[i : i + length] = loudness * window[: len(envelope[i : i + length])]
        i += length + int(rng.integers(2, 10))
        if rng.random() < 0.16:  # a pause between phrases
            i += int(rng.integers(25, 60))
    texture = 0.72 + 0.28 * rng.random(n)  # bars of a real waveform never line up smoothly
    return envelope * texture


class SpeechWave(QWidget):
    """A quiet waveform along the bottom of the page. Colours are read as it paints, so it follows the theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.envelope = speech_envelope()
        self.setFixedHeight(WAVE_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, ev):  # noqa: N802
        p = QPainter(self)
        colour = QColor(COLORS["voiced"])
        colour.setAlpha(150)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2
        reach = mid - 6
        for k, x in enumerate(range(0, self.width(), BAR_PITCH)):
            half = max(float(self.envelope[k % len(self.envelope)]) * reach, 1.0)
            p.drawRoundedRect(QRectF(x, mid - half, 2, 2 * half), 1, 1)
        p.end()


class ActionRow(QPushButton):
    """A flat row: what it does on the left, its keyboard shortcut on the right."""

    def __init__(self, text: str, shortcut: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("startAction")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(TEXT_INSET, 0, TEXT_INSET, 0)
        label = QLabel(text)
        label.setObjectName("startActionLabel")
        keys = QLabel(shortcut)
        keys.setObjectName("muted")
        for w in (label, keys):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(label)
        row.addStretch()
        row.addWidget(keys)


class RecentDelegate(QStyledItemDelegate):
    """File name above its folder, with the date it was last changed on the right."""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, p, option, index):
        path = Path(index.data(Qt.ItemDataRole.UserRole))
        rect = QRectF(option.rect)
        p.save()
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TOKENS["accent_soft"]))
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawRoundedRect(rect, 6, 6)
        exists = path.exists()
        date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %Y").lstrip("0") if exists else "Missing"
        name_font = QFont(option.font)
        name_font.setWeight(QFont.Weight.DemiBold)
        muted = QColor(TOKENS["text_muted"])
        text_rect = rect.adjusted(TEXT_INSET, 6, -TEXT_INSET, -6)
        p.setFont(option.font)
        date_width = p.fontMetrics().horizontalAdvance(date) + 16
        p.setPen(muted)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, date)
        left = text_rect.adjusted(0, 0, -date_width, 0)
        folder = p.fontMetrics().elidedText(str(path.parent), Qt.TextElideMode.ElideMiddle, int(left.width()))
        p.drawText(left, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, folder)
        p.setFont(name_font)
        p.setPen(QColor(TOKENS["text"]) if exists else muted)
        name = p.fontMetrics().elidedText(path.name, Qt.TextElideMode.ElideRight, int(left.width()))
        p.drawText(left, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
        p.restore()


class StartPage(QWidget):
    open_requested = pyqtSignal()
    open_path = pyqtSignal(str)
    record_requested = pyqtSignal()
    batch_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorPage")

        title = QLabel("PhonoLab")
        title.setObjectName("appTitle")
        title.setFont(QFont(self.font().family(), 26, QFont.Weight.DemiBold))
        title.setContentsMargins(TEXT_INSET, 0, 0, 0)  # lines up with the text in the rows below

        actions = QVBoxLayout()
        actions.setSpacing(2)
        for text, shortcut, signal in (
            ("Open sound…", "Ctrl+O", self.open_requested),
            ("Record…", "Ctrl+R", self.record_requested),
            ("Batch measure…", "Ctrl+B", self.batch_requested),
        ):
            row = ActionRow(text, shortcut)
            row.clicked.connect(signal)
            actions.addWidget(row)

        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(title)
        left.addSpacing(26)
        left.addLayout(actions)
        left.addStretch(1)

        self.recent_label = QLabel("Recent")
        self.recent_label.setObjectName("sectionTitle")
        self.recent_label.setContentsMargins(TEXT_INSET, 0, 0, 0)
        self.recent = QListWidget()
        self.recent.setObjectName("recentList")
        self.recent.setFrameShape(QFrame.Shape.NoFrame)
        self.recent.setItemDelegate(RecentDelegate(self.recent))
        self.recent.setMouseTracking(True)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.recent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent.itemClicked.connect(self._open_item)
        self.recent.itemActivated.connect(self._open_item)
        self.empty_hint = QLabel("Files you open will appear here. You can also drop them anywhere in this window.")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setContentsMargins(TEXT_INSET, 0, 0, 0)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addSpacing(12)
        right.addWidget(self.recent_label)
        right.addWidget(self.recent)
        right.addWidget(self.empty_hint)
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.setSpacing(56)
        columns.addLayout(left, 4)
        columns.addLayout(right, 7)
        content = QWidget()
        content.setMaximumWidth(CONTENT_WIDTH)
        content.setLayout(columns)
        centred = QHBoxLayout()
        centred.setContentsMargins(32, 0, 32, 0)
        centred.addStretch(1)
        centred.addWidget(content, 40)
        centred.addStretch(1)

        version = QLabel(__version__)
        version.setObjectName("muted")
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 14, 6)
        footer.addStretch()
        footer.addWidget(version)

        page = QVBoxLayout(self)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addStretch(3)
        page.addLayout(centred)
        page.addStretch(4)
        page.addWidget(SpeechWave())
        page.addLayout(footer)

    def _open_item(self, item: QListWidgetItem):
        self.open_path.emit(item.data(Qt.ItemDataRole.UserRole))

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for p in paths:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.recent.addItem(item)
        self.recent.setFixedHeight(min(len(paths), VISIBLE_RECENT) * ROW_HEIGHT + 2)
        self.recent.setVisible(bool(paths))
        self.empty_hint.setVisible(not paths)
