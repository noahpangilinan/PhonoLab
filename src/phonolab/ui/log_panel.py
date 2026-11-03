"""The "Info" dock: query results accumulate here, ready to copy (Praat's Info window)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogPanel(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Results", parent)
        self.setObjectName("results_dock")
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setPlaceholderText("Query results appear here.\nTry F5 (pitch), F1 (formants) or F8 (intensity).")
        buttons = QHBoxLayout()
        copy = QPushButton("Copy all")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        clear = QPushButton("Clear")
        clear.clicked.connect(self.text.clear)
        buttons.addStretch()
        buttons.addWidget(copy)
        buttons.addWidget(clear)
        layout.addWidget(self.text)
        layout.addLayout(buttons)
        self.setWidget(body)

    def append(self, message: str) -> None:
        self.text.appendPlainText(message)
        if not self.isVisible():
            self.show()
            if (window := self.parent()) is not None:
                window.resizeDocks([self], [160], Qt.Orientation.Vertical)
        self.raise_()
