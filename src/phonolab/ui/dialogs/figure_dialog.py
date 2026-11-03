"""Compose a publication figure of the current sound and export it as SVG, PDF or PNG."""

from __future__ import annotations

import io
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from phonolab.core import figures
from phonolab.core.figures import FigureRequest, FigureSettings
from phonolab.ui.dialogs.settings_dialog import SettingsForm

PREVIEW_DPI = 90
PREVIEW_DELAY_MS = 300
PANEL_LABELS = {"waveform": "Waveform", "spectrogram": "Spectrogram", "pitch": "Pitch contour", "textgrid": "TextGrid"}


class FigureDialog(QDialog):
    def __init__(self, editor, settings: FigureSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Figure — {editor.doc.sound.name}")
        self.resize(1100, 720)
        self.editor = editor
        self.figure = None
        doc = editor.doc

        panels_box = QGroupBox("Panels")
        panels_layout = QVBoxLayout(panels_box)
        self.panel_checks = {}
        for key, label in PANEL_LABELS.items():
            box = QCheckBox(label)
            box.setChecked(key in ("waveform", "spectrogram") or (key == "textgrid" and doc.textgrid is not None))
            box.setEnabled(key != "textgrid" or doc.textgrid is not None)
            box.toggled.connect(self.schedule_preview)
            panels_layout.addWidget(box)
            self.panel_checks[key] = box
        self.tier_list = QListWidget()
        self.tier_list.setMaximumHeight(90)
        for tier in doc.textgrid.tiers if doc.textgrid else []:
            item = QListWidgetItem(tier.name)
            item.setCheckState(Qt.CheckState.Checked)
            self.tier_list.addItem(item)
        self.tier_list.itemChanged.connect(self.schedule_preview)
        self.tier_list.setVisible(self.tier_list.count() > 0)
        panels_layout.addWidget(self.tier_list)

        range_box = QGroupBox("Time range")
        range_layout = QVBoxLayout(range_box)
        self.range_group = QButtonGroup(self)
        axis = editor.axis
        options = [("selection", "Selection", axis.selection), ("view", "Visible window", axis.view),
                   ("all", "Whole sound", (0.0, doc.sound.duration))]  # fmt: skip
        for key, label, rng in options:
            button = QRadioButton(f"{label} ({rng[0]:.3f}–{rng[1]:.3f} s)" if rng else f"{label} (none)")
            button.setEnabled(rng is not None)
            button.setProperty("range", rng)
            self.range_group.addButton(button)
            range_layout.addWidget(button)
            if key == ("selection" if axis.selection else "view"):
                button.setChecked(True)
        self.range_group.buttonToggled.connect(self.schedule_preview)

        self.form = SettingsForm(settings)
        self.form.changed.connect(self.schedule_preview)
        style_box = QGroupBox("Style")
        QVBoxLayout(style_box).addWidget(self.form)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        for w in (panels_box, range_box, style_box):
            left_layout.addWidget(w)
        left_layout.addStretch()
        left_scroll = QScrollArea()
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(360)

        self.preview = QLabel("Rendering…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: white; border: 1px solid #ccc;")
        preview_scroll = QScrollArea()
        preview_scroll.setWidget(self.preview)
        preview_scroll.setWidgetResizable(True)

        save = QPushButton("Save as…")
        save.setDefault(True)
        save.clicked.connect(self.save_as)
        copy = QPushButton("Copy image")
        copy.clicked.connect(self.copy_image)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        self.status = QLabel()
        self.status.setStyleSheet("color: #d62728;")
        buttons.addWidget(self.status, 1)
        for b in (copy, save, close):
            buttons.addWidget(b)

        body = QHBoxLayout()
        body.addWidget(left_scroll)
        body.addWidget(preview_scroll, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

        self._timer = QTimer(self, singleShot=True, interval=PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self.render_preview)
        self.schedule_preview()

    # ------------------------------------------------------------------ request

    def request(self) -> FigureRequest:
        start, end = self.range_group.checkedButton().property("range")
        panels = tuple(k for k, box in self.panel_checks.items() if box.isChecked() and box.isEnabled())
        tiers = tuple(
            self.tier_list.item(i).text()
            for i in range(self.tier_list.count())
            if self.tier_list.item(i).checkState() == Qt.CheckState.Checked
        )
        m = self.editor.manager.settings
        return FigureRequest(
            panels, start, end, tiers, self.form.value(),
            m["spectrogram"], m["pitch"], m["formants"], m["intensity"],
        )  # fmt: skip

    def settings(self) -> FigureSettings:
        return self.form.value()

    # ------------------------------------------------------------------ rendering

    def schedule_preview(self, *_):
        self._timer.start()

    def render_preview(self) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            doc = self.editor.doc
            self.figure = figures.make_figure(doc.sound, doc.textgrid, self.request())
            buffer = io.BytesIO()
            self.figure.savefig(buffer, format="png", dpi=PREVIEW_DPI)
        except Exception as e:  # e.g. nothing to draw, a range too short for analysis
            self.figure = None
            self.status.setText(str(e))
            self.preview.setText("No preview")
            return False
        finally:
            QApplication.restoreOverrideCursor()
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue(), "PNG")
        self.preview.setPixmap(pixmap)
        self.status.setText("")
        return True

    def save_as(self):
        if self.figure is None and not self.render_preview():
            return
        sound = self.editor.doc.sound
        default = sound.path.with_suffix(".pdf") if sound.path else Path(f"{sound.name}.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save figure", str(default), "PDF (*.pdf);;SVG (*.svg);;PNG image (*.png)"
        )
        if path:
            self.save(Path(path))

    def save(self, path: Path):
        try:
            figures.save_figure(self.figure, path, dpi=self.settings().dpi)
        except Exception as e:  # unwritable location, unsupported extension
            self.status.setText(f"Could not save: {e}")
            return
        self.status.setText("")
        self.setWindowTitle(f"Figure — saved {path.name}")

    def copy_image(self):
        if self.figure is None and not self.render_preview():
            return
        buffer = io.BytesIO()
        self.figure.savefig(buffer, format="png", dpi=self.settings().dpi)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue(), "PNG")
        QApplication.clipboard().setPixmap(pixmap)
        self.setWindowTitle("Figure — copied to clipboard")
