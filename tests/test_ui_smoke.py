import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtCore import QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

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


def test_spectrum_panel_follows_selection(window, wav):
    window.open_sound(str(wav))
    editor = window.editor
    window._show_spectrum()
    editor.axis.set_selection(0.2, 0.4)
    window.spectrum_panel.update_spectrum()
    r = window.spectrum_panel.result
    assert r is not None and (r.start, r.end) == (0.2, 0.4)
    window.spectrum_panel.log_cpps()
    assert "CPPS" in window.log_panel.text.toPlainText()


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
        assert app.palette().color(app.palette().ColorRole.Window).name() == "#2b2d31"
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
