"""The Sound + TextGrid editor shown in each document tab."""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QScrollBar,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from phonolab.audio.player import AudioPlayer
from phonolab.core import formant_path, manipulation, praat_engine, queries, registry, speech, voice
from phonolab.core.ipa import to_unicode
from phonolab.core.manipulation import ManipulationSettings
from phonolab.core.queries import fmt
from phonolab.core.settings import Preferences
from phonolab.core.sound import LongSoundError, Sound
from phonolab.core.textgrid import IntervalTier, TextGrid, TextGridError
from phonolab.ui.document import Document
from phonolab.ui.editor.base_pane import LEFT_AXIS_WIDTH, RIGHT_AXIS_WIDTH
from phonolab.ui.editor.find_bar import FindBar
from phonolab.ui.editor.manipulation_pane import ManipulationPane
from phonolab.ui.editor.spectrogram_pane import SpectrogramPane
from phonolab.ui.editor.textgrid_pane import TextGridView
from phonolab.ui.editor.time_axis import TimeAxisController
from phonolab.ui.editor.voicing_bar import VoicingBar
from phonolab.ui.editor.waveform_pane import Envelope, WaveformPane
from phonolab.ui.ipa_palette import IpaPalette
from phonolab.ui.manipulation import ManipulationState
from phonolab.ui.theme import COLORS, style_plot
from phonolab.ui.workers import ZOOM_HINT, AnalysisManager

PLAYHEAD_INTERVAL_MS = 16
EXTRACT_FIRST = "Long recordings can't do this as a whole: select a part and use Sound > Extract selection"
LAYERS = ("waveform", "spectrogram", "pitch", "formants", "intensity", "voicing", "pulses", "manipulation")
# Layers hidden until the user turns them on (like Praat, which hides pulses by default).
HIDDEN_BY_DEFAULT = {"pulses", "manipulation"}
# Layers whose visibility lives in preferences rather than in the spectrogram pane.
STANDALONE_LAYERS = ("waveform", "voicing", "pulses", "manipulation")


def _reports_long_sound_limits(method):
    """Turn a long sound's limits into a status-bar message, for commands run straight from a menu."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except LongSoundError as e:
            self.message.emit(str(e))
            return None

    return wrapper


class _OverviewBox(pg.ViewBox):
    def __init__(self, axis: TimeAxisController):
        super().__init__(enableMenu=False)
        self.axis = axis
        self.setMouseEnabled(x=False, y=False)

    def _center_on(self, ev):
        t = self.mapSceneToView(ev.scenePos()).x()
        v0, v1 = self.axis.view
        self.axis.set_view(t - (v1 - v0) / 2, t + (v1 - v0) / 2)

    def mouseClickEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self._center_on(ev)

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self._center_on(ev)

    def wheelEvent(self, ev, axis=None):  # noqa: N802
        ev.accept()


@dataclass(frozen=True)
class SoundClip:
    """Audio on PhonoLab's clipboard, shared by every open sound."""

    samples: np.ndarray  # (samples, channels)
    sampling_rate: float

    def problem_with(self, sound: Sound) -> str | None:
        """Why this can't go into ``sound``. Converting silently would change the data, so say so instead."""
        if sound.is_long:
            return EXTRACT_FIRST
        if self.sampling_rate != sound.sampling_rate:
            return (
                f"The copied sound is {self.sampling_rate:g} Hz and this one is {sound.sampling_rate:g} Hz: "
                "use Sound > Resample first"
            )
        if self.samples.shape[1] != sound.n_channels:
            return (
                f"The copied sound has {self.samples.shape[1]} channel(s) and this one has {sound.n_channels}: "
                "use Sound > Convert to mono first"
            )
        return None


class OverviewStrip(pg.PlotWidget):
    """Whole-file waveform with a box marking the visible window; click or drag to navigate."""

    def __init__(self, axis: TimeAxisController, sound, parent=None):
        super().__init__(parent, viewBox=_OverviewBox(axis))
        self.axis = axis
        self.setFixedHeight(46)
        plot = self.getPlotItem()
        plot.hideButtons()
        plot.setMenuEnabled(False)
        for side in ("left", "right"):
            plot.showAxis(side)
            plot.getAxis(side).setStyle(showValues=False)
        plot.getAxis("left").setWidth(LEFT_AXIS_WIDTH)
        plot.getAxis("right").setWidth(RIGHT_AXIS_WIDTH)
        plot.getAxis("bottom").setStyle(showValues=False)
        plot.getAxis("bottom").setHeight(2)
        if sound.is_long:
            lows, highs = sound.block_envelope
            envelope = Envelope(sound.samples[:, 0], sound.sampling_rate, (lows.min(axis=1), highs.max(axis=1)))
        else:
            envelope = Envelope(sound.mono, sound.sampling_rate)
        self.curve = plot.plot(pen=pg.mkPen(COLORS["muted"]))
        self._draw(envelope, sound)
        self.window_box = pg.LinearRegionItem(
            movable=False, brush=self._window_brush(), pen=pg.mkPen(COLORS["playhead"])
        )
        self.addItem(self.window_box)
        axis.view_changed.connect(lambda a, b: self.window_box.setRegion((a, b)))
        self.window_box.setRegion(axis.view)

    def _draw(self, envelope: Envelope, sound):
        self.curve.setData(*envelope.render(0, sound.duration, 1500))
        peak = sound.peak or 1.0
        self.getPlotItem().getViewBox().setRange(xRange=(0, sound.duration), yRange=(-peak, peak), padding=0)

    def set_sound(self, sound):
        self._draw(Envelope(sound.mono, sound.sampling_rate), sound)

    @staticmethod
    def _window_brush():
        colour = QColor(COLORS["playhead"])
        colour.setAlpha(50)
        return pg.mkBrush(colour)

    def retheme(self):
        style_plot(self)
        self.curve.setPen(pg.mkPen(COLORS["muted"]))
        self.window_box.setBrush(self._window_brush())
        for line in self.window_box.lines:
            line.setPen(pg.mkPen(COLORS["playhead"]))


class SoundEditor(QWidget):
    message = pyqtSignal(str)  # transient status-bar text
    log = pyqtSignal(str)  # query results for the Results dock
    busy_changed = pyqtSignal(str, bool)
    new_sound = pyqtSignal(object)  # a Sound to open in a new tab (e.g. a resynthesis)
    formant_path_ready = pyqtSignal(object)  # a FormantPathResult to show

    def __init__(self, doc: Document, prefs: Preferences, player: AudioPlayer, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.prefs = prefs
        self.player = player
        sound = doc.sound
        self.axis = TimeAxisController(sound.duration, self)
        self.manager = AnalysisManager(
            doc.analysis_sound, {name: prefs.analysis_settings(name) for name in registry.ANALYSES}, self
        )
        self.muted: set[int] = set()
        self.manager.busy_changed.connect(self.busy_changed)
        self.manager.error.connect(lambda name, msg: self.message.emit(f"{name.title()} failed: {msg}"))

        self.overview = OverviewStrip(self.axis, sound)
        self.waveform = WaveformPane(self.axis, sound)
        self.manager.corrections = doc.corrections
        doc.corrections_changed.connect(lambda: self.manager.set_corrections(doc.corrections))
        self.manager.result_ready.connect(self._on_result)
        self.manager.window_changed.connect(self._on_window_changed)
        self.spectrogram = SpectrogramPane(self.axis, self.manager)
        self.manipulation_pane = ManipulationPane(self.axis)
        self.manipulation_pane.message.connect(self.message)
        self.manipulation_settings = prefs.analysis_settings("manipulation", ManipulationSettings)
        self.manager.job_done.connect(self._on_job_done)
        self.manager.job_failed.connect(self._on_job_failed)
        self._resynthesis = None  # (pitch, duration, gain, samples, sr) of the latest resynthesis
        self._after_resynthesis = None  # what to do when the pending resynthesis arrives
        self._resynthesis_tiers = None  # (pitch, duration, gain) submitted for the pending resynthesis
        self._aligning = None  # name of the tier whose alignment is running
        self.panes = [self.waveform, self.spectrogram, self.manipulation_pane]
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.waveform)
        self.splitter.addWidget(self.spectrogram)
        self.splitter.addWidget(self.manipulation_pane)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Select an interval or point to type its label")
        self.label_edit.setClearButtonEnabled(True)
        self.label_edit.textEdited.connect(self._label_edited)
        self.label_edit.returnPressed.connect(lambda: self.textgrid_view.setFocus())
        self.label_edit.setToolTip(r"Praat backslash codes such as \ae or \sw are shown as IPA in the tiers")
        self.ipa_button = QToolButton(text="IPA")
        self.ipa_button.setToolTip("Insert IPA symbols")
        self.ipa_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        palette = IpaPalette()
        palette.symbol_chosen.connect(self._insert_symbol)
        menu = QMenu(self.ipa_button)
        palette_action = QWidgetAction(menu)
        palette_action.setDefaultWidget(palette)
        menu.addAction(palette_action)
        self.ipa_button.setMenu(menu)
        self.label_row = QWidget()
        row = QHBoxLayout(self.label_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.label_edit, 1)
        row.addWidget(self.ipa_button)
        self.textgrid_view = TextGridView(self.axis, doc, self._plot_area)
        self.textgrid_view.item_selected.connect(self._sync_label_edit)
        self.textgrid_view.message.connect(self.message)
        self.textgrid_view.type_text.connect(self._type_into_label)
        self.voicing_bar = VoicingBar(self.axis, self._plot_area)
        self.find_bar = FindBar(self.textgrid_view)
        self.find_bar.hide()
        self.find_bar.closed.connect(lambda: self.textgrid_view.setFocus())
        doc.textgrid_changed.connect(self._on_textgrid_changed)
        doc.sound_changed.connect(self._on_sound_changed)

        self.scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.scrollbar.valueChanged.connect(self._scrolled)
        self.axis.view_changed.connect(self._sync_scrollbar)

        layout = QVBoxLayout(self)
        self.setObjectName("editorPage")
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(self.overview)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(self.voicing_bar)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.label_row)
        layout.addWidget(self.textgrid_view)
        layout.addWidget(self.scrollbar)

        self._playhead_timer = QTimer(self, interval=PLAYHEAD_INTERVAL_MS)
        self._playhead_timer.timeout.connect(self._update_playhead)
        self.player.finished.connect(self._on_playback_finished)
        self._playing = False

        for name in LAYERS:
            self.set_layer_visible(name, prefs.pane_visible(name, name not in HIDDEN_BY_DEFAULT))
        self._on_textgrid_changed()
        self._sync_scrollbar(*self.axis.view)
        if not self.manager.analyses_available:
            self._on_window_changed(False)

    # ------------------------------------------------------------------ editing the audio

    def _on_sound_changed(self):
        """Every pane moves to the new audio. Runs for edits, undo and redo."""
        sound = self.doc.sound
        self.stop()
        self._resynthesis = self._after_resynthesis = None
        self.manager.set_sound(self.doc.analysis_sound)
        self.waveform.set_sound(sound)
        self.overview.set_sound(sound)
        self.axis.set_duration(sound.duration)
        self.manipulation_pane.set_state(self.doc.manipulation)
        if self.manipulation_pane.isVisible():
            self.ensure_manipulation()

    def set_analysis_channel(self, channel: int | None) -> None:
        """Measure one channel, or the mix (None). The manipulation comes from the old audio, so it starts again."""
        doc = self.doc
        if channel == doc.analysis_channel:
            return
        if doc.sound.is_long:
            self.message.emit("Long recordings are analysed as a mix: extract a part to analyse one channel")
            return
        doc.analysis_channel = channel
        doc.manipulation = None
        self._resynthesis = self._after_resynthesis = None
        self.manager.set_sound(doc.analysis_sound)
        self.manipulation_pane.set_state(None)
        if self.manipulation_pane.isVisible():
            self.ensure_manipulation()
        self.waveform.mark_channels(channel, self.muted)
        self.axis.selection_changed.emit(self.axis.selection)  # the spectrum panel follows this
        self.axis.view_changed.emit(*self.axis.view)
        self.message.emit(
            "Analysing the mix of all channels" if channel is None else f"Analysing channel {channel + 1}"
        )

    def channel_gains(self) -> np.ndarray | None:
        if not self.muted:
            return None
        gains = np.ones(self.doc.sound.n_channels, dtype=np.float32)
        gains[list(self.muted)] = 0
        return gains

    def set_channel_muted(self, channel: int, muted: bool) -> None:
        (self.muted.add if muted else self.muted.discard)(channel)
        self.player.set_gains(self.channel_gains())
        self.waveform.mark_channels(self.doc.analysis_channel, self.muted)

    def _selected_samples(self) -> tuple[int, int] | None:
        if self.axis.selection is None:
            self.message.emit("Select a part of the sound first")
            return None
        a, b = sorted(self.doc.sound.time_to_index(t) for t in self.axis.selection)
        if a == b:
            self.message.emit("The selection is too short to hold a sample")
            return None
        return a, b

    def _splice(self, description: str, start: int, end: int, inserted=None) -> bool:
        state = self.doc.manipulation
        modified = state is not None and state.is_modified
        try:
            self.doc.splice_audio(description, start, end, inserted)
        except (TextGridError, LongSoundError) as e:
            self.message.emit(str(e))
            return False
        if modified:
            self.message.emit("The manipulation was reset for the edited sound. Undo brings it back.")
        return True

    @_reports_long_sound_limits
    def copy_selection(self) -> SoundClip | None:
        """The selected audio, ready to paste into this or any other open sound."""
        if self.axis.selection is None:
            self.message.emit("Select a part of the sound first")
            return None
        part = self.doc.sound.extract(*self.axis.selection)
        return SoundClip(part.samples, part.sampling_rate) if part.n_samples else None

    def cut_selection(self) -> SoundClip | None:
        span = self._selected_samples()
        if span is None:
            return None
        clip = self.copy_selection()
        if clip is None or not self._splice("Cut", *span):
            return None
        self.axis.clear_selection()
        self.axis.set_cursor(span[0] / self.doc.sound.sampling_rate)
        return clip

    def paste(self, clip: SoundClip | None, where: str = "here"):
        """Paste ``before`` or ``after`` the selection, or ``here``: over a selection, otherwise at the cursor."""
        sound = self.doc.sound
        if clip is None:
            self.message.emit("Nothing to paste: cut or copy part of a sound first")
            return
        if problem := clip.problem_with(sound):
            self.message.emit(problem)
            return
        selection = self.axis.selection
        if where != "here" and selection is None:
            self.message.emit("Select a part of the sound first")
            return
        if selection is None:
            start = end = sound.time_to_index(self.axis.cursor)
        else:
            a, b = sorted(sound.time_to_index(t) for t in selection)
            start, end = {"here": (a, b), "before": (a, a), "after": (b, b)}[where]
        names = {"here": "Paste", "before": "Paste before selection", "after": "Paste after selection"}
        if self._splice(names[where], start, end, clip.samples):
            rate = sound.sampling_rate
            self.axis.set_selection(start / rate, (start + len(clip.samples)) / rate)

    # ------------------------------------------------------------------ alignment

    def align(self, language: str, whole_tier: bool = False):
        """Find the words and phonemes of the selected interval's text, or of every labelled interval on its tier."""
        view = self.textgrid_view
        tier = view.current_tier()
        if not praat_engine.available():
            self.message.emit(speech.NEEDS_PRAAT)
        elif not isinstance(tier, IntervalTier):
            self.message.emit("Select an interval tier first")
        elif not whole_tier and view.selected_item is None:
            self.message.emit("Select an interval with text to align")
        else:
            chosen = tier.intervals if whole_tier else [tier.intervals[view.selected_item]]
            spans = [(iv.xmin, iv.xmax, to_unicode(iv.text)) for iv in chosen if iv.text.strip()]
            if not spans:
                self.message.emit("Type the text of the interval first")
                return
            self._aligning = tier.name
            self.message.emit("Aligning…")
            self.manager.submit("alignment", speech.align_many, spans, language)

    def _finish_alignment(self, alignments, problems):
        source = self._aligning
        if self.doc.textgrid is None or not any(t.name == source for t in self.doc.textgrid.tiers):
            self.message.emit("The tier being aligned has gone")
            return
        if alignments:
            self.doc.edit("Align", lambda grid: speech.apply_alignments(grid, source, alignments))
        if problems:
            self.message.emit(
                f"{len(problems)} of {len(alignments) + len(problems)} could not be aligned: {problems[0]}"
            )
        else:
            self.message.emit(f"Aligned {len(alignments)} interval(s)")

    # ------------------------------------------------------------------ layout helpers

    def _plot_area(self) -> tuple[float, float]:
        pane = next((p for p in self.panes if p.isVisible()), self.waveform)
        left, right = pane.plot_area_x()
        if right <= left:  # not laid out yet
            return LEFT_AXIS_WIDTH, self.width() - RIGHT_AXIS_WIDTH
        offset = pane.mapTo(self, pane.rect().topLeft()).x()
        return left + offset, right + offset

    def _sync_scrollbar(self, start: float, end: float):
        width_ms = int((end - start) * 1000)
        self.scrollbar.blockSignals(True)
        self.scrollbar.setRange(0, max(0, int(self.axis.duration * 1000) - width_ms))
        self.scrollbar.setPageStep(max(width_ms, 1))
        self.scrollbar.setSingleStep(max(width_ms // 10, 1))
        self.scrollbar.setValue(int(start * 1000))
        self.scrollbar.blockSignals(False)

    def _scrolled(self, value: int):
        v0, v1 = self.axis.view
        self.axis.set_view(value / 1000, value / 1000 + (v1 - v0))

    def set_layer_visible(self, name: str, visible: bool):
        self.prefs.set_pane_visible(name, visible)
        if name == "waveform":
            self.waveform.setVisible(visible)
        elif name == "pulses":
            self.waveform.set_pulses_visible(visible)
            self.manager.set_enabled("pulses", visible)
        elif name == "voicing":
            self.voicing_bar.setVisible(visible)
            self.manager.set_enabled("voicing", visible)
        elif name == "manipulation":
            self.manipulation_pane.setVisible(visible)
            if visible:
                self.ensure_manipulation()
        else:
            self.spectrogram.set_layer_visible(name, visible)
            any_layer = any(self.spectrogram.visible[n] for n in SpectrogramPane.LAYERS)
            self.spectrogram.setVisible(any_layer)

    def _on_window_changed(self, available: bool):
        """Long sounds: the panes outside the spectrogram follow the analysis window too."""
        if available:
            self.voicing_bar.hint = "analysing…"
        else:
            self.voicing_bar.hint = "zoom in to see voicing"
            self.voicing_bar.set_result(None)
            self.waveform.set_pulses(None)
        self.voicing_bar.update()

    def _on_result(self, name: str):
        if name == "pulses":
            self.waveform.set_pulses(self.manager.results["pulses"].times)
        elif name == "voicing":
            self.voicing_bar.set_result(self.manager.results["voicing"])

    def layer_visible(self, name: str) -> bool:
        if name in STANDALONE_LAYERS:
            return self.prefs.pane_visible(name, name not in HIDDEN_BY_DEFAULT)
        return self.spectrogram.visible[name]

    def retheme(self):
        """Re-read colours after a theme change."""
        self.overview.retheme()
        for pane in self.panes:
            pane.retheme()
        self.textgrid_view.update()
        self.voicing_bar.update()

    def apply_settings(self, name: str, settings):
        self.prefs.set_analysis_settings(name, settings)
        self.manager.update_settings(name, settings)
        self.spectrogram.apply_settings()
        if "voicing" not in self.manager.results:  # pitch or voicing settings changed: recomputing
            self.voicing_bar.set_result(None)

    def add_voicing_tier(self):
        """Add a "voicing" interval tier with Praat-style V/U labels (one undoable step)."""
        doc = self.doc
        if doc.sound.is_long:
            self.message.emit(EXTRACT_FIRST)
            return
        if doc.textgrid is None:
            doc.set_textgrid(TextGrid.for_duration(doc.sound.duration, ()), saved=False)
        r = self.result("voicing")

        def add(tg):
            tier = IntervalTier("voicing", tg.xmin, tg.xmax)
            for a, b in zip(r.starts, r.ends, strict=True):
                for t in (a, b):
                    if tg.xmin < t < tg.xmax and t not in tier.boundaries:
                        tier.add_boundary(t)
            for iv in tier.intervals:
                iv.text = "V" if r.voiced_at((iv.xmin + iv.xmax) / 2) else "U"
            tg.tiers.append(tier)

        doc.edit("Add voicing tier", add)

    # ------------------------------------------------------------------ manipulation

    def ensure_manipulation(self) -> bool:
        """Show the manipulation, starting its pitch analysis if needed. True if it is ready."""
        if self.doc.sound.is_long:
            self.manipulation_pane.set_status(EXTRACT_FIRST)
            return False
        if self.doc.manipulation is not None:
            self.manipulation_pane.set_state(self.doc.manipulation)
            return True
        self.manager.submit("manipulation", manipulation.analyse, self.manipulation_settings)
        return False

    def apply_manipulation_settings(self, settings: ManipulationSettings):
        """New analysis settings discard the current manipulation (its points came from the old analysis)."""
        self.prefs.set_analysis_settings("manipulation", settings)
        self.manipulation_settings = settings
        self.doc.manipulation = None
        self._resynthesis = None
        self.manipulation_pane.set_state(None)
        self.manipulation_pane.set_status("Analysing pitch for manipulation…")
        if self.layer_visible("manipulation"):
            self.ensure_manipulation()

    def compare_formant_ceilings(self):
        """Analyse the selection (or visible stretch) at several ceilings, in the background."""
        start, end = self.axis.selection or self.axis.view
        if not praat_engine.available():
            self.message.emit("Comparing formant ceilings needs the bundled Praat 7 program")
        elif end - start > formant_path.MAX_SECONDS:
            self.message.emit(f"Select {formant_path.MAX_SECONDS:.0f} seconds or less to compare formant ceilings")
        else:
            settings = self.prefs.analysis_settings("formant_path", formant_path.FormantPathSettings)
            self.manager.submit(
                "formant_path", formant_path.compare_ceilings, start, end, self.manager.settings["formants"], settings
            )

    def use_formant_ceiling(self, ceiling: float):
        self.apply_settings("formants", replace(self.manager.settings["formants"], max_formant=round(ceiling, 1)))
        self.log.emit(f"Formant ceiling set to {ceiling:.0f} Hz")

    def _on_job_done(self, key: str, result):
        if key == "formant_path":
            self.formant_path_ready.emit(result)
        elif key == "alignment":
            self._finish_alignment(*result)
        elif key == "manipulation":
            self.doc.manipulation = ManipulationState(result, self.manipulation_settings, self.doc.undo_stack, self.doc)
            self.manipulation_pane.set_state(self.doc.manipulation)
        elif key == "resynthesis":
            # Results come back as copies, so cache them under the tier objects we submitted.
            self._resynthesis = (*self._resynthesis_tiers, *result)
            action, self._after_resynthesis = self._after_resynthesis, None
            if action:
                action()

    def _on_job_failed(self, key: str, message: str):
        self.message.emit(f"{key.title()} failed: {message}")
        if key == "manipulation":
            self.manipulation_pane.set_status(f"Manipulation unavailable: {message}")

    def _with_resynthesis(self, action):
        """Call ``action(samples, sr)`` with the resynthesis of the current tiers (computing it if stale)."""
        state = self.doc.manipulation
        if self.doc.sound.is_long:
            self.message.emit(EXTRACT_FIRST)
            return
        if state is None:
            self.message.emit("Show the manipulation first (View ▸ Show manipulation)")
            return
        cached = self._resynthesis
        if cached and cached[0] is state.pitch and cached[1] is state.duration and cached[2] is state.gain:
            action(cached[3], cached[4])
            return
        self._after_resynthesis = lambda: self._with_resynthesis(action)
        self._resynthesis_tiers = (state.pitch, state.duration, state.gain)
        self.manager.submit(
            "resynthesis", manipulation.resynthesize, self.manipulation_settings, *self._resynthesis_tiers
        )

    def play_resynthesis(self):
        if self._playing:
            self.stop()
            return

        def play(samples, sr):
            state = self.doc.manipulation
            start, end = self.axis.play_range()
            total = self.doc.sound.duration
            a, b = (manipulation.map_time(state.duration, t, total) for t in (start, end))
            # With duration changes the timeline no longer matches the editor, so hide the playhead.
            self.play(a, b, samples=samples, sampling_rate=sr, follow=len(state.duration) == 0)

        self._with_resynthesis(play)

    def open_resynthesis(self):
        def open_(samples, sr):
            self.new_sound.emit(Sound(samples, sr, title=f"{self.doc.sound.name}_manipulated"))

        self._with_resynthesis(open_)

    def _manipulation_range(self) -> tuple[float, float]:
        return self.axis.selection or (0.0, self.doc.sound.duration)

    def _require_manipulation(self) -> ManipulationState | None:
        if self.doc.sound.is_long:
            self.message.emit(EXTRACT_FIRST)
            return None
        if self.doc.manipulation is None:
            self.set_layer_visible("manipulation", True)
            self.message.emit("Analysing pitch for manipulation; try again in a moment")
            return None
        return self.doc.manipulation

    def stylize_pitch(self, semitones: float = 2.0):
        if state := self._require_manipulation():
            pitch = manipulation.stylize(state.pitch, semitones, self.doc.analysis_sound)
            state.apply(f"Stylize pitch ({semitones:g} st)", pitch=pitch)

    def shift_pitch(self, semitones: float):
        if state := self._require_manipulation():
            pitch = manipulation.shift_semitones(state.pitch, semitones, *self._manipulation_range())
            state.apply(f"Shift pitch {semitones:+g} st", pitch=pitch)

    def flatten_pitch(self):
        if state := self._require_manipulation():
            state.apply("Flatten pitch", pitch=manipulation.flatten(state.pitch, *self._manipulation_range()))

    def remove_pitch_points(self):
        state = self._require_manipulation()
        if state is None:
            return
        if not self.axis.selection:
            self.message.emit("Select the stretch whose pitch points should be removed")
            return
        state.apply("Remove pitch points", pitch=state.pitch.without_range(*self.axis.selection))

    def add_pitch_point_at_cursor(self):
        if state := self._require_manipulation():
            t = self.axis.cursor
            self.manipulation_pane.add_point(t, state.pitch.value_at(t, default=state.settings.floor * 2))

    def set_duration_factor(self, factor: float):
        if not self.axis.selection:
            self.message.emit("Select the stretch to lengthen or shorten")
            return
        if state := self._require_manipulation():
            duration = manipulation.set_duration_factor(state.duration, *self.axis.selection, factor)
            state.apply(f"Duration ×{factor:g}", duration=duration)

    def set_loudness(self, decibels: float):
        if not self.axis.selection:
            self.message.emit("Select the stretch to make louder or quieter")
            return
        if state := self._require_manipulation():
            gain = manipulation.set_gain(state.gain, *self.axis.selection, decibels)
            state.apply(f"Loudness {decibels:+g} dB", gain=gain)

    def reset_manipulation(self):
        if state := self._require_manipulation():
            state.reset()

    # ------------------------------------------------------------------ labels

    def _on_textgrid_changed(self):
        self.label_row.setVisible(self.doc.textgrid is not None)
        self._sync_label_edit()

    def _sync_label_edit(self):
        view = self.textgrid_view
        tier = view.current_tier()
        if tier is None or view.selected_item is None:
            self.label_edit.setEnabled(False)
            self.ipa_button.setEnabled(False)
            self.label_edit.clear()
            return
        self.label_edit.setEnabled(True)
        self.ipa_button.setEnabled(True)
        text = tier.get_text(view.selected_item)
        if text != self.label_edit.text():
            self.label_edit.setText(text)

    def _label_edited(self, text: str):
        view = self.textgrid_view
        if view.selected_item is None:
            return
        try:
            self.doc.set_label(view.selected_tier, view.selected_item, text)
        except TextGridError as e:
            self.message.emit(str(e))

    def _insert_symbol(self, symbol: str):
        if self.textgrid_view.selected_item is not None:
            self._type_into_label(symbol)

    def _type_into_label(self, text: str):
        self.label_edit.setFocus()
        self.label_edit.insert(text)
        self._label_edited(self.label_edit.text())

    # ------------------------------------------------------------------ playback

    @property
    def is_playing(self) -> bool:
        return self._playing

    def toggle_playback(self):
        if self._playing:
            self.stop()
        else:
            self.play(*self.axis.play_range())

    def play(self, start: float, end: float, samples=None, sampling_rate=None, follow: bool = True):
        """Play ``[start, end]`` of the sound (or of other ``samples``); ``follow`` moves the playhead."""
        if not self.player.available:
            self.message.emit("No audio output device available")
            return
        gains = None
        if samples is None:
            samples, sampling_rate = self.doc.sound.samples, self.doc.sound.sampling_rate
            gains = self.channel_gains()
        try:
            self.player.play(samples, sampling_rate, start, end, gains)
        except Exception as e:  # sounddevice raises PortAudioError for device problems
            self.message.emit(f"Playback failed: {e}")
            return
        self._playing = True
        if follow:
            self._playhead_timer.start()

    def stop(self):
        if self._playing:
            self.player.stop()

    def _on_playback_finished(self):
        if not self._playing:
            return
        self._playing = False
        self._playhead_timer.stop()
        self._show_playhead(None)

    def _update_playhead(self):
        t = self.player.position
        self._show_playhead(t)
        self.axis.ensure_visible(t)

    def _show_playhead(self, t):
        for pane in self.panes:
            pane.set_playhead(t)
        self.textgrid_view.playhead = t
        self.textgrid_view.update()
        self.voicing_bar.playhead = t
        self.voicing_bar.update()

    # ------------------------------------------------------------------ queries

    def result(self, name: str):
        """Analysis result, computing it synchronously if its layer is hidden."""
        if name not in self.manager.results:
            return self.manager.compute_now(name)
        return self.manager.results[name]

    # ------------------------------------------------------------------ corrections

    def _selected_stretch(self) -> tuple[float, float] | None:
        if self.axis.selection is None:
            self.message.emit("Select the stretch to correct first")
        return self.axis.selection

    def correct_unvoice(self):
        if span := self._selected_stretch():
            self.doc.correct("Unvoice", self.doc.corrections.with_unvoiced(*span))

    def correct_octave(self, factor: float):
        if span := self._selected_stretch():
            direction = "up" if factor > 1 else "down"
            self.doc.correct(f"Octave {direction}", self.doc.corrections.with_octave(*span, factor))

    def correct_remove_pulses(self):
        if span := self._selected_stretch():
            self.doc.correct("Remove pulses", self.doc.corrections.with_pulses_removed(*span))

    def correct_add_pulse(self):
        self.doc.correct("Add pulse", self.doc.corrections.with_pulse(self.axis.cursor))

    def correct_restore(self):
        """Undo every correction touching the selection, or all of them with no selection."""
        c = self.doc.corrections
        span = self.axis.selection
        self.doc.correct("Restore analysis", c.without_range(*span) if span else type(c)())

    def _check_coverage(self):
        """Long sounds: refuse rather than report statistics over part of what was asked for."""
        start, end = self.axis.selection or (self.axis.cursor, self.axis.cursor)
        if not self.manager.covers(start, end):
            hint = ZOOM_HINT if self.manager.analysis_window is None else "Zoom so that all of it is in view"
            raise LongSoundError(hint)

    def _where(self) -> str:
        if self.axis.selection:
            a, b = self.axis.selection
            return f"{a:.4f}–{b:.4f} s"
        return f"{self.axis.cursor:.4f} s"

    @_reports_long_sound_limits
    def query_pitch(self):
        self._check_coverage()
        p = self.result("pitch")
        if self.axis.selection:
            st = queries.pitch_stats(p, *self.axis.selection)
            slope = queries.pitch_mean_abs_slope(p, *self.axis.selection)
            mean_st = fmt(queries.semitones(st.mean), "st re 100 Hz")
            self.log.emit(
                f"Pitch {self._where()}: mean {fmt(st.mean, 'Hz')} ({mean_st}), "
                f"median {fmt(st.median, 'Hz')}, sd {fmt(st.stdev, 'Hz')}, "
                f"min {fmt(st.minimum, 'Hz')} at {fmt(st.time_of_minimum, 's', 4)}, "
                f"max {fmt(st.maximum, 'Hz')} at {fmt(st.time_of_maximum, 's', 4)}, "
                f"mean |slope| {fmt(slope, 'Hz/s', 1)} ({st.n_frames} voiced frames)"
            )
        else:
            f0 = queries.pitch_at(p, self.axis.cursor)
            self.log.emit(f"Pitch at {self._where()}: {fmt(f0, 'Hz')} ({fmt(queries.semitones(f0), 'st re 100 Hz')})")

    @_reports_long_sound_limits
    def query_formants(self):
        self._check_coverage()
        f = self.result("formants")
        if self.axis.selection:
            stats = queries.formant_stats(f, *self.axis.selection)
            parts = [f"F{i + 1} {fmt(s.mean, 'Hz', 0)}" for i, s in enumerate(stats[:4])]
            self.log.emit(f"Mean formants {self._where()}: " + ", ".join(parts))
        else:
            values = queries.formants_at(f, self.axis.cursor)
            try:
                bws = queries.formant_bandwidths_at(
                    self.doc.analysis_sound, self.manager.settings["formants"], self.axis.cursor
                )
            except Exception:  # cursor too close to the edges for a Burg window
                bws = [float("nan")] * len(values)
            parts = [
                f"F{i + 1} {fmt(v, 'Hz', 0)} (B{i + 1} {fmt(b, 'Hz', 0)})"
                for i, (v, b) in enumerate(zip(values[:4], bws, strict=False))
            ]
            self.log.emit(f"Formants at {self._where()}: " + ", ".join(parts))

    @_reports_long_sound_limits
    def query_intensity(self):
        self._check_coverage()
        r = self.result("intensity")
        if self.axis.selection:
            st = queries.intensity_stats(r, *self.axis.selection)
            self.log.emit(
                f"Intensity {self._where()}: mean {fmt(st.mean, 'dB')}, "
                f"min {fmt(st.minimum, 'dB')}, max {fmt(st.maximum, 'dB')}"
            )
        else:
            self.log.emit(f"Intensity at {self._where()}: {fmt(queries.intensity_at(r, self.axis.cursor), 'dB')}")

    def query_voice_report(self):
        """Praat's voice report over the selection (or the visible window)."""
        start, end = self.axis.selection or self.axis.view
        report = voice.voice_report(
            self.doc.analysis_sound, self.manager.settings["pitch"], self.manager.settings["pulses"], start, end,
            self.doc.corrections,
        )  # fmt: skip
        header = f"Voice report for {self.doc.sound.name}, {start:.4f}–{end:.4f} s:"
        self.log.emit(f"{header}\n{report.text.rstrip()}\n")
        return report

    def query_duration(self):
        if self.axis.selection:
            a, b = self.axis.selection
            self.log.emit(f"Selection duration: {b - a:.6f} s ({a:.6f}–{b:.6f})")
        else:
            self.log.emit(f"Total duration of {self.doc.sound.name}: {self.doc.sound.duration:.6f} s")

    def readout(self, t: float | None, freq: float | None) -> dict[str, str]:
        """Values at time ``t`` for the info panel; analyses that aren't ready show "…"."""
        snd = self.doc.sound
        res = self.manager.results
        out = {"Time": "" if t is None else f"{t:.4f} s"}
        if t is None or not 0 <= t <= snd.duration:
            return out
        if not self.manager.covers(t, t):
            out["Amplitude"] = f"{snd.amplitude_at(t):+.4f}"
            return out
        out["Amplitude"] = f"{snd.amplitude_at(t):+.4f}"
        out["Frequency"] = "" if freq is None else f"{freq:.0f} Hz"
        out["Pitch"] = fmt(queries.pitch_at(res["pitch"], t), "Hz", 1) if "pitch" in res else "…"
        if "formants" in res:
            for i, v in enumerate(queries.formants_at(res["formants"], t)[:4]):
                out[f"F{i + 1}"] = fmt(v, "Hz", 0)
        if "voicing" in res:
            out["Voicing"] = "voiced" if res["voicing"].voiced_at(t) else "unvoiced"
        out["Intensity"] = fmt(queries.intensity_at(res["intensity"], t), "dB", 1) if "intensity" in res else "…"
        return out

    # ------------------------------------------------------------------ export

    def export_selection(self, path: Path):
        if self.axis.selection:
            self.doc.sound.extract(*self.axis.selection).save(path)
        else:
            self.doc.sound.save(path)

    def export_table(self, name: str, path: Path):
        """Write an analysis as CSV, restricted to the selection if there is one."""
        if self.doc.sound.is_long and not self.axis.selection:
            raise LongSoundError("Select a stretch and zoom to it: long recordings are analysed in parts")
        self._check_coverage()
        r = self.result(name)
        if name == "pitch":
            header, cols = ["time_s", "f0_hz"], [r.times, r.frequencies]
        elif name == "formants":
            header = ["time_s"] + [f"F{i + 1}_hz" for i in range(r.frequencies.shape[0])]
            cols = [r.times, *r.frequencies]
        else:
            header, cols = ["time_s", "intensity_db"], [r.times, r.db]
        rows = np.column_stack(cols)
        if self.axis.selection:
            a, b = self.axis.selection
            rows = rows[(rows[:, 0] >= a) & (rows[:, 0] <= b)]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for row in rows:
                w.writerow(["" if np.isnan(v) else f"{v:.6g}" for v in row])

    def export_textgrid_table(self, path: Path):
        tg = self.doc.textgrid
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["tier", "start_s", "end_s", "label"])
            for tier in tg.tiers:
                if isinstance(tier, IntervalTier):
                    for iv in tier.intervals:
                        if iv.text:
                            w.writerow([tier.name, f"{iv.xmin:.6f}", f"{iv.xmax:.6f}", iv.text])
                else:
                    for pt in tier.points:
                        w.writerow([tier.name, f"{pt.time:.6f}", f"{pt.time:.6f}", pt.mark])
