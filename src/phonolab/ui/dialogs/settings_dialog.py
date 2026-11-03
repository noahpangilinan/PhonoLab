"""A settings form generated from an analysis settings dataclass."""

from __future__ import annotations

import dataclasses
from enum import Enum

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

# Spin-box step per number of decimals (Hz-like values step by 1, ratios by 0.01).
_STEPS = {1: 0.5, 2: 1.0, 3: 0.01, 4: 0.001}


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.cls = type(settings)
        self.setWindowTitle(f"{self.cls.title} settings")
        self.editors = {}
        form = QFormLayout()
        for f in dataclasses.fields(self.cls):
            editor = self._make_editor(f)
            self.editors[f.name] = editor
            form.addRow(f.metadata.get("label", f.name) + ":", editor)
        self._load(settings)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setToolTip("Restore Praat's standard values")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda: self._load(self.cls()))
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _make_editor(f):
        meta, default = f.metadata, f.default
        if isinstance(default, bool):
            return QCheckBox()
        if isinstance(default, Enum):
            box = QComboBox()
            for member in type(default):
                box.addItem(member.value, member)
            return box
        if "choices" in meta:
            box = QComboBox()
            for choice in meta["choices"]:
                box.addItem(choice, choice)
            return box
        box = QSpinBox() if isinstance(default, int) else QDoubleSpinBox()
        if isinstance(box, QDoubleSpinBox):
            decimals = meta.get("decimals", 2)
            box.setDecimals(decimals)
            box.setSingleStep(_STEPS.get(decimals, 1.0))
        lo, hi = meta.get("min"), meta.get("max")
        box.setRange(lo if lo is not None else -1e9, hi if hi is not None else 1e9)
        if meta.get("unit"):
            box.setSuffix(" " + meta["unit"])
        return box

    def _load(self, settings):
        for name, editor in self.editors.items():
            value = getattr(settings, name)
            if isinstance(editor, QCheckBox):
                editor.setChecked(value)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(value)))
            else:
                editor.setValue(value)

    def value(self):
        kwargs = {}
        for name, editor in self.editors.items():
            if isinstance(editor, QCheckBox):
                kwargs[name] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                kwargs[name] = editor.currentData()
            else:
                kwargs[name] = editor.value()
        return self.cls(**kwargs)
