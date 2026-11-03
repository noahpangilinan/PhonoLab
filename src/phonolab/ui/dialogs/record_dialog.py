"""Record from a microphone into a new sound."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from phonolab.core.sound import Sound

try:
    import sounddevice as sd
except OSError:  # PortAudio missing
    sd = None

log = logging.getLogger(__name__)

SAMPLING_RATES = (44100, 48000, 22050, 16000, 96000)


class RecordingBuffer:
    """Thread-safe accumulation of input blocks; tracks the recent peak for the level meter."""

    def __init__(self, channels: int):
        self.channels = channels
        self._blocks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self.peak = 0.0
        self.clipped = False

    def add(self, block: np.ndarray) -> None:
        with self._lock:
            self._blocks.append(block.copy())
        level = float(np.max(np.abs(block))) if block.size else 0.0
        self.peak = level
        self.clipped = self.clipped or level >= 0.999

    @property
    def n_frames(self) -> int:
        with self._lock:
            return sum(len(b) for b in self._blocks)

    def samples(self) -> np.ndarray:
        with self._lock:
            if not self._blocks:
                return np.zeros((0, self.channels))
            return np.concatenate(self._blocks).astype(np.float64)


class RecordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record sound")
        self.stream = None
        self.buffer: RecordingBuffer | None = None
        self.sound: Sound | None = None

        self.device = QComboBox()
        self.rate = QComboBox()
        for sr in SAMPLING_RATES:
            self.rate.addItem(f"{sr} Hz", sr)
        self.channels = QComboBox()
        self.channels.addItem("Mono", 1)
        self.channels.addItem("Stereo", 2)
        if sd is not None:
            default_in = sd.default.device[0]
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    self.device.addItem(dev["name"], i)
                    if i == default_in:
                        self.device.setCurrentIndex(self.device.count() - 1)

        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.elapsed = QLabel("0.0 s")
        self.status = QLabel("" if sd is not None and self.device.count() else "No input device found.")
        self.status.setStyleSheet("color: #d62728;")

        self.record_button = QPushButton("● Record")
        self.record_button.clicked.connect(self.toggle)
        self.record_button.setEnabled(sd is not None and self.device.count() > 0)

        form = QFormLayout()
        form.addRow("Input:", self.device)
        form.addRow("Sampling frequency:", self.rate)
        form.addRow("Channels:", self.channels)
        form.addRow("Level:", self.meter)
        form.addRow("Recorded:", self.elapsed)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Open recording")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.record_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

        self._timer = QTimer(self, interval=50)
        self._timer.timeout.connect(self._tick)
        self._started = 0.0

    def toggle(self):
        if self.stream is None:
            self.start()
        else:
            self.stop()

    def start(self):
        channels, sr = self.channels.currentData(), self.rate.currentData()
        self.buffer = buffer = RecordingBuffer(channels)

        def callback(indata, _frames, _time, status):
            if status:
                log.debug("recording status: %s", status)
            buffer.add(indata)

        try:
            self.stream = sd.InputStream(
                device=self.device.currentData(), channels=channels, samplerate=sr, dtype="float32",
                callback=callback,
            )  # fmt: skip
            self.stream.start()
        except Exception as e:  # PortAudioError: unsupported rate/channels, device busy…
            self.stream = None
            self.status.setText(f"Could not start recording: {e}")
            return
        self.status.setText("")
        self._started = time.monotonic()
        self._timer.start()
        self.record_button.setText("■ Stop")
        for w in (self.device, self.rate, self.channels):
            w.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self._timer.stop()
        self.meter.setValue(0)
        self.record_button.setText("● Record again")
        for w in (self.device, self.rate, self.channels):
            w.setEnabled(True)
        samples = self.buffer.samples() if self.buffer else np.zeros((0, 1))
        if len(samples):
            self.sound = Sound(samples, float(self.rate.currentData()), title=f"recording_{time.strftime('%H%M%S')}")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            if self.buffer.clipped:
                self.status.setText("The recording clipped: lower the input level and record again.")

    def _tick(self):
        if self.buffer is None:
            return
        self.meter.setValue(int(min(1.0, self.buffer.peak) * 100))
        self.elapsed.setText(f"{time.monotonic() - self._started:.1f} s")

    def reject(self):
        self.stop()
        super().reject()

    def accept(self):
        self.stop()
        super().accept()
