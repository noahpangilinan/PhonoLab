"""Welcome screen shown when no document is open."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phonolab.ui.icon import app_icon


class StartPage(QWidget):
    open_requested = pyqtSignal()
    open_path = pyqtSignal(str)
    record_requested = pyqtSignal()
    batch_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorPage")
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("startCard")
        card.setFixedWidth(560)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(10)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(56, 56))
        title = QLabel("PhonoLab")
        title.setObjectName("appTitle")
        title.setFont(QFont(self.font().family(), 30, QFont.Weight.Bold))
        header.addWidget(logo)
        header.addSpacing(8)
        header.addWidget(title)
        header.addStretch()
        subtitle = QLabel("Acoustic analysis and annotation for speech, powered by Praat")
        subtitle.setObjectName("muted")

        open_button = QPushButton("Open sound…")
        open_button.setObjectName("primary")
        open_button.setMinimumHeight(38)
        open_button.clicked.connect(self.open_requested)
        record_button = QPushButton("Record…")
        record_button.setMinimumHeight(38)
        record_button.clicked.connect(self.record_requested)
        batch_button = QPushButton("Batch measure…")
        batch_button.setMinimumHeight(38)
        batch_button.clicked.connect(self.batch_requested)
        actions = QHBoxLayout()
        actions.addWidget(open_button, 2)
        actions.addWidget(record_button, 1)
        actions.addWidget(batch_button, 1)

        hint = QLabel("Or drop sound files (WAV, FLAC, MP3, M4A…) and TextGrids anywhere in this window.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)

        self.recent_label = QLabel("RECENT FILES")
        self.recent_label.setObjectName("sectionTitle")
        self.recent = QListWidget()
        self.recent.setMinimumHeight(120)
        self.recent.setMaximumHeight(240)
        self.recent.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent.setWordWrap(False)
        self.recent.itemActivated.connect(lambda item: self.open_path.emit(item.data(Qt.ItemDataRole.UserRole)))

        layout.addLayout(header)
        layout.addWidget(subtitle)
        layout.addSpacing(14)
        layout.addLayout(actions)
        layout.addWidget(hint)
        layout.addSpacing(10)
        layout.addWidget(self.recent_label)
        layout.addWidget(self.recent)
        outer.addWidget(card)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for p in paths:
            item = QListWidgetItem(f"{Path(p).name}\n{Path(p).parent}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.recent.addItem(item)
        self.recent.setVisible(bool(paths))
        self.recent_label.setVisible(bool(paths))
