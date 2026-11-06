import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QAction, QCloseEvent, QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from phonolab.core.textgrid import TextGrid  # noqa: E402
from phonolab.ui.theme import configure_pyqtgraph  # noqa: E402
from tests.conftest import make_vowel  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    # Keep the user's real preferences out of tests.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    configure_pyqtgraph()
    from phonolab.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    # Never block on modal dialogs in tests.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    return w


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "vowel.wav"
    make_vowel(duration=1.0).save(path)
    return path


def wait_for_analyses(qtbot, editor):
    qtbot.waitUntil(
        lambda: {"pitch", "formants", "intensity", "spectrogram"} <= set(editor.manager.results), timeout=10000
    )


def test_open_sound_and_query(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    assert editor is not None and window.tabs.count() == 1
    wait_for_analyses(qtbot, editor)
    editor.axis.set_cursor(0.5)
    editor.query_pitch()
    assert "120" in window.log_panel.text.toPlainText()
    # Opening the same file again just focuses its tab.
    window.open_sound(str(wav))
    assert window.tabs.count() == 1


def test_annotate_undo_and_save(window, qtbot, wav, tmp_path):
    window.open_sound(str(wav))
    editor = window.editor
    doc = editor.doc
    doc.set_textgrid(TextGrid.for_duration(doc.sound.duration, ["words"]))
    view = editor.textgrid_view
    view.setFocus()
    editor.axis.set_cursor(0.4)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert doc.textgrid.tiers[0].boundaries == [pytest.approx(0.4)]
    qtbot.keyClicks(view, "ba")
    assert doc.textgrid.tiers[0].intervals[0].text == "ba"
    assert doc.is_dirty and window.windowTitle().startswith("vowel*")

    doc.undo_stack.undo()  # typing merges into a single step
    assert doc.textgrid.tiers[0].intervals[0].text == ""
    doc.undo_stack.undo()
    assert doc.textgrid.tiers[0].boundaries == []
    doc.undo_stack.redo()
    doc.undo_stack.redo()

    out = tmp_path / "out.TextGrid"
    window._write_textgrid(editor, out)
    assert not doc.is_dirty
    assert TextGrid.read(out).tiers[0].intervals[0].text == "ba"


def test_sibling_textgrid_loads_automatically(window, wav):
    tg = TextGrid.for_duration(1.0, ["words"])
    tg.tiers[0].set_text(0, "hello")
    tg.write(wav.with_suffix(".TextGrid"))
    window.open_sound(str(wav))
    assert window.editor.doc.textgrid.tiers[0].intervals[0].text == "hello"


def test_zoom_and_layers(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    editor.axis.zoom(0.25, 0.5)
    start, end = editor.axis.view
    assert end - start == pytest.approx(0.25)
    assert editor.scrollbar.value() == int(start * 1000)
    editor.set_layer_visible("spectrogram", False)
    editor.set_layer_visible("pitch", False)
    editor.set_layer_visible("formants", False)
    editor.set_layer_visible("intensity", False)
    assert not editor.spectrogram.isVisibleTo(window)
    editor.set_layer_visible("pitch", True)
    assert editor.spectrogram.isVisibleTo(window)


def test_export_tables(window, qtbot, wav, tmp_path):
    window.open_sound(str(wav))
    editor = window.editor
    editor.axis.set_selection(0.2, 0.4)
    editor.export_table("formants", tmp_path / "f.csv")
    lines = (tmp_path / "f.csv").read_text().splitlines()
    assert lines[0].startswith("time_s,F1_hz")
    assert all(0.2 <= float(line.split(",")[0]) <= 0.4 for line in lines[1:])
    editor.export_selection(tmp_path / "part.wav")
    from phonolab.core.sound import Sound

    assert Sound.from_file(tmp_path / "part.wav").duration == pytest.approx(0.2, abs=1e-3)


def test_ipa_palette_inserts_into_label(window, wav):
    window.open_sound(str(wav))
    editor = window.editor
    doc = editor.doc
    doc.set_textgrid(TextGrid.for_duration(doc.sound.duration, ["phones"]))
    editor.textgrid_view.select(0, 0)
    editor._insert_symbol("ə")
    assert doc.textgrid.tiers[0].intervals[0].text == "ə"


def test_pulses_layer_and_voice_report(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    assert not editor.layer_visible("pulses")  # off by default, as in Praat
    editor.set_layer_visible("pulses", True)
    qtbot.waitUntil(lambda: len(editor.waveform.pulse_times) > 50, timeout=10000)
    editor.axis.set_selection(0.2, 0.8)
    report = editor.query_voice_report()
    assert report.value("Number of pulses") is not None
    assert "Jitter (local)" in window.log_panel.text.toPlainText()


def test_spectrum_panel_follows_selection(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    window._show_spectrum()
    editor.axis.set_selection(0.2, 0.4)
    window.spectrum_panel.update_spectrum()
    r = window.spectrum_panel.result
    assert r is not None and (r.start, r.end) == (0.2, 0.4)
    window.spectrum_panel.log_cpps()  # runs in a worker
    qtbot.waitUntil(lambda: "CPPS" in window.log_panel.text.toPlainText(), timeout=30000)


def test_derived_sound_opens_unsaved_and_saves(window, wav, tmp_path, monkeypatch):
    from phonolab.core import sound_ops

    window.open_sound(str(wav))
    window.editor.axis.set_selection(0.1, 0.4)
    window.extract_selection()
    assert window.tabs.count() == 2
    doc = window.editor.doc
    assert doc.sound_unsaved and doc.title.endswith("*")
    monkeypatch.setattr(
        "phonolab.ui.main_window.QFileDialog.getSaveFileName", lambda *a, **k: (str(tmp_path / "part.flac"), "")
    )
    assert window.save_sound_as()
    assert not doc.is_dirty and doc.sound.path == tmp_path / "part.flac"
    window._derive(sound_ops.reverse)
    assert window.tabs.count() == 3


def test_manipulation_edit_undo_and_resynthesis(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    state = editor.doc.manipulation
    original = state.pitch
    editor.shift_pitch(12)
    assert np.median(state.pitch.values) == pytest.approx(2 * np.median(original.values))
    assert not editor.doc.textgrid_dirty  # pitch edits are not annotation edits
    editor.doc.undo_stack.undo()
    assert state.pitch == original
    editor.doc.undo_stack.redo()
    editor.open_resynthesis()
    qtbot.waitUntil(lambda: window.tabs.count() == 2, timeout=15000)
    assert window.editor.doc.sound.name == "vowel_manipulated"


def test_batch_dialog_writes_csv(qtbot, tmp_path):
    from phonolab.core import batch
    from phonolab.core.batch import BatchOptions
    from phonolab.ui.dialogs.batch_dialog import BatchDialog

    for i, f0 in enumerate((110, 150)):
        make_vowel(f0=f0, duration=0.5).save(tmp_path / f"s{i}.wav")
    dialog = BatchDialog(BatchOptions(measures=frozenset({"pitch", "intensity"})), str(tmp_path))
    qtbot.addWidget(dialog)
    out = tmp_path / "results.csv"
    dialog.start(batch.find_sounds(tmp_path), out)
    qtbot.waitUntil(out.exists, timeout=60000)
    text = out.read_text(encoding="utf-8")
    assert "s0.wav" in text and "s1.wav" in text and "f0_mean_hz" in text


def test_script_window_runs_in_worker(window, qtbot, wav):
    window.open_sound(str(wav))
    window.show_script_window()
    sw = window.script_window
    sw.language.setCurrentIndex(sw.language.findData("python"))
    sw.editor.setPlainText(
        "print('hello')\nnew_sounds = [Sound(sound.samples[::2], sound.sampling_rate / 2, title='half')]"
    )
    sw.run_or_stop()
    qtbot.waitUntil(lambda: window.tabs.count() == 2, timeout=30000)
    assert "hello" in sw.output.toPlainText()
    # An endless loop can be stopped.
    sw.editor.setPlainText("while True: pass")
    sw.run_or_stop()
    assert sw.run_button.text() == "Stop"
    sw.run_or_stop()
    assert "Stopped" in sw.output.toPlainText()


def test_figure_dialog_renders_and_saves(window, wav, tmp_path):
    from phonolab.core.figures import FigureSettings
    from phonolab.ui.dialogs.figure_dialog import FigureDialog

    window.open_sound(str(wav))
    window.editor.axis.set_selection(0.1, 0.6)
    dialog = FigureDialog(window.editor, FigureSettings(dpi=100), window)
    assert dialog.render_preview() and not dialog.preview.pixmap().isNull()
    dialog.save(tmp_path / "f.svg")
    assert (tmp_path / "f.svg").read_text(encoding="utf-8").startswith("<?xml")


def test_find_bar_steps_through_matches_and_duplicate_tier(window, wav):
    window.open_sound(str(wav))
    editor = window.editor
    tg = TextGrid.for_duration(1.0, ["words"])
    for t in (0.25, 0.5, 0.75):
        tg.tiers[0].add_boundary(t)
    for i, text in enumerate(["cat", "dog", "catalog", ""]):
        tg.tiers[0].set_text(i, text)
    editor.doc.set_textgrid(tg)
    bar = editor.find_bar
    bar.open_bar()
    bar.field.setText("cat")
    assert bar.count.text() == "2 matches"
    assert bar.step(1) and editor.textgrid_view.selected_item == 0
    assert bar.step(1) and editor.textgrid_view.selected_item == 2
    assert bar.step(1) and editor.textgrid_view.selected_item == 0  # wraps around
    editor.textgrid_view.duplicate_tier(0)
    assert [t.name for t in editor.doc.textgrid.tiers] == ["words", "words_copy"]
    editor.doc.undo_stack.undo()
    assert len(editor.doc.textgrid.tiers) == 1


def test_theme_switching_and_preference(qtbot):
    from PyQt6.QtWidgets import QApplication

    from phonolab.core.settings import MemoryStore, Preferences
    from phonolab.ui import theme

    app = QApplication.instance()
    try:
        assert theme.apply_theme(app, "dark") == "dark"
        assert theme.COLORS["background"] == theme.THEMES["dark"]["background"]
        assert app.palette().color(app.palette().ColorRole.Window).name() == theme.UI["dark"]["window"]
    finally:
        theme.apply_theme(app, "light")  # other tests expect the light theme
    assert theme.THEMES["light"] == theme.COLORS
    prefs = Preferences(MemoryStore())
    assert prefs.theme() == "system"
    prefs.set_theme("dark")
    assert prefs.theme() == "dark"


def test_alt_backspace_removes_boundary_not_undo(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    editor.doc.set_textgrid(TextGrid.for_duration(1.0, ["words"]))
    view = editor.textgrid_view
    view.setFocus()
    editor.axis.set_cursor(0.3)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    editor.axis.set_cursor(0.6)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    qtbot.keyClick(view, Qt.Key.Key_Backspace, Qt.KeyboardModifier.AltModifier)
    # The boundary at the cursor (0.6) is removed; the one at 0.3 stays.
    assert editor.doc.textgrid.tiers[0].boundaries == [pytest.approx(0.3)]
    shortcuts = {a.text(): [k.toString() for k in a.shortcuts()] for a in window.findChildren(QAction)}
    assert shortcuts["&Quit"] == ["Ctrl+Q"]


def test_voicing_bar_and_tier(window, qtbot, tmp_path):
    from phonolab.core.sound import Sound

    x = np.concatenate([make_vowel(duration=0.3).mono, np.zeros(4800), make_vowel(duration=0.3).mono])
    path = tmp_path / "vuv.wav"
    Sound(x, 16000).save(path)
    window.open_sound(str(path))
    editor = window.editor
    assert editor.layer_visible("voicing")  # on by default
    qtbot.waitUntil(lambda: editor.voicing_bar.result is not None, timeout=15000)
    assert len(editor.voicing_bar.result.starts) == 2
    assert editor.readout(0.1, None)["Voicing"] == "voiced"
    editor.add_voicing_tier()
    tier = editor.doc.textgrid.tiers[-1]
    assert tier.name == "voicing" and [iv.text for iv in tier.intervals][1:4] == ["V", "U", "V"]
    editor.doc.undo_stack.undo()
    assert editor.doc.textgrid.tiers == []


def test_docks_hidden_on_start_page_and_restored(window, wav):
    assert not window.info_panel.isVisible()  # start page
    window.open_sound(str(wav))
    assert window.info_panel.isVisible()
    window.close_tab(0)
    assert not window.info_panel.isVisible()
    window.open_sound(str(wav))
    assert window.info_panel.isVisible()


def test_mac_delete_key_removes_boundary(window, qtbot, wav, monkeypatch):
    window.open_sound(str(wav))
    editor = window.editor
    editor.doc.set_textgrid(TextGrid.for_duration(1.0, ["words"]))
    view = editor.textgrid_view
    view.setFocus()
    editor.axis.set_cursor(0.3)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    monkeypatch.setattr("phonolab.ui.editor.textgrid_pane.sys.platform", "win32")
    qtbot.keyClick(view, Qt.Key.Key_Backspace)  # plain Backspace does nothing outside macOS
    assert len(editor.doc.textgrid.tiers[0].boundaries) == 1
    monkeypatch.setattr("phonolab.ui.editor.textgrid_pane.sys.platform", "darwin")
    qtbot.keyClick(view, Qt.Key.Key_Backspace)
    assert editor.doc.textgrid.tiers[0].boundaries == []


def test_finder_file_open_event_opens_sound(window, wav):
    from PyQt6.QtCore import QEvent

    from phonolab.app import FileOpenFilter

    class FakeFileOpenEvent:  # PyQt doesn't allow constructing a real QFileOpenEvent
        def type(self):
            return QEvent.Type.FileOpen

        def file(self):
            return str(wav)

    assert FileOpenFilter(window).eventFilter(None, FakeFileOpenEvent())
    assert window.tabs.count() == 1 and window.editor.doc.sound.name == "vowel"


def test_queries_have_shortcuts_without_function_keys(window):
    shortcuts = {a.text(): [k.toString() for k in a.shortcuts()] for a in window.findChildren(QAction)}
    assert shortcuts["Get &pitch"] == ["F5", "Ctrl+1"]
    assert "Ctrl+G" in shortcuts["Find &next"]


def test_theme_switch_applies_live_to_open_editors(window, qtbot, wav):
    from phonolab.ui import theme

    window.open_sound(str(wav))
    editor = window.editor
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    qtbot.waitUntil(lambda: "spectrogram" in editor.manager.results, timeout=15000)
    colours = lambda: (  # noqa: E731
        editor.waveform.backgroundBrush().color().name(),
        editor.waveform.curves[0].opts["pen"].color().name(),
        editor.waveform.getAxis("left").textPen().color().name(),
        editor.overview.backgroundBrush().color().name(),
        editor.manipulation_pane.curve.opts["pen"].color().name(),
        window.spectrum_panel.curve.opts["pen"].color().name(),
    )

    def expected(name):
        c = theme.THEMES[name]
        return (c["background"], c["waveform"], c["foreground"], c["background"], c["manipulation"], c["waveform"])

    try:
        window._set_theme("dark")
        assert colours() == expected("dark")
        assert editor.spectrogram.image.lut[0][:3].tolist() == list(
            bytes.fromhex(theme.THEMES["dark"]["background"][1:])
        )
        window._set_theme("light")
        assert colours() == expected("light")
    finally:
        theme.apply_theme(QApplication.instance(), "light")


def test_system_theme_change_only_followed_in_system_mode(window, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "_apply_theme", lambda: calls.append(1))
    window.prefs.set_theme("dark")
    window._on_system_colours_changed()
    assert calls == []
    window.prefs.set_theme("system")
    window._on_system_colours_changed()
    assert calls == [1]


def test_start_page_actions_and_recent_files(window, qtbot, wav, monkeypatch):
    from phonolab.ui.start_page import ActionRow, speech_envelope

    page = window.start_page
    assert np.array_equal(speech_envelope(), speech_envelope())  # the drawing is fixed, not random per launch
    page.set_recent([])
    assert page.recent.isHidden() and not page.empty_hint.isHidden()
    page.set_recent([str(wav), str(wav.with_name("gone.wav"))])
    assert not page.recent.isHidden() and page.empty_hint.isHidden()
    with qtbot.waitSignal(page.open_path) as opened:
        page.recent.itemClicked.emit(page.recent.item(0))
    assert opened.args == [str(wav)]
    monkeypatch.setattr("phonolab.ui.main_window.QFileDialog.getOpenFileNames", lambda *a, **k: ([], ""))
    with qtbot.waitSignal(page.open_requested):
        page.findChildren(ActionRow)[0].click()
    page.grab()  # paints the delegate for both an existing and a missing file


@pytest.fixture
def long_window(window, tmp_path, monkeypatch):
    """A window holding a file treated as long, with analyses limited to half a second at a time."""
    from phonolab.core import sound as sound_module
    from phonolab.ui import workers

    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 1000)
    monkeypatch.setattr(workers, "MAX_WINDOW_SECONDS", 0.5)
    wav = tmp_path / "long.wav"
    make_vowel(duration=3.0).save(wav)
    window.open_sound(str(wav))
    assert window.editor.doc.sound.is_long
    return window


def test_long_sound_analyses_follow_the_zoom(long_window, qtbot):
    editor = long_window.editor
    manager = editor.manager
    assert not manager.analyses_available and manager.results == {}
    assert editor.spectrogram.hint.isVisible()
    editor.axis.set_view(0.3, 0.6)
    manager.set_spectrogram_range(0.3, 0.6)
    assert manager.analyses_available and manager.covers(0.3, 0.6)
    qtbot.waitUntil(lambda: {"pitch", "spectrogram", "voicing"} <= set(manager.results), timeout=20000)
    assert not editor.spectrogram.hint.isVisible()
    assert manager.results["pitch"].times[0] > 0  # placed on the whole sound's time axis
    editor.axis.set_cursor(0.45)
    editor.query_pitch()
    assert "120" in long_window.log_panel.text.toPlainText()
    # Moving elsewhere: old results must stop answering at once, even before new ones arrive.
    manager.set_spectrogram_range(2.2, 2.4)
    assert "pitch" not in manager.results and "voicing" not in manager.results
    assert editor.readout(2.3, None)["Pitch"] == "…"
    manager.set_spectrogram_range(0.0, 1.0)  # zoomed back out
    assert not manager.analyses_available and manager.results == {}
    assert editor.spectrogram.hint.isVisible()


def test_long_sound_refuses_partial_answers_and_whole_file_work(long_window):
    from phonolab.core import sound_ops

    editor = long_window.editor
    messages = []
    editor.message.connect(messages.append)
    long_window.statusBar().messageChanged.connect(messages.append)
    editor.axis.set_cursor(0.45)
    editor.query_pitch()  # zoomed out: no analysis to report
    assert any("Zoom in" in m for m in messages) and not long_window.log_panel.text.toPlainText()
    editor.axis.set_selection(0.1, 0.9)
    assert editor.readout(0.5, None).get("Pitch") is None
    long_window._derive(sound_ops.reverse)
    assert long_window.tabs.count() == 1 and any("Extract" in m for m in messages)
    assert editor.ensure_manipulation() is False
    long_window.extract_selection()  # the way out: an ordinary sound
    assert long_window.tabs.count() == 2 and not long_window.editor.doc.sound.is_long


def test_closing_a_long_sound_deletes_its_working_file(long_window, qtbot):
    folder = long_window.editor.doc.sound.long_folder
    assert (folder / "samples.f32").exists()
    long_window.close_tab(0)
    qtbot.waitUntil(lambda: not folder.exists(), timeout=5000)


def test_formant_ceiling_dialog_picks_and_applies(window, qtbot, wav, monkeypatch):
    from phonolab.core import praat_engine
    from phonolab.ui.dialogs.formant_path_dialog import FormantPathDialog
    from tests.test_formant_path import result

    window.open_sound(str(wav))
    editor = window.editor
    dialog = FormantPathDialog(result([5.0, 3.0, 4.0]), 5500.0, window)
    qtbot.addWidget(dialog)
    assert dialog.ceiling == 4500.0  # starts on the lowest stress
    dialog.tiles[2].chosen.emit(2)
    assert dialog.ceiling == 5000.0 and dialog.tiles[2].property("selected")
    editor.use_formant_ceiling(dialog.ceiling)
    assert editor.manager.settings["formants"].max_formant == 5000.0
    if praat_engine.available():  # the whole route, stopping at the dialog
        shown = []
        monkeypatch.setattr(window, "_show_formant_path", lambda ed, r: shown.append(r))
        editor.formant_path_ready.connect(shown.append)
        editor.axis.set_selection(0.2, 0.8)
        editor.compare_formant_ceilings()
        qtbot.waitUntil(lambda: bool(shown), timeout=30000)
        assert len(shown[0].candidates) == 9


def test_views_panel_shows_a_view_and_limits_range(window, qtbot, wav):
    from phonolab.core import praat_engine

    window.open_sound(str(wav))
    panel = window.views_panel
    panel.show()
    if praat_engine.available():
        window.editor.axis.set_selection(0.2, 0.8)
        panel.update_view()
        qtbot.waitUntil(lambda: panel.result is not None, timeout=20000)
        assert panel.image.image is not None and panel.status.text().startswith("Cepstrogram")
    panel.retheme()


def test_correcting_pitch_reaches_queries_undo_and_saving(window, qtbot, wav):
    from phonolab.core.corrections import Corrections

    window.open_sound(str(wav))
    editor = window.editor
    doc = editor.doc
    qtbot.waitUntil(lambda: "pitch" in editor.manager.results, timeout=15000)
    before = np.nanmedian(editor.manager.results["pitch"].frequencies)
    editor.axis.set_selection(0.0, 1.0)
    editor.correct_octave(2.0)
    assert np.nanmedian(editor.manager.results["pitch"].frequencies) == pytest.approx(2 * before)
    assert doc.corrections_dirty and doc.title.endswith("*")
    assert len(editor.spectrogram.raw_pitch_curve.getData()[0]) > 0  # the original stays visible
    editor.query_pitch()
    assert str(int(2 * before)) in window.log_panel.text.toPlainText()
    doc.undo_stack.undo()
    assert np.nanmedian(editor.manager.results["pitch"].frequencies) == pytest.approx(before)
    assert not doc.corrections_dirty
    doc.undo_stack.redo()
    assert window.save_corrections()
    assert not doc.corrections_dirty and Corrections.path_for(wav).exists()
    window.close_tab(0)
    window.open_sound(str(wav))  # corrections come back
    editor = window.editor
    qtbot.waitUntil(lambda: "pitch" in editor.manager.results, timeout=15000)
    assert np.nanmedian(editor.manager.results["pitch"].frequencies) == pytest.approx(2 * before)
    editor.axis.clear_selection()
    editor.correct_restore()
    assert window.save_corrections() and not Corrections.path_for(wav).exists()


def test_correcting_needs_a_selection_and_prompts_on_close(window, wav, monkeypatch):
    window.open_sound(str(wav))
    editor = window.editor
    messages = []
    editor.message.connect(messages.append)
    editor.correct_unvoice()
    assert editor.doc.corrections.is_empty and "Select" in messages[-1]
    editor.axis.set_selection(0.2, 0.3)
    editor.correct_unvoice()
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: asked.append(a[1]) or QMessageBox.StandardButton.Discard
    )
    window.close_tab(0)
    assert asked == ["Unsaved corrections"]


def test_loudness_edit_is_undoable_and_labelled(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    state = editor.doc.manipulation
    editor.axis.set_selection(0.2, 0.4)
    editor.set_loudness(6.0)
    assert len(state.gain) > 0 and state.is_modified
    assert any("loudness" in label.toPlainText() for label in editor.manipulation_pane.duration_labels)
    editor.doc.undo_stack.undo()
    assert len(state.gain) == 0


def test_tier_window_edits_and_saves(window, qtbot, tmp_path):
    from phonolab.core.tiers import read_tier
    from tests.test_tiers import make

    path = tmp_path / "t.PitchTier"
    make().save(path)
    window.open_path(str(path))
    from phonolab.ui.tier_window import TierWindow

    tier_window = window.findChild(TierWindow)
    assert tier_window is not None and len(tier_window.tier) == 2
    tier_window.add_point(1.0, 150.0)
    assert len(tier_window.tier) == 3 and tier_window.selected == 1 and tier_window.dirty
    tier_window.remove_selected()
    assert len(tier_window.tier) == 2
    tier_window.undo()
    assert len(tier_window.tier) == 3
    assert tier_window.save() and not tier_window.dirty
    assert len(read_tier(path).tier) == 3
    tier_window.close()


def open_tier_window(window, tmp_path):
    from phonolab.ui.tier_window import TierWindow
    from tests.test_tiers import make

    path = tmp_path / "t.PitchTier"
    make().save(path)
    window.open_path(str(path))
    return window.findChild(TierWindow)


def mouse(widget, kind, point, buttons, modifiers=Qt.KeyboardModifier.NoModifier):
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    event = QMouseEvent(kind, QPointF(point), QPointF(widget.mapToGlobal(point)), button, buttons, modifiers)
    QApplication.sendEvent(widget, event)


def scene_point(tier_window, time, value):
    plot = tier_window.plot
    return plot.mapFromScene(plot.getViewBox().mapViewToScene(QPointF(time, value)))


def test_dragging_a_tier_point_with_the_mouse(window, qtbot, tmp_path):
    tier_window = open_tier_window(window, tmp_path)
    qtbot.waitExposed(tier_window)
    viewport, left = tier_window.plot.viewport(), Qt.MouseButton.LeftButton
    start, end = scene_point(tier_window, 0.5, 100), scene_point(tier_window, 0.8, 150)
    mouse(viewport, QEvent.Type.MouseButtonPress, start, left)
    for step in (0.3, 0.7, 1.0):
        mouse(viewport, QEvent.Type.MouseMove, start + (end - start) * step, left)
    mouse(viewport, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    assert tier_window.tier.times[0] == pytest.approx(0.8, abs=0.02)
    assert tier_window.tier.values[0] == pytest.approx(150, abs=3)
    assert tier_window.dirty and len(tier_window.history) == 1
    tier_window.undo()
    assert tier_window.tier.times[0] == pytest.approx(0.5)
    tier_window.dirty = False


def test_dragging_empty_space_changes_nothing(window, qtbot, tmp_path):
    tier_window = open_tier_window(window, tmp_path)
    qtbot.waitExposed(tier_window)
    viewport, left = tier_window.plot.viewport(), Qt.MouseButton.LeftButton
    start, end = scene_point(tier_window, 1.0, 110), scene_point(tier_window, 1.3, 130)
    mouse(viewport, QEvent.Type.MouseButtonPress, start, left)
    mouse(viewport, QEvent.Type.MouseMove, (start + end) / 2, left)
    mouse(viewport, QEvent.Type.MouseMove, end, left)
    mouse(viewport, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
    assert not tier_window.dirty and not tier_window.history


@pytest.mark.parametrize("closer", ["close", "reject"])
def test_tier_window_asks_before_losing_edits(window, tmp_path, monkeypatch, closer):
    tier_window = open_tier_window(window, tmp_path)
    tier_window.add_point(1.0, 150.0)
    asked = []
    buttons = QMessageBox.StandardButton
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a) or buttons.Cancel)
    tier_window.show()
    getattr(tier_window, closer)()
    assert asked and tier_window.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: buttons.Discard)
    getattr(tier_window, closer)()
    assert not tier_window.isVisible()


def test_closing_the_app_can_be_stopped_by_an_unsaved_tier(window, tmp_path, monkeypatch):
    tier_window = open_tier_window(window, tmp_path)
    tier_window.add_point(1.0, 150.0)
    tier_window.show()
    buttons = QMessageBox.StandardButton
    monkeypatch.setattr(QMessageBox, "question", lambda *a: buttons.Cancel)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and tier_window.isVisible()
    tier_window.dirty = False


def test_loudness_menu_and_saving_the_pitch_tier(window, qtbot, wav, tmp_path, monkeypatch):
    from phonolab.core.tiers import read_tier

    window.open_sound(str(wav))
    editor = window.editor
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    editor.axis.set_selection(0.2, 0.4)
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *a: (-6.0, True))
    window._set_loudness()
    assert -6.0 in editor.doc.manipulation.gain.values
    target = tmp_path / "saved.PitchTier"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(target), ""))
    window._save_pitch_tier()
    saved = read_tier(target)
    assert saved.object_class == "PitchTier" and saved.tier == editor.doc.manipulation.pitch
    assert saved.xmax == pytest.approx(editor.doc.sound.duration)


def test_changing_loudness_invalidates_the_resynthesis(window, qtbot, wav):
    window.open_sound(str(wav))
    editor = window.editor
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    results = []
    editor._with_resynthesis(lambda samples, sr: results.append(samples))
    qtbot.waitUntil(lambda: len(results) == 1, timeout=20000)
    editor.axis.set_selection(0.2, 0.4)
    editor.set_loudness(-12.0)
    editor._with_resynthesis(lambda samples, sr: results.append(samples))
    qtbot.waitUntil(lambda: len(results) == 2, timeout=20000)
    assert results[1] is not results[0]
    assert np.abs(results[1]).sum() < np.abs(results[0]).sum()
