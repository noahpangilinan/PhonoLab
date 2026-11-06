"""Dialog for synthesizing speech with eSpeak."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from phonolab.core import speech


class SpeechDialog(QDialog):
    def __init__(self, language: str, voice: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Synthesize speech")
        self.resize(460, 280)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Type what to say")
        self.language = QComboBox()
        self.language.addItems(speech.LANGUAGES)
        self.language.setCurrentText(language)
        self.voice = QComboBox()
        self.voice.addItems(speech.VOICES)
        self.voice.setCurrentText(voice)
        self.rate = QSpinBox(minimum=80, maximum=450, value=175, suffix=" words per minute")
        form = QFormLayout()
        form.addRow("Language", self.language)
        form.addRow("Voice", self.voice)
        form.addRow("Speed", self.rate)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(form)
        layout.addWidget(buttons)
