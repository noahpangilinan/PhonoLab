"""Clickable IPA chart for inserting symbols into labels."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QToolButton, QVBoxLayout

from phonolab.core.ipa import to_trigraphs

# Laid out roughly like the IPA chart. Combining diacritics are shown on a dotted circle.
GROUPS = [
    ("Vowels", "i y ɨ ʉ ɯ u ɪ ʏ ʊ e ø ɘ ɵ ɤ o ə ɛ œ ɜ ɞ ʌ ɔ æ ɐ a ɶ ɑ ɒ ɚ ɝ"),
    ("Plosives & nasals", "p b t d ʈ ɖ c ɟ k ɡ q ɢ ʔ m ɱ n ɳ ɲ ŋ ɴ"),
    ("Fricatives", "ɸ β f v θ ð s z ʃ ʒ ʂ ʐ ç ʝ x ɣ χ ʁ ħ ʕ h ɦ ɬ ɮ"),
    ("Approximants & others", "ʋ ɹ ɻ j ɰ l ɭ ʎ ʟ ʙ r ʀ ⱱ ɾ ɽ w ʍ ɥ ʜ ʢ ɕ ʑ ɺ ɧ"),
    ("Clicks & implosives", "ʘ ǀ ǃ ǂ ǁ ɓ ɗ ʄ ɠ ʛ"),
    ("Suprasegmentals", "ˈ ˌ ː ˑ ̆ | ‖ . ‿ ↗ ↘"),
    ("Diacritics", "̥ ̬ ʰ ̹ ̜ ̟ ̠ ̈ ̽ ̩ ̯ ˞ ̤ ̰ ̼ ʷ ʲ ˠ ˤ ̴ ̝ ̞ ̘ ̙ ̪ ̺ ̻ ̃ ⁿ ˡ ̚"),
]
COLUMNS = 12


def _is_combining(ch: str) -> bool:
    return 0x0300 <= ord(ch) <= 0x036F


class IpaPalette(QFrame):
    """Popup grid of IPA symbols; emits the symbol clicked."""

    symbol_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 1.4)
        for title, symbols in GROUPS:
            header = QLabel(title)
            header.setStyleSheet("font-weight: bold; margin-top: 4px;")
            layout.addWidget(header)
            grid = QGridLayout()
            grid.setSpacing(2)
            for i, sym in enumerate(symbols.split()):
                button = QToolButton()
                button.setText("◌" + sym if _is_combining(sym) else sym)
                button.setFont(font)
                button.setAutoRaise(True)
                button.setFixedSize(34, 34)
                code = to_trigraphs(sym)
                tip = f"U+{ord(sym[0]):04X}" + (f"   Praat: {code}" if code != sym else "")
                button.setToolTip(tip)
                button.clicked.connect(lambda _=False, s=sym: self.symbol_chosen.emit(s))
                grid.addWidget(button, i // COLUMNS, i % COLUMNS)
            layout.addLayout(grid)
