"""Welcome screen shown when no document is open."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget


class StartPage(QWidget):
    open_requested = pyqtSignal()
    open_path = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title = QLabel("PhonoLab")
        title.setFont(QFont(self.font().family(), 40, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Acoustic analysis and annotation for speech")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7b8794;")
        hint = QLabel("Drop a sound file (WAV, FLAC, AIFF, MP3) or a TextGrid anywhere in this window")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #7b8794;")

        open_button = QPushButton("Open sound…")
        open_button.setMinimumSize(220, 44)
        open_button.setDefault(True)
        open_button.clicked.connect(self.open_requested)

        self.recent_label = QLabel("Recent files")
        self.recent_label.setStyleSheet("font-weight: bold; margin-top: 16px;")
        self.recent = QListWidget()
        self.recent.setMaximumSize(520, 220)
        self.recent.itemActivated.connect(lambda item: self.open_path.emit(item.data(Qt.ItemDataRole.UserRole)))

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addWidget(self.recent_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.recent, alignment=Qt.AlignmentFlag.AlignCenter)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for p in paths:
            item = QListWidgetItem(f"{Path(p).name}    —    {Path(p).parent}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.recent.addItem(item)
        self.recent.setVisible(bool(paths))
        self.recent_label.setVisible(bool(paths))
