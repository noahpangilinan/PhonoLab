"""A settings form generated from an analysis settings dataclass."""

from __future__ import annotations

import dataclasses
from enum import Enum

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# Spin-box step per number of decimals (Hz-like values step by 1, ratios by 0.01).
_STEPS = {1: 0.5, 2: 1.0, 3: 0.01, 4: 0.001}


class SettingsForm(QWidget):
    """One editor per dataclass field; emits ``changed`` whenever any value changes."""

    changed = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.cls = type(settings)
        self.editors = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        for f in dataclasses.fields(self.cls):
            editor = self._make_editor(f)
            self.editors[f.name] = editor
            form.addRow(f.metadata.get("label", f.name) + ":", editor)
        self.load(settings)

    def _make_editor(self, f):
        meta, default = f.metadata, f.default
        if isinstance(default, bool):
            box = QCheckBox()
            box.toggled.connect(self.changed)
            return box
        if isinstance(default, Enum) or "choices" in meta:
            box = QComboBox()
            for choice in type(default) if isinstance(default, Enum) else meta["choices"]:
                box.addItem(choice.value if isinstance(choice, Enum) else choice, choice)
            box.currentIndexChanged.connect(self.changed)
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
        box.valueChanged.connect(self.changed)
        return box

    def load(self, settings):
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


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.form = SettingsForm(settings)
        self.setWindowTitle(f"{self.form.cls.title} settings")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setToolTip("Restore Praat's standard values")
        restore.clicked.connect(lambda: self.form.load(self.form.cls()))
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        layout.addWidget(buttons)

    def value(self):
        return self.form.value()
