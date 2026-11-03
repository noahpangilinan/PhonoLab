"""Main window: tabbed documents, menus, docks and file handling."""

from __future__ import annotations

import logging
from pathlib import Path

import parselmouth
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QAction, QKeySequence, QUndoGroup
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
)

from phonolab import __version__
from phonolab.audio.player import AudioPlayer
from phonolab.core.analysis import ANALYSES
from phonolab.core.settings import Preferences
from phonolab.core.sound import SUPPORTED_EXTENSIONS, Sound, SoundLoadError
from phonolab.core.textgrid import TextGrid, TextGridError
from phonolab.ui.dialogs.new_textgrid import NewTextGridDialog
from phonolab.ui.dialogs.settings_dialog import SettingsDialog
from phonolab.ui.document import Document
from phonolab.ui.editor.sound_editor import LAYERS, SoundEditor
from phonolab.ui.info_panel import InfoPanel
from phonolab.ui.log_panel import LogPanel
from phonolab.ui.start_page import StartPage

log = logging.getLogger(__name__)

SOUND_FILTER = "Sound files (" + " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS) + ");;All files (*)"
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
            ("Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"),
        ],
    ),
    (
        "Measurements",
        [("F5", "Pitch at cursor or over selection"), ("F1", "Formants"), ("F8", "Intensity"), ("F2", "Duration")],
    ),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhonoLab")
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        self.qsettings = QSettings()
        self.prefs = Preferences(self.qsettings)
        self.player = AudioPlayer(self)
        self.undo_group = QUndoGroup(self)

        self.start_page = StartPage()
        self.start_page.open_requested.connect(self.open_dialog)
        self.start_page.open_path.connect(self.open_sound)
        self.tabs = QTabWidget(documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self.info_panel = InfoPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.info_panel)
        self.log_panel = LogPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_panel)
        self.log_panel.hide()

        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        self._busy: set[str] = set()

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
            self.restoreState(state)

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
        self._action(x, "View as &image (PNG)…", self.export_image, needs=e)
        m.addSeparator()
        self._action(
            m, "&Close", lambda: self.close_tab(self.tabs.currentIndex()), QKeySequence.StandardKey.Close, needs=e
        )
        self._action(m, "&Quit", self.close, QKeySequence.StandardKey.Quit)

        m = mb.addMenu("&Edit")
        undo = self.undo_group.createUndoAction(self, "&Undo")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        redo = self.undo_group.createRedoAction(self, "&Redo")
        redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        m.addActions([undo, redo])
        m.addSeparator()
        self._action(m, "Select &all", lambda: self.editor.axis.select_all(), "Ctrl+Shift+A", needs=e)

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
            action.setChecked(self.prefs.pane_visible(name))
            self._layer_actions[name] = action
        m.addSeparator()
        m.addAction(self.info_panel.toggleViewAction())
        m.addAction(self.log_panel.toggleViewAction())

        m = mb.addMenu("&Play")
        self._action(m, "&Play / Stop", lambda: self.editor.toggle_playback(), ["Space", "Tab"], needs=e)
        self._action(m, "&Stop", lambda: self.editor.stop(), "Esc", needs=e)
        self._action(m, "Play &whole sound", lambda: self.editor.play(0, self.editor.doc.sound.duration), needs=e)

        m = mb.addMenu("&Analysis")
        for name, (cls, _) in ANALYSES.items():
            self._action(m, f"{cls.title} settings…", lambda _=False, n=name: self.edit_settings(n), needs=e)

        m = mb.addMenu("&Query")
        self._action(m, "Get &pitch", lambda: self.editor.query_pitch(), "F5", needs=e)
        self._action(m, "Get &formants", lambda: self.editor.query_formants(), "F1", needs=e)
        self._action(m, "Get &intensity", lambda: self.editor.query_intensity(), "F8", needs=e)
        self._action(m, "Get &duration", lambda: self.editor.query_duration(), "F2", needs=e)

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
        self._action(m, "Re&move tier…", lambda: tv().remove_tier(), needs=tg)

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
        self.undo_group.setActiveStack(editor.doc.undo_stack if editor else None)
        self.info_panel.set_editor(editor)
        self._update_actions()
        self._busy.clear()
        self._update_busy()
        if editor:
            editor.setFocus()

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
        if Path(path).suffix.lower() == ".textgrid":
            self.open_textgrid(path)
        else:
            self.open_sound(path)

    def open_sound(self, path: str):
        path = Path(path)
        for i, editor in enumerate(self.editors()):
            if editor.doc.sound.path and editor.doc.sound.path.resolve() == path.resolve():
                self.tabs.setCurrentIndex(i)
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            sound = Sound.from_file(path)
        except SoundLoadError as err:
            sound, error = None, err
        finally:
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
            editor.doc.set_textgrid(TextGrid.for_duration(editor.doc.sound.duration, intervals, points))
            # A new grid is unsaved work: mark it dirty so closing prompts.
            editor.doc.undo_stack.resetClean()
            editor.doc.title_changed.emit(editor.doc.title)
            editor.textgrid_view.setFocus()

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
        """Ask to save unsaved annotations. Returns False if the user cancels."""
        if not editor.doc.is_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved annotations",
            f"Save changes to the TextGrid of “{editor.doc.sound.name}”?",
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

    def closeEvent(self, ev):  # noqa: N802
        for i, editor in enumerate(self.editors()):
            self.tabs.setCurrentIndex(i)
            if not self._confirm_discard(editor):
                ev.ignore()
                return
        self.player.stop()
        for editor in self.editors():
            editor.manager.close()
        self.qsettings.setValue("window/geometry", self.saveGeometry())
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
            f"<p>Analyses by Praat {parselmouth.PRAAT_VERSION} via Parselmouth {parselmouth.VERSION}.</p>"
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
