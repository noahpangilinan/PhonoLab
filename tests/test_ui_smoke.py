import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import QSettings, Qt  # noqa: E402
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
