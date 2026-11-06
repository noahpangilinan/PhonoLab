"""Main window: tabbed documents, menus, docks and file handling."""

from __future__ import annotations

import atexit
import logging
from pathlib import Path

import parselmouth
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence, QUndoGroup
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QTabWidget,
)

from phonolab import __version__
from phonolab.audio.player import AudioPlayer
from phonolab.core import praat_engine, sound_ops
from phonolab.core.batch import BatchOptions
from phonolab.core.figures import FigureSettings
from phonolab.core.registry import ANALYSES
from phonolab.core.settings import Preferences
from phonolab.core.sound import (
    SUPPORTED_EXTENSIONS,
    LongSoundError,
    Sound,
    SoundLoadCancelledError,
    SoundLoadError,
)
from phonolab.core.spectrum import SpectrumSettings
from phonolab.core.textgrid import TextGrid, TextGridError
from phonolab.core.tiers import SUFFIXES as TIER_SUFFIXES
from phonolab.core.tiers import TierFile, TierFileError, read_tier
from phonolab.ui.dialogs.batch_dialog import BatchDialog
from phonolab.ui.dialogs.figure_dialog import FigureDialog
from phonolab.ui.dialogs.formant_path_dialog import FormantPathDialog
from phonolab.ui.dialogs.new_textgrid import NewTextGridDialog
from phonolab.ui.dialogs.record_dialog import RecordDialog
from phonolab.ui.dialogs.settings_dialog import SettingsDialog
from phonolab.ui.document import Document
from phonolab.ui.editor.sound_editor import EXTRACT_FIRST, HIDDEN_BY_DEFAULT, LAYERS, SoundEditor
from phonolab.ui.info_panel import InfoPanel
from phonolab.ui.log_panel import LogPanel
from phonolab.ui.script_window import ScriptWindow
from phonolab.ui.spectrum_panel import SpectrumPanel
from phonolab.ui.start_page import StartPage
from phonolab.ui.theme import THEME_CHOICES, apply_theme
from phonolab.ui.tier_window import TierWindow
from phonolab.ui.views_panel import ViewsPanel

log = logging.getLogger(__name__)

RELEASE_DELAY_MS = 300
SOUND_FILTER = "Sound files (" + " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS) + ");;All files (*)"
TIER_FILTER = "Praat tiers (*.PitchTier *.DurationTier *.IntensityTier *.AmplitudeTier *.RealTier);;All files (*)"
TEXTGRID_FILTER = "TextGrid files (*.TextGrid *.textgrid);;All files (*)"

SHORTCUTS = [
    ("Playback", [("Space / Tab", "Play selection, or from cursor to end of window; again to stop"), ("Esc", "Stop")]),
    (
        "Navigation",
        [
            ("Ctrl+= / Ctrl+-", "Zoom in / out"),
            ("Ctrl+wheel", "Zoom around the mouse"),
            ("Wheel, Page Up/Down", "Scroll"),
            ("Ctrl+N", "Zoom to selection"),
            ("Ctrl+A", "Show all"),
            ("Click / drag", "Set cursor / select"),
            ("Shift+click", "Extend selection"),
        ],
    ),
    (
        "Annotation",
        [
            ("Enter", "Add boundary (or point) at the cursor"),
            ("Double-click in tier", "Add boundary there"),
            ("Drag boundary", "Move it"),
            ("Delete / Alt+Backspace", "Remove boundary near cursor"),
            ("Type", "Edit the selected interval's label"),
            ("Alt+Left / Alt+Right", "Previous / next interval"),
            ("Up / Down", "Change tier"),
            ("Ctrl+F, F3", "Find labels"),
            ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"),
        ],
    ),
    (
        "Measurements",
        [
            ("F5 / Ctrl+1", "Pitch at cursor or over selection"),
            ("F1 / Ctrl+2", "Formants"),
            ("F8 / Ctrl+3", "Intensity"),
            ("F2 / Ctrl+4", "Duration"),
            ("F6 / Ctrl+5", "Spectrum"),
            ("Ctrl+M", "Manipulation"),
            ("Shift+Space", "Play resynthesis"),
            ("Ctrl+Shift+V", "Voice report"),
            ("Ctrl+X / Ctrl+C / Ctrl+V", "Cut, copy and paste sound"),
        ],
    ),
]


class _LoadProgress:
    """Progress dialog for long files, which report as they stream. Short files never call it."""

    def __init__(self, name: str, parent):
        self.name, self.parent, self.dialog = name, parent, None

    def __call__(self, fraction: float) -> bool:
        if self.dialog is None:
            self.dialog = QProgressDialog(f"Opening {self.name}…", "Cancel", 0, 1000, self.parent)
            self.dialog.setWindowTitle("Long recording")
            self.dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.dialog.setMinimumDuration(0)
        self.dialog.setValue(int(fraction * 1000))
        QApplication.processEvents()
        return not self.dialog.wasCanceled()

    def close(self):
        if self.dialog is not None:
            self.dialog.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhonoLab")
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        self.qsettings = QSettings()
        self.prefs = Preferences(self.qsettings)
        self.player = AudioPlayer(self)
        self.sound_clip = None  # the last audio cut or copied, shared by every tab
        self.undo_group = QUndoGroup(self)

        self.start_page = StartPage()
        self.start_page.open_requested.connect(self.open_dialog)
        self.start_page.open_path.connect(self.open_sound)
        self.start_page.record_requested.connect(self.record)
        self.start_page.batch_requested.connect(self.batch_measure)
        self.tabs = QTabWidget(documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self.info_panel = InfoPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.info_panel)
        self.spectrum_panel = SpectrumPanel(self.prefs.analysis_settings("spectrum", SpectrumSettings), self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.spectrum_panel)
        self.spectrum_panel.hide()
        self.views_panel = ViewsPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.views_panel)
        self.views_panel.hide()
        self.spectrum_panel.settings_requested.connect(self._edit_spectrum_settings)
        self.log_panel = LogPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_panel)
        self.log_panel.hide()
        self.spectrum_panel.log_message.connect(self.log_panel.append)

        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        self._busy: set[str] = set()
        self.script_window: ScriptWindow | None = None
        QApplication.styleHints().colorSchemeChanged.connect(self._on_system_colours_changed)
        self._hidden_docks: list | None = None  # docks hidden while the start page shows

        self._editor_actions: list[QAction] = []
        self._textgrid_actions: list[QAction] = []
        self._layer_actions: dict[str, QAction] = {}
        self._build_menus()
        self._refresh_recent()
        self._on_tab_changed()

        geometry = self.qsettings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.qsettings.value("window/state")
        if state is not None:
            # restoreState sets each dock's visibility; record that layout afresh and hide it again,
            # since the start page shows first. It comes back when a document opens.
            self.restoreState(state)
            self._hidden_docks = None
            self._show_docks(False)

    # ------------------------------------------------------------------ menus

    def _action(self, menu, text, slot, shortcut=None, *, needs=None, tip=None, checkable=False):
        action = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setStatusTip(tip)
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        menu.addAction(action)
        if needs == "editor":
            self._editor_actions.append(action)
        elif needs == "textgrid":
            self._textgrid_actions.append(action)
        return action

    def _build_menus(self):
        mb = self.menuBar()
        e = "editor"
        tg = "textgrid"

        m = mb.addMenu("&File")
        self._action(m, "&Open Sound…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.recent_menu = m.addMenu("Open &Recent")
        self._action(
            m,
            "Open &TextGrid…",
            self.open_textgrid_dialog,
            "Ctrl+Shift+O",
            needs=e,
            tip="Attach an existing TextGrid to the current sound",
        )
        self._action(m, "&New TextGrid…", self.new_textgrid, "Ctrl+Shift+N", needs=e)
        self._action(
            m,
            "Open t&ier…",
            self.open_tier_dialog,
            tip="Open a Praat PitchTier, DurationTier, IntensityTier, AmplitudeTier or RealTier",
        )
        m.addSeparator()
        self._action(m, "&Save TextGrid", self.save_textgrid, QKeySequence.StandardKey.Save, needs=tg)
        self._action(m, "Save TextGrid &As…", self.save_textgrid_as, "Ctrl+Shift+S", needs=tg)
        x = m.addMenu("&Export")
        self._action(
            x,
            "Selection as &WAV…",
            self.export_selection,
            needs=e,
            tip="Save the selected part (or the whole sound) as a WAV file",
        )
        self._action(x, "&Pitch table (CSV)…", lambda: self.export_table("pitch"), needs=e)
        self._action(x, "&Formant table (CSV)…", lambda: self.export_table("formants"), needs=e)
        self._action(x, "&Intensity table (CSV)…", lambda: self.export_table("intensity"), needs=e)
        self._action(x, "&Annotations (CSV)…", self.export_annotations, needs=tg)
        x.addSeparator()
        self._action(x, "Publication &figure (PDF, SVG, PNG)…", self.make_figure, "Ctrl+P", needs=e)
        self._action(x, "View as &image (PNG)…", self.export_image, needs=e)
        m.addSeparator()
        self._action(
            m,
            "&Batch measure folder…",
            self.batch_measure,
            "Ctrl+B",
            tip="Measure every sound in a folder (or each labelled interval) into one CSV",
        )
        m.addSeparator()
        self._action(
            m, "&Close", lambda: self.close_tab(self.tabs.currentIndex()), QKeySequence.StandardKey.Close, needs=e
        )
        # Explicit: Qt's standard Quit binding is empty on Windows.
        self._action(m, "&Quit", self.close, "Ctrl+Q")

        m = mb.addMenu("&Edit")
        undo = self.undo_group.createUndoAction(self, "&Undo")
        # Not StandardKey.Undo: on Windows it includes Alt+Backspace, which removes a boundary here.
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        redo = self.undo_group.createRedoAction(self, "&Redo")
        redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        m.addActions([undo, redo])
        m.addSeparator()
        self._action(m, "Cu&t sound", self.cut_sound, "Ctrl+X", needs=e, tip="Remove the selection from the sound")
        self._action(m, "&Copy sound", self.copy_sound, "Ctrl+C", needs=e)
        self._action(
            m,
            "&Paste sound",
            lambda: self.paste_sound("here"),
            "Ctrl+V",
            needs=e,
            tip="Replace the selection, or insert at the cursor",
        )
        self._action(m, "Paste &before selection", lambda: self.paste_sound("before"), needs=e)
        self._action(m, "Paste a&fter selection", lambda: self.paste_sound("after"), needs=e)
        m.addSeparator()
        self._action(m, "Select &all", lambda: self.editor.axis.select_all(), "Ctrl+Shift+A", needs=e)
        self._action(
            m, "&Find label…", lambda: self.editor.find_bar.open_bar(), QKeySequence.StandardKey.Find, needs=tg
        )
        self._action(m, "Find &next", lambda: self.editor.find_bar.step(1), ["F3", "Ctrl+G"], needs=tg)
        self._action(m, "Find &previous", lambda: self.editor.find_bar.step(-1), ["Shift+F3", "Ctrl+Shift+G"], needs=tg)

        m = mb.addMenu("&View")
        self._action(m, "Zoom &in", lambda: self.editor.axis.zoom(0.5), ["Ctrl+=", "Ctrl++"], needs=e)
        self._action(m, "Zoom &out", lambda: self.editor.axis.zoom(2.0), "Ctrl+-", needs=e)
        self._action(m, "Zoom to &selection", lambda: self.editor.axis.zoom_to_selection(), "Ctrl+N", needs=e)
        self._action(m, "Show &all", lambda: self.editor.axis.show_all(), "Ctrl+A", needs=e)
        self._action(m, "Scroll back", lambda: self.editor.axis.scroll(-0.8), "PgUp", needs=e)
        self._action(m, "Scroll forward", lambda: self.editor.axis.scroll(0.8), "PgDown", needs=e)
        m.addSeparator()
        for name in LAYERS:
            action = self._action(m, f"Show {name}", lambda on, n=name: self.set_layer(n, on), needs=e, checkable=True)
            action.setChecked(self.prefs.pane_visible(name, name not in HIDDEN_BY_DEFAULT))
            self._layer_actions[name] = action
        m.addSeparator()
        m.addAction(self.info_panel.toggleViewAction())
        theme_menu = m.addMenu("&Theme")
        theme_group = QActionGroup(self)
        for choice in THEME_CHOICES:
            action = theme_menu.addAction(choice.title(), lambda c=choice: self._set_theme(c))
            action.setCheckable(True)
            action.setChecked(choice == self.prefs.theme())
            theme_group.addAction(action)
        m.addSeparator()
        m.addAction(self.spectrum_panel.toggleViewAction())
        m.addAction(self.views_panel.toggleViewAction())
        m.addAction(self.log_panel.toggleViewAction())

        m = mb.addMenu("&Play")
        self._action(m, "&Play / Stop", lambda: self.editor.toggle_playback(), ["Space", "Tab"], needs=e)
        self._action(m, "&Stop", lambda: self.editor.stop(), "Esc", needs=e)
        self._action(m, "Play &whole sound", lambda: self.editor.play(0, self.editor.doc.sound.duration), needs=e)

        m = mb.addMenu("&Sound")
        self._action(
            m,
            "&Save sound as…",
            lambda: self.save_sound_as(),
            "Ctrl+Alt+S",
            needs=e,
            tip="Save the whole sound as WAV, FLAC, AIFF, OGG or MP3",
        )
        m.addSeparator()
        self._action(m, "&Record…", self.record, "Ctrl+R")
        self._action(m, "&New tone or noise…", self.new_sound)
        self._action(m, "Synthesize &vowel (Klatt)…", self.synthesize_vowel)
        m.addSeparator()
        self._action(m, "E&xtract selection to new tab", self.extract_selection, "Ctrl+E", needs=e)
        self._action(m, "Convert to &mono", lambda: self._derive(sound_ops.to_mono), needs=e)
        self._action(m, "Re&sample…", lambda: self._derive(sound_ops.resample, sound_ops.ResampleSettings), needs=e)
        self._action(
            m, "Filter (&pass band)…", lambda: self._derive(sound_ops.pass_band, sound_ops.BandSettings), needs=e
        )
        self._action(
            m, "Filter (s&top band)…", lambda: self._derive(sound_ops.stop_band, sound_ops.BandSettings), needs=e
        )
        self._action(
            m, "Pre-&emphasis…", lambda: self._derive(sound_ops.pre_emphasis, sound_ops.PreEmphasisSettings), needs=e
        )
        self._action(
            m, "Scale &peak…", lambda: self._derive(sound_ops.scale_peak, sound_ops.ScalePeakSettings), needs=e
        )
        self._action(m, "Re&verse", lambda: self._derive(sound_ops.reverse), needs=e)
        self._action(
            m,
            "&Concatenate open sounds",
            self.concatenate_sounds,
            needs=e,
            tip="Join every open sound, in tab order, into a new sound",
        )

        m = mb.addMenu("&Analysis")
        for name, (cls, _) in ANALYSES.items():
            self._action(m, f"{cls.title} settings…", lambda _=False, n=name: self.edit_settings(n), needs=e)
        self._action(m, "Spectrum settings…", self._edit_spectrum_settings)

        m = mb.addMenu("&Manipulation")
        self._action(
            m,
            "&Show manipulation",
            lambda: self._show_manipulation(),
            "Ctrl+M",
            needs=e,
            tip="Edit the pitch contour and durations, then hear the PSOLA resynthesis",
        )
        self._action(m, "&Play resynthesis", lambda: self.editor.play_resynthesis(), "Shift+Space", needs=e)
        self._action(m, "Open resynthesis in new &tab", lambda: self.editor.open_resynthesis(), needs=e)
        m.addSeparator()
        self._action(m, "Add pitch point at &cursor", lambda: self.editor.add_pitch_point_at_cursor(), needs=e)
        self._action(m, "&Remove pitch points in selection", lambda: self.editor.remove_pitch_points(), needs=e)
        self._action(m, "Stylize pitch (2 semitones)", lambda: self.editor.stylize_pitch(2.0), needs=e)
        self._action(m, "Stylize pitch…", self._stylize_pitch, needs=e)
        self._action(
            m,
            "Shift pitch…",
            self._shift_pitch,
            needs=e,
            tip="Raise or lower the selection (or everything) by semitones",
        )
        self._action(
            m,
            "&Flatten pitch",
            lambda: self.editor.flatten_pitch(),
            needs=e,
            tip="Set the selection (or everything) to its mean pitch",
        )
        m.addSeparator()
        self._action(
            m,
            "Set &duration of selection…",
            self._set_duration,
            needs=e,
            tip="Lengthen (>1) or shorten (<1) the selected stretch",
        )
        self._action(
            m,
            "Set &loudness of selection…",
            self._set_loudness,
            needs=e,
            tip="Make the selected stretch louder or quieter, in dB",
        )
        self._action(m, "Re&set manipulation", lambda: self.editor.reset_manipulation(), needs=e)
        self._action(
            m, "Save pitch &tier…", self._save_pitch_tier, needs=e, tip="Save the edited contour as a Praat PitchTier"
        )
        m.addSeparator()
        self._action(m, "Manipulation settings…", self._edit_manipulation_settings, needs=e)

        m = mb.addMenu("&Correct")
        self._action(
            m,
            "&Unvoice selection",
            lambda: self.editor.correct_unvoice(),
            "Ctrl+U",
            needs=e,
            tip="Mark the selected stretch as having no pitch or pulses",
        )
        self._action(m, "Pitch octave &up in selection", lambda: self.editor.correct_octave(2.0), "Ctrl+Up", needs=e)
        self._action(
            m, "Pitch octave &down in selection", lambda: self.editor.correct_octave(0.5), "Ctrl+Down", needs=e
        )
        m.addSeparator()
        self._action(m, "&Remove pulses in selection", lambda: self.editor.correct_remove_pulses(), needs=e)
        self._action(m, "&Add pulse at cursor", lambda: self.editor.correct_add_pulse(), needs=e)
        m.addSeparator()
        self._action(
            m,
            "Restore &analysis",
            lambda: self.editor.correct_restore(),
            needs=e,
            tip="Remove corrections in the selection, or all of them with nothing selected",
        )
        self._action(
            m,
            "&Save corrections",
            self.save_corrections,
            "Ctrl+Alt+C",
            needs=e,
            tip="Saved next to the sound and loaded again when it opens",
        )

        m = mb.addMenu("&Query")
        self._action(m, "Get &pitch", lambda: self.editor.query_pitch(), ["F5", "Ctrl+1"], needs=e)
        self._action(m, "Get &formants", lambda: self.editor.query_formants(), ["F1", "Ctrl+2"], needs=e)
        self._action(m, "Get &intensity", lambda: self.editor.query_intensity(), ["F8", "Ctrl+3"], needs=e)
        self._action(m, "Get &duration", lambda: self.editor.query_duration(), ["F2", "Ctrl+4"], needs=e)
        self._action(
            m,
            "Compare formant &ceilings…",
            lambda: self.editor.compare_formant_ceilings(),
            "Ctrl+6",
            needs=e,
            tip="See the selection analysed at several formant ceilings and choose one",
        )
        m.addSeparator()
        self._action(m, "Spectral &slice / LTAS", self._show_spectrum, ["F6", "Ctrl+5"], needs=e)
        self._action(m, "Spectral &moments", lambda: self._show_spectrum(log=True), needs=e)
        self._action(
            m,
            "&CPPS",
            lambda: self.spectrum_panel.log_cpps(),
            needs=e,
            tip="Smoothed cepstral peak prominence over the selection (or visible window)",
        )
        self._action(
            m, "&Voice report", self._voice_report, "Ctrl+Shift+V", needs=e,
            tip="Jitter, shimmer and harmonicity over the selection (or the visible window)",
        )  # fmt: skip

        m = mb.addMenu("A&nnotate")
        tv = lambda: self.editor.textgrid_view  # noqa: E731
        self._action(m, "Add boundary/point at cursor\tEnter", lambda: tv().add_at_cursor(), needs=tg)
        self._action(m, "Remove boundary/point at cursor\tDel", lambda: tv().remove_near_cursor(), needs=tg)
        self._action(m, "Previous interval\tAlt+Left", lambda: tv().select_adjacent(-1), needs=tg)
        self._action(m, "Next interval\tAlt+Right", lambda: tv().select_adjacent(1), needs=tg)
        m.addSeparator()
        self._action(m, "Add &interval tier…", lambda: tv().add_tier("interval"), needs=tg)
        self._action(m, "Add &point tier…", lambda: tv().add_tier("point"), needs=tg)
        self._action(m, "&Rename tier…", lambda: tv().rename_tier(), needs=tg)
        self._action(m, "D&uplicate tier", lambda: tv().duplicate_tier(), needs=tg)
        self._action(
            m,
            "Add &voicing tier",
            lambda: self.editor.add_voicing_tier(),
            needs=e,
            tip="A tier of voiced (V) and unvoiced (U) intervals from the glottal pulses",
        )
        self._action(m, "Re&move tier…", lambda: tv().remove_tier(), needs=tg)

        m = mb.addMenu("&Tools")
        self._action(
            m,
            "&Script window…",
            self.show_script_window,
            "Ctrl+K",
            tip="Run Praat scripts or Python on the current sound",
        )
        self._action(m, "&Batch measure folder…", self.batch_measure)
        self._action(m, "&Figure…", self.make_figure, needs=e)

        m = mb.addMenu("&Help")
        self._action(m, "&Keyboard shortcuts", self.show_shortcuts, "Ctrl+/")
        self._action(m, "&About PhonoLab", self.show_about)

    # ------------------------------------------------------------------ state

    @property
    def editor(self) -> SoundEditor | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, SoundEditor) else None

    def editors(self) -> list[SoundEditor]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def _on_tab_changed(self, _index=None):
        editor = self.editor
        self.stack.setCurrentWidget(self.tabs if editor else self.start_page)
        self._show_docks(editor is not None)
        self.undo_group.setActiveStack(editor.doc.undo_stack if editor else None)
        self.info_panel.set_editor(editor)
        self.spectrum_panel.set_editor(editor)
        self.views_panel.set_editor(editor)
        self._update_actions()
        self._busy.clear()
        self._update_busy()
        if editor:
            editor.setFocus()

    def _show_docks(self, show: bool):
        """Hide the docks on the start page (they'd be empty) and bring back the same ones later."""
        docks = (self.info_panel, self.spectrum_panel, self.views_panel, self.log_panel)
        if not show and self._hidden_docks is None:
            # isHidden(), not isVisible(): before the window is first shown nothing is "visible".
            self._hidden_docks = [d for d in docks if not d.isHidden()]
            for d in self._hidden_docks:
                d.hide()
        elif show and self._hidden_docks is not None:
            for d in self._hidden_docks:
                d.show()
            self._hidden_docks = None

    def _update_actions(self):
        editor = self.editor
        has_tg = bool(editor and editor.doc.textgrid is not None)
        for a in self._editor_actions:
            a.setEnabled(editor is not None)
        for a in self._textgrid_actions:
            a.setEnabled(has_tg)
        if editor:
            for name, a in self._layer_actions.items():
                a.setChecked(editor.layer_visible(name))
        title = f"{editor.doc.title} — PhonoLab" if editor else "PhonoLab"
        self.setWindowTitle(title)

    def _on_title_changed(self, editor: SoundEditor):
        i = self.tabs.indexOf(editor)
        if i >= 0:
            self.tabs.setTabText(i, editor.doc.title)
        self._update_actions()

    def _on_busy(self, editor: SoundEditor, name: str, busy: bool):
        if editor is not self.editor or name == "spectrogram":
            return
        (self._busy.add if busy else self._busy.discard)(name)
        self._update_busy()

    def _update_busy(self):
        self.busy_label.setText(("Computing " + ", ".join(sorted(self._busy)) + "…") if self._busy else "")

    def set_layer(self, name: str, visible: bool):
        for editor in self.editors():
            editor.set_layer_visible(name, visible)

    def _set_theme(self, choice: str):
        self.prefs.set_theme(choice)
        self._apply_theme()

    def _apply_theme(self):
        apply_theme(QApplication.instance(), self.prefs.theme())
        for editor in self.editors():
            editor.retheme()
        self.spectrum_panel.retheme()
        self.views_panel.retheme()
        for tier_window in self.findChildren(TierWindow):
            tier_window.retheme()
        self.start_page.update()

    def _on_system_colours_changed(self):
        if self.prefs.theme() == "system":
            self._apply_theme()

    def copy_sound(self):
        self.sound_clip = self.editor.copy_selection() or self.sound_clip

    def cut_sound(self):
        self.sound_clip = self.editor.cut_selection() or self.sound_clip

    def paste_sound(self, where: str):
        self.editor.paste(self.sound_clip, where)

    def show_message(self, text: str):
        self.statusBar().showMessage(text, 5000)

    # ------------------------------------------------------------------ opening

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open sound", self._last_dir(), SOUND_FILTER)
        for p in paths:
            self.open_sound(p)

    def _last_dir(self) -> str:
        return str(self.qsettings.value("last_dir", str(Path.home())))

    def open_path(self, path: str):
        suffix = Path(path).suffix.lower()
        if suffix == ".textgrid":
            self.open_textgrid(path)
        elif suffix in TIER_SUFFIXES:
            self.open_tier(path)
        else:
            self.open_sound(path)

    def open_sound(self, path: str):
        path = Path(path)
        for i, editor in enumerate(self.editors()):
            if editor.doc.sound.path and editor.doc.sound.path.resolve() == path.resolve():
                self.tabs.setCurrentIndex(i)
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        progress = _LoadProgress(path.name, self)
        try:
            sound = Sound.from_file(path, progress)
        except SoundLoadCancelledError:
            return
        except SoundLoadError as err:
            sound, error = None, err
        finally:
            progress.close()
            QApplication.restoreOverrideCursor()
        if sound is None:
            QMessageBox.warning(self, "Could not open sound", str(error))
            return
        self.qsettings.setValue("last_dir", str(path.parent))
        self.prefs.add_recent_file(path)
        self._refresh_recent()

        doc = Document(sound)
        sibling = next(
            (path.with_suffix(ext) for ext in (".TextGrid", ".textgrid") if path.with_suffix(ext).exists()), None
        )
        if sibling:
            try:
                doc.set_textgrid(TextGrid.read(sibling), sibling)
                self.show_message(f"Loaded annotations from {sibling.name}")
            except TextGridError as err:
                self.show_message(f"Ignored {sibling.name}: {err}")
        self._add_editor(doc)

    def _add_editor(self, doc: Document):
        editor = SoundEditor(doc, self.prefs, self.player)
        editor.message.connect(self.show_message)
        editor.log.connect(self.log_panel.append)
        editor.new_sound.connect(self.open_new_sound)
        editor.formant_path_ready.connect(lambda result, ed=editor: self._show_formant_path(ed, result))
        editor.busy_changed.connect(lambda n, b, ed=editor: self._on_busy(ed, n, b))
        doc.title_changed.connect(lambda _t, ed=editor: self._on_title_changed(ed))
        doc.textgrid_changed.connect(self._update_actions)
        self.undo_group.addStack(doc.undo_stack)
        i = self.tabs.addTab(editor, doc.title)
        self.tabs.setTabToolTip(i, str(doc.sound.path or ""))
        self.tabs.setCurrentIndex(i)

    def open_textgrid_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open TextGrid", self._last_dir(), TEXTGRID_FILTER)
        if path:
            self.open_textgrid(path)

    def open_textgrid(self, path: str):
        # Prefer the open sound with the same name, e.g. when dropping a TextGrid.
        stem = Path(path).stem
        for i, ed in enumerate(self.editors()):
            if ed.doc.sound.name == stem:
                self.tabs.setCurrentIndex(i)
                break
        editor = self.editor
        if editor is None:
            QMessageBox.information(self, "Open TextGrid", "Open the sound this TextGrid belongs to first.")
            return
        if not self._confirm_discard(editor):
            return
        try:
            tg = TextGrid.read(path)
        except (OSError, TextGridError) as err:
            QMessageBox.warning(self, "Could not open TextGrid", str(err))
            return
        if abs(tg.xmax - editor.doc.sound.duration) > 0.01:
            self.show_message(
                f"Note: TextGrid duration {tg.xmax:.3f} s differs from sound {editor.doc.sound.duration:.3f} s"
            )
        editor.doc.set_textgrid(tg, Path(path))

    def new_textgrid(self):
        editor = self.editor
        if editor is None or not self._confirm_discard(editor):
            return
        dialog = NewTextGridDialog(self)
        if dialog.exec():
            intervals, points = dialog.tier_names()
            if not intervals and not points:
                intervals = ["words"]
            tg = TextGrid.for_duration(editor.doc.sound.duration, intervals, points)
            editor.doc.set_textgrid(tg, saved=False)
            editor.textgrid_view.setFocus()

    def open_new_sound(self, sound: Sound):
        """Open a sound made inside PhonoLab (it has no file until saved)."""
        self._add_editor(Document(sound))

    def _derive(self, fn, settings_cls=None):
        """Run a sound operation on the current sound and open the result in a new tab."""
        editor = self.editor
        if editor.doc.sound.is_long and fn is not sound_ops.extract:
            self.show_message(EXTRACT_FIRST)
            return
        args = ()
        if settings_cls is not None:
            key = f"op_{settings_cls.__name__}"
            dialog = SettingsDialog(self.prefs.analysis_settings(key, settings_cls), self)
            if not dialog.exec():
                return
            settings = dialog.value()
            self.prefs.set_analysis_settings(key, settings)
            args = (settings,)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result, error = fn(editor.doc.sound, *args), None
        except Exception as err:  # Praat errors, e.g. a band above the Nyquist frequency
            result, error = None, err
        finally:
            QApplication.restoreOverrideCursor()
        if error is not None:
            QMessageBox.warning(self, "Sound operation failed", str(error))
            return
        self.open_new_sound(result)

    def extract_selection(self):
        sel = self.editor.axis.selection
        if not sel:
            self.show_message("Select a part of the sound first")
            return
        try:
            self.open_new_sound(sound_ops.extract(self.editor.doc.sound, *sel))
        except LongSoundError as err:
            self.show_message(str(err))

    def concatenate_sounds(self):
        if any(ed.doc.sound.is_long for ed in self.editors()):
            self.show_message(EXTRACT_FIRST)
            return
        try:
            sound = sound_ops.concatenate([ed.doc.sound for ed in self.editors()])
        except ValueError as err:
            QMessageBox.warning(self, "Concatenate", str(err))
            return
        self.open_new_sound(sound)

    def new_sound(self):
        key = "op_ToneSettings"
        dialog = SettingsDialog(self.prefs.analysis_settings(key, sound_ops.ToneSettings), self)
        if dialog.exec():
            self.prefs.set_analysis_settings(key, dialog.value())
            self.open_new_sound(sound_ops.generate(dialog.value()))

    def synthesize_vowel(self):
        key = "op_VowelSettings"
        dialog = SettingsDialog(self.prefs.analysis_settings(key, sound_ops.VowelSettings), self)
        if dialog.exec():
            self.prefs.set_analysis_settings(key, dialog.value())
            try:
                sound = sound_ops.synthesize_vowel(dialog.value())
            except Exception as err:  # Praat rejects e.g. formants above the Nyquist frequency
                QMessageBox.warning(self, "Synthesize vowel", str(err))
                return
            self.open_new_sound(sound)

    def record(self):
        dialog = RecordDialog(self)
        if dialog.exec() and dialog.sound is not None:
            self.open_new_sound(dialog.sound)

    def save_sound_as(self, editor: SoundEditor | None = None) -> bool:
        editor = editor or self.editor
        doc = editor.doc
        default = doc.sound.path or Path(self._last_dir()) / f"{doc.sound.name}.wav"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save sound", str(default),
            "WAV (*.wav);;FLAC (*.flac);;AIFF (*.aiff);;OGG Vorbis (*.ogg);;MP3 (*.mp3)",
        )  # fmt: skip
        if not path:
            return False
        try:
            doc.save_sound(Path(path))
        except Exception as err:  # libsndfile errors for unsupported format/rate combinations
            QMessageBox.warning(self, "Could not save sound", str(err))
            return False
        self.prefs.add_recent_file(path)
        self._refresh_recent()
        self.tabs.setTabToolTip(self.tabs.indexOf(editor), path)
        self.show_message(f"Saved {Path(path).name}")
        return True

    def _refresh_recent(self):
        self.recent_menu.clear()
        recent = self.prefs.recent_files()
        for p in recent:
            self.recent_menu.addAction(Path(p).name, lambda path=p: self.open_sound(path)).setToolTip(p)
        if recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", self._clear_recent)
        self.recent_menu.setEnabled(bool(recent))
        self.start_page.set_recent(recent)

    def _clear_recent(self):
        self.prefs.clear_recent_files()
        self._refresh_recent()

    # ------------------------------------------------------------------ saving / closing

    def save_textgrid(self, editor: SoundEditor | None = None) -> bool:
        editor = editor or self.editor
        if editor.doc.textgrid_path is None:
            return self.save_textgrid_as(editor)
        return self._write_textgrid(editor, editor.doc.textgrid_path)

    def save_textgrid_as(self, editor: SoundEditor | None = None) -> bool:
        editor = editor or self.editor
        doc = editor.doc
        default = doc.textgrid_path or (doc.sound.path.with_suffix(".TextGrid") if doc.sound.path else None)
        path, chosen = QFileDialog.getSaveFileName(
            self,
            "Save TextGrid",
            str(default or ""),
            "TextGrid (*.TextGrid);;TextGrid, short format (*.TextGrid)",
        )
        if not path:
            return False
        return self._write_textgrid(editor, Path(path), short="short" in chosen)

    def _write_textgrid(self, editor: SoundEditor, path: Path, short: bool = False) -> bool:
        try:
            editor.doc.save_textgrid(path, short=short)
        except OSError as err:
            QMessageBox.warning(self, "Could not save TextGrid", str(err))
            return False
        self.show_message(f"Saved {path.name}")
        return True

    def _confirm_discard(self, editor: SoundEditor) -> bool:
        """Ask to save an unsaved sound and/or annotations. Returns False if the user cancels."""
        buttons = QMessageBox.StandardButton
        doc = editor.doc
        audio_discarded = False
        if doc.sound_needs_saving:
            kind = "new" if doc.sound_unsaved else "edited"
            answer = QMessageBox.question(
                self, "Unsaved sound", f"Save the {kind} sound “{doc.sound.name}”?",
                buttons.Save | buttons.Discard | buttons.Cancel,
            )  # fmt: skip
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save_sound_as(editor)):
                return False
            audio_discarded = answer == buttons.Discard and doc.audio_dirty
        # Corrections and annotations follow audio edits, so without those edits their times would be wrong.
        if editor.doc.corrections_dirty and not audio_discarded:
            answer = QMessageBox.question(
                self, "Unsaved corrections", f"Save your corrections to “{editor.doc.sound.name}”?",
                buttons.Save | buttons.Discard | buttons.Cancel,
            )  # fmt: skip
            if answer == buttons.Cancel or (answer == buttons.Save and not self.save_corrections(editor)):
                return False
        if not editor.doc.textgrid_dirty:
            return True
        warning = "Its times follow the audio edits you just discarded. " if audio_discarded else ""
        answer = QMessageBox.question(
            self,
            "Unsaved annotations",
            f"{warning}Save changes to the TextGrid of “{editor.doc.sound.name}”?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_textgrid(editor)
        return answer == QMessageBox.StandardButton.Discard

    def close_tab(self, index: int):
        editor = self.tabs.widget(index)
        if editor is None or not self._confirm_discard(editor):
            return
        editor.stop()
        editor.manager.close()
        self.undo_group.removeStack(editor.doc.undo_stack)
        self.tabs.removeTab(index)
        editor.deleteLater()
        self._on_tab_changed()
        # Long sounds: delete the working file once the deleted editor has let go of it.
        QTimer.singleShot(RELEASE_DELAY_MS, editor.doc.sound.release)

    def closeEvent(self, ev):  # noqa: N802
        for i, editor in enumerate(self.editors()):
            self.tabs.setCurrentIndex(i)
            if not self._confirm_discard(editor):
                ev.ignore()
                return
        for tier_window in self.findChildren(TierWindow):
            if not tier_window.close():
                ev.ignore()
                return
        self.player.stop()
        for editor in self.editors():
            editor.manager.close()
            atexit.register(editor.doc.sound.release)
        self.qsettings.setValue("window/geometry", self.saveGeometry())
        self._show_docks(True)  # save the user's dock layout, not the start page's
        self.qsettings.setValue("window/state", self.saveState())
        ev.accept()

    # ------------------------------------------------------------------ export

    def _save_path(self, title: str, suffix: str, filter_: str) -> Path | None:
        doc = self.editor.doc
        base = doc.sound.path.with_suffix(suffix) if doc.sound.path else Path(self._last_dir()) / f"untitled{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, title, str(base), filter_)
        return Path(path) if path else None

    def export_selection(self):
        path = self._save_path("Export selection", "_part.wav", "WAV (*.wav)")
        if path:
            self._run_export(lambda: self.editor.export_selection(path), path)

    def export_table(self, name: str):
        path = self._save_path(f"Export {name}", f"_{name}.csv", "CSV (*.csv)")
        if path:
            self._run_export(lambda: self.editor.export_table(name, path), path)

    def export_annotations(self):
        path = self._save_path("Export annotations", "_annotations.csv", "CSV (*.csv)")
        if path:
            self._run_export(lambda: self.editor.export_textgrid_table(path), path)

    def export_image(self):
        path = self._save_path("Export view as image", ".png", "PNG image (*.png)")
        if path:
            self._run_export(lambda: self.editor.grab().save(str(path)), path)

    def _run_export(self, fn, path: Path):
        try:
            fn()
        except Exception as err:  # surface any I/O or encoding problem to the user
            log.exception("export failed")
            QMessageBox.warning(self, "Export failed", str(err))
        else:
            self.show_message(f"Exported {path.name}")

    # ------------------------------------------------------------------ dialogs

    def edit_settings(self, name: str):
        editor = self.editor
        dialog = SettingsDialog(editor.manager.settings[name], self)
        if dialog.exec():
            settings = dialog.value()
            for ed in self.editors():
                ed.apply_settings(name, settings)

    def _show_formant_path(self, editor: SoundEditor, result):
        dialog = FormantPathDialog(result, editor.manager.settings["formants"].max_formant, self)
        if dialog.exec():
            editor.use_formant_ceiling(dialog.ceiling)

    def _show_spectrum(self, log: bool = False):
        self.spectrum_panel.show()
        self.spectrum_panel.raise_()
        self.spectrum_panel.update_spectrum()
        if log:
            self.spectrum_panel.log_measurements()

    def _edit_spectrum_settings(self):
        dialog = SettingsDialog(self.spectrum_panel.settings, self)
        if dialog.exec():
            settings = dialog.value()
            self.prefs.set_analysis_settings("spectrum", settings)
            self.spectrum_panel.set_settings(settings)

    def _show_manipulation(self):
        self.set_layer("manipulation", True)
        self._layer_actions["manipulation"].setChecked(True)

    def _ask_number(self, title: str, label: str, value: float, lo: float, hi: float, decimals: int = 2):
        number, ok = QInputDialog.getDouble(self, title, label, value, lo, hi, decimals)
        return number if ok else None

    def _stylize_pitch(self):
        if (st := self._ask_number("Stylize pitch", "Frequency resolution (semitones):", 2.0, 0.1, 12.0)) is not None:
            self.editor.stylize_pitch(st)

    def _shift_pitch(self):
        if (st := self._ask_number("Shift pitch", "Shift by (semitones):", 2.0, -48.0, 48.0)) is not None:
            self.editor.shift_pitch(st)

    def _set_duration(self):
        factor = self._ask_number("Set duration", "Relative duration (1 = unchanged):", 1.5, 0.05, 20.0)
        if factor is not None:
            self.editor.set_duration_factor(factor)

    def _set_loudness(self):
        decibels = self._ask_number("Set loudness", "Change by (dB):", 6.0, -60.0, 60.0, 1)
        if decibels is not None:
            self.editor.set_loudness(decibels)

    def _save_pitch_tier(self):
        editor = self.editor
        state = editor.doc.manipulation
        if state is None:
            self.show_message("Show the manipulation first")
            return
        path = self._save_path("Save pitch tier", ".PitchTier", "PitchTier (*.PitchTier)")
        if path:
            tier = TierFile("PitchTier", 0.0, editor.doc.sound.duration, state.pitch)
            self._run_export(lambda: tier.save(path), path)

    def open_tier_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open tier", self._last_dir(), TIER_FILTER)
        if path:
            self.open_tier(path)

    def open_tier(self, path: str):
        try:
            tier = read_tier(path)
        except (OSError, TierFileError) as err:
            QMessageBox.warning(self, "Could not open tier", str(err))
            return
        window = TierWindow(tier, Path(path), self)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()

    def _edit_manipulation_settings(self):
        dialog = SettingsDialog(self.editor.manipulation_settings, self)
        if dialog.exec():
            for ed in self.editors():
                ed.apply_manipulation_settings(dialog.value())

    def show_script_window(self):
        if self.script_window is None:
            self.script_window = ScriptWindow(lambda: self.editor, self)
            self.script_window.result_ready.connect(self._on_script_result)
        self.script_window.show()
        self.script_window.raise_()
        self.script_window.activateWindow()

    def save_corrections(self, editor: SoundEditor | None = None) -> bool:
        editor = editor or self.editor
        if editor.doc.sound_needs_saving and not self.save_sound_as(editor):
            return False  # corrections live next to the sound and follow its timing, so save it first
        try:
            path = editor.doc.save_corrections()
        except OSError as err:
            QMessageBox.warning(self, "Could not save corrections", str(err))
            return False
        self.show_message(f"Saved {path.name}")
        return True

    def _on_script_result(self, result, editor):
        for name, samples, sr in result.sounds:
            self.open_new_sound(Sound(samples, sr, title=name))
        if result.textgrid is None or editor not in self.editors():
            return
        doc, new = editor.doc, result.textgrid
        if doc.textgrid is None:
            doc.set_textgrid(new, saved=False)
            return

        def replace(tg):
            tg.xmin, tg.xmax, tg.tiers[:] = new.xmin, new.xmax, new.tiers

        doc.edit("Script", replace)

    def make_figure(self):
        dialog = FigureDialog(self.editor, self.prefs.analysis_settings("figure", FigureSettings), self)
        dialog.exec()
        self.prefs.set_analysis_settings("figure", dialog.settings())

    def batch_measure(self):
        p = self.prefs
        options = BatchOptions(
            pitch=p.analysis_settings("pitch"), formants=p.analysis_settings("formants"),
            intensity=p.analysis_settings("intensity"), voice=p.analysis_settings("pulses"),
        )  # fmt: skip
        BatchDialog(options, self._last_dir(), self).exec()

    def _voice_report(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.editor.query_voice_report()
        except Exception as err:  # Praat raises PraatError for e.g. too-short selections
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Voice report", f"Could not compute a voice report: {err}")
            return
        QApplication.restoreOverrideCursor()

    def show_shortcuts(self):
        html = ["<table cellspacing=4>"]
        for section, rows in SHORTCUTS:
            html.append(f"<tr><td colspan=2><b><br>{section}</b></td></tr>")
            html += [f"<tr><td><code>{k}</code>&nbsp;&nbsp;</td><td>{v}</td></tr>" for k, v in rows]
        html.append("</table>")
        QMessageBox.information(self, "Keyboard shortcuts", "".join(html))

    def show_about(self):
        QMessageBox.about(
            self,
            "About PhonoLab",
            f"<h3>PhonoLab {__version__}</h3>"
            "<p>Acoustic analysis and annotation for speech.</p>"
            f"<p>Measurements by {praat_engine.engine_description()}.<br>"
            f"Spectrograms and manipulation by Parselmouth {parselmouth.VERSION} "
            f"(Praat {parselmouth.PRAAT_VERSION}).</p>"
            "<p>Licensed under the GNU GPL v3 or later.</p>",
        )

    # ------------------------------------------------------------------ drag and drop

    def dragEnterEvent(self, ev):  # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):  # noqa: N802
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        # Sounds first so a dropped sound + TextGrid pair ends up together.
        paths.sort(key=lambda p: Path(p).suffix.lower() == ".textgrid")
        for p in paths:
            self.open_path(p)
        ev.acceptProposedAction()
