"""Dialog for creating a TextGrid for the current sound."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


class NewTextGridDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New TextGrid")
        self.interval_tiers = QLineEdit("words phones")
        self.point_tiers = QLineEdit("")
        self.point_tiers.setPlaceholderText("e.g. tones events")
        form = QFormLayout()
        form.addRow("Interval tiers:", self.interval_tiers)
        form.addRow("Point tiers:", self.point_tiers)
        note = QLabel("Separate tier names with spaces. You can add, rename and remove tiers later.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #7b8794;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def tier_names(self) -> tuple[list[str], list[str]]:
        return self.interval_tiers.text().split(), self.point_tiers.text().split()
