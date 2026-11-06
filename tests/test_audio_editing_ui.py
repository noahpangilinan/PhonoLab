"""Audio editing in the running app, with real worker processes, shortcuts and dialogs.

The core tests prove the arithmetic. These prove that every pane, cache and background job moves to the
new audio, including when an edit lands while analyses are still running.
"""

import gc
import os
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from multiprocessing import shared_memory  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from phonolab.core import praat_engine, registry  # noqa: E402
from phonolab.core.corrections import Corrections  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.core.textgrid import TextGrid  # noqa: E402
from tests.conftest import make_sine, make_vowel  # noqa: E402
from tests.test_ui_smoke import long_window, wait_for_analyses, wav, window  # noqa: E402, F401

Buttons = QMessageBox.StandardButton


def opened(window, wav, qtbot):  # noqa: F811
    window.open_sound(str(wav))
    wait_for_analyses(qtbot, window.editor)
    return window.editor


def action(window, text):  # noqa: F811
    for a in window.findChildren(QAction):
        if a.text().replace("&", "") == text:
            return a
    raise AssertionError(f"no action {text}")


def settled(qtbot, editor):
    """Wait for analyses of the current audio, and check nothing is left marked as running."""
    wait_for_analyses(qtbot, editor)
    for name in ("pitch", "formants", "intensity"):
        assert editor.manager.results[name] is not None


def assert_matches_sound(editor):
    """The results on screen must be exactly what analysing the current audio gives."""
    manager, sound = editor.manager, editor.doc.sound
    fresh = registry.compute("pitch", sound, manager.settings)
    shown = manager.raw_results["pitch"]
    assert np.array_equal(shown.times, fresh.times)
    assert np.allclose(shown.frequencies, fresh.frequencies, equal_nan=True)


# ---------------------------------------------------------------------- everything moves to the new audio


def test_cut_updates_every_pane(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    sound = editor.doc.sound
    assert sound.duration == pytest.approx(0.75)
    assert editor.axis.duration == pytest.approx(0.75) and editor.axis.view == (0.0, pytest.approx(0.75))
    assert editor.axis.selection is None and editor.axis.cursor == pytest.approx(0.25)
    assert editor.manager.sound is sound and editor.waveform.sound is sound
    assert len(editor.waveform.envelopes[0].signal) == sound.n_samples
    assert editor.scrollbar.maximum() == 0
    assert editor.overview.curve.getData()[0].max() <= 0.75 + 1e-3
    settled(qtbot, editor)
    assert_matches_sound(editor)
    assert editor.manager.results["pitch"].times.max() < 0.75


def test_undo_and_redo_bring_results_back_to_each_version(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    original = editor.doc.sound.samples.copy()
    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    settled(qtbot, editor)
    editor.doc.undo_stack.undo()
    assert np.array_equal(editor.doc.sound.samples, original) and editor.axis.duration == pytest.approx(1.0)
    settled(qtbot, editor)
    assert_matches_sound(editor)
    editor.doc.undo_stack.redo()
    assert editor.axis.duration == pytest.approx(0.75)
    settled(qtbot, editor)
    assert_matches_sound(editor)


def test_a_zoomed_view_survives_an_edit_and_stays_in_range(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_view(0.7, 0.9)
    editor.axis.set_selection(0.1, 0.6)
    window.cut_sound()
    start, end = editor.axis.view
    assert end <= editor.axis.duration + 1e-9 and end - start == pytest.approx(0.2)
    assert editor.scrollbar.maximum() > 0


def test_queries_measure_the_edited_audio(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    editor.axis.select_all()
    editor.query_duration()
    assert "0.5" in window.log_panel.text.toPlainText()


def test_the_voice_report_uses_the_edited_audio(window, qtbot, tmp_path):  # noqa: F811
    path = tmp_path / "half.wav"
    # Two different vowels: cutting one away must change the measured pitch.
    Sound(np.concatenate([make_vowel(f0=100, duration=1.0).mono, make_vowel(f0=200, duration=1.0).mono]), 16000.0).save(
        path
    )
    window.open_sound(str(path))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    editor.axis.set_selection(0.0, 1.0)
    window.cut_sound()
    settled(qtbot, editor)
    median = np.nanmedian(editor.manager.results["pitch"].frequencies)
    assert median == pytest.approx(200, rel=0.03)


def test_the_spectrum_and_views_panels_survive_a_cursor_past_the_new_end(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    window.spectrum_panel.show()
    window.views_panel.show()
    editor.axis.set_cursor(0.95)
    editor.axis.set_selection(0.1, 0.9)
    window.cut_sound()
    qtbot.wait(300)
    assert editor.axis.cursor <= editor.axis.duration


def test_the_running_app_lets_go_of_old_audio(window, qtbot, wav):  # noqa: F811
    """Every pane, cache and job must drop it, not just the document."""
    editor = opened(window, wav, qtbot)
    refs = []
    for i in range(4):
        refs.append(weakref.ref(editor.doc.sound.samples))
        editor.axis.set_selection(0.1 + i * 0.05, 0.12 + i * 0.05)
        window.cut_sound()
        settled(qtbot, editor)
    gc.collect()
    assert sum(r() is not None for r in refs) == 0


def test_each_edit_closes_the_previous_shared_block(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    old = editor.manager._shared
    editor.axis.set_selection(0.1, 0.15)
    window.cut_sound()
    assert old.shm is None and editor.manager._shared is not old


def test_workers_let_go_of_old_audio_however_many_edits_happen():
    """Every edit makes a new block, and a block can be hundreds of MB, so workers must not keep them."""
    from phonolab.core import manipulation
    from phonolab.core.manipulation import ManipulationSettings
    from phonolab.ui import workers

    signal = make_sine(150).mono
    names, blocks = [], []
    for _ in range(5):
        block = shared_memory.SharedMemory(create=True, size=signal.nbytes)
        np.ndarray(signal.shape, dtype=np.float64, buffer=block.buf)[:] = signal
        blocks.append(block)
        names.append(block.name)
        sound = workers._attach(block.name, len(signal), 16000.0)
        assert sound.praat is not None and len(sound.mono)  # the caches a real analysis fills
        manipulation.analyse(sound, ManipulationSettings())
        if praat_engine.available():
            praat_engine.sound_file(sound)
        del sound
    assert len(workers._worker_sounds) <= workers._MAX_CACHED_SOUNDS
    kept = set(workers._worker_sounds)
    for block in blocks:
        block.close()
        block.unlink()
    for name in names:
        if name not in kept:
            with pytest.raises(FileNotFoundError):
                shared_memory.SharedMemory(name=name)
    for name in kept:
        workers._worker_sounds.pop(name)[0].close()


# ---------------------------------------------------------------------- races with background work


def test_an_edit_during_analysis_never_shows_old_results(window, qtbot, wav):  # noqa: F811
    window.open_sound(str(wav))  # analyses are still running
    editor = window.editor
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    settled(qtbot, editor)
    qtbot.wait(500)  # anything stale would have landed by now
    assert_matches_sound(editor)


def test_a_manipulation_analysis_of_the_old_audio_never_lands(window, qtbot, wav):  # noqa: F811
    """Its pitch points would belong to audio that no longer exists."""
    editor = opened(window, wav, qtbot)
    editor.ensure_manipulation()  # the pane is hidden, so nothing restarts this after the edit
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    qtbot.wait(2500)
    assert editor.doc.manipulation is None


def test_any_background_job_of_the_old_audio_is_dropped(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    delivered = []
    editor.manager.job_done.connect(lambda key, result: delivered.append(key))
    editor.manager.submit("view", int)
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    qtbot.wait(1500)
    assert "view" not in delivered


def test_rapid_edits_and_undos_settle_on_the_right_audio(window, qtbot, wav):  # noqa: F811
    errors = []
    window.open_sound(str(wav))
    editor = window.editor
    editor.manager.error.connect(lambda name, message: errors.append((name, message)))
    rng = np.random.default_rng(3)
    for _ in range(30):
        if rng.random() < 0.3 and editor.doc.undo_stack.canUndo():
            editor.doc.undo_stack.undo()
        else:
            d = editor.doc.sound.duration
            a = float(rng.uniform(0, d * 0.8))
            editor.axis.set_selection(a, min(d, a + 0.02))
            window.cut_sound() if rng.random() < 0.6 else (window.copy_sound(), window.paste_sound("after"))
        qtbot.wait(int(rng.integers(0, 15)))
    settled(qtbot, editor)
    qtbot.wait(500)
    assert_matches_sound(editor)
    assert not errors


def test_busy_indicator_clears_after_an_edit(window, qtbot, wav):  # noqa: F811
    window.open_sound(str(wav))
    editor = window.editor
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    settled(qtbot, editor)
    qtbot.waitUntil(lambda: not window._busy, timeout=10000)


def test_a_resynthesis_of_the_old_audio_never_plays_after_an_edit(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    received = []
    editor._with_resynthesis(lambda samples, sr: received.append(samples))
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    qtbot.wait(1500)
    assert not received
    qtbot.waitUntil(lambda: not window._busy, timeout=10000)


def test_closing_a_tab_right_after_an_edit_leaves_nothing_running(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.2, 0.3)
    window.cut_sound()
    assert editor.spectrogram._debounce.isActive()
    window.close_tab(0)
    assert not editor.spectrogram._debounce.isActive() and not editor._playhead_timer.isActive()


def test_quitting_right_after_an_edit_leaves_nothing_running(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    window.spectrum_panel.show()
    window.views_panel.show()
    editor.axis.set_selection(0.2, 0.3)
    window.cut_sound()
    window.close()
    assert not editor.spectrogram._debounce.isActive()
    assert not window.spectrum_panel._timer.isActive() and not window.views_panel._timer.isActive()


def test_playback_stops_for_an_edit(window, qtbot, wav, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    stopped = []
    monkeypatch.setattr(editor, "stop", lambda: stopped.append(True))
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    assert stopped


# ---------------------------------------------------------------------- manipulation


def modified_manipulation(window, editor, qtbot):  # noqa: F811
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    editor.axis.set_selection(0.2, 0.4)
    editor.set_loudness(6.0)
    return editor.doc.manipulation


def test_manipulation_resets_on_an_edit_and_undo_restores_it(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    state = modified_manipulation(window, editor, qtbot)
    messages = []
    editor.message.connect(messages.append)
    editor.axis.set_selection(0.5, 0.7)
    window.cut_sound()
    assert editor.doc.manipulation is None or editor.doc.manipulation is not state
    assert any("manipulation was reset" in m for m in messages)
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    assert editor.doc.manipulation.original.times.max() < 0.8  # re-analysed on the shorter sound
    editor.doc.undo_stack.undo()
    assert editor.doc.manipulation is state and len(state.gain) > 0
    assert editor.manipulation_pane.state is state


def test_undo_chain_through_manipulation_and_audio_keeps_commands_working(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    modified_manipulation(window, editor, qtbot)
    editor.axis.set_selection(0.5, 0.7)
    window.cut_sound()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    second = editor.doc.manipulation
    editor.axis.set_selection(0.1, 0.2)
    editor.set_loudness(-6.0)
    stack = editor.doc.undo_stack
    stack.undo()  # loudness on the new state
    stack.undo()  # the cut
    stack.redo()  # the cut again: must return to the same state, or the next redo edits an orphan
    assert editor.doc.manipulation is second
    stack.redo()
    assert len(editor.doc.manipulation.gain) > 0


def test_resynthesis_after_an_edit_uses_the_new_audio(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    editor.axis.set_selection(0.0, 0.5)
    window.cut_sound()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    results = []
    editor._with_resynthesis(lambda samples, sr: results.append((samples, sr)))
    qtbot.waitUntil(lambda: bool(results), timeout=20000)
    assert len(results[0][0]) / results[0][1] == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------- annotations and corrections, live


def test_a_cut_moves_the_textgrid_and_undo_restores_it(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    grid = TextGrid.for_duration(1.0)
    grid.tiers[0].add_boundary(0.3)
    grid.tiers[0].add_boundary(0.6)
    grid.tiers[0].set_text(2, "kept")
    editor.doc.set_textgrid(grid, saved=True)
    before = editor.doc.textgrid.copy()
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    tier = editor.doc.textgrid.tiers[0]
    assert tier.intervals[2].text == "kept" and tier.intervals[2].xmin == pytest.approx(0.5)
    assert editor.doc.textgrid_dirty
    editor.doc.undo_stack.undo()
    assert editor.doc.textgrid == before and not editor.doc.textgrid_dirty


def test_a_selected_interval_cut_away_doesnt_break_the_view(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    grid = TextGrid.for_duration(1.0)
    grid.tiers[0].add_boundary(0.3)
    grid.tiers[0].add_boundary(0.6)
    editor.doc.set_textgrid(grid)
    editor.textgrid_view.selected_tier, editor.textgrid_view.selected_item = 0, 2
    editor.axis.set_selection(0.25, 1.0)
    window.cut_sound()
    assert len(editor.doc.textgrid.tiers[0].intervals) == 1
    editor.textgrid_view.repaint()
    assert editor.textgrid_view.selected_item is None


def test_corrections_follow_a_cut_into_the_results(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.correct("Unvoice", Corrections(unvoiced=((0.6, 0.8),)))
    editor.axis.set_selection(0.1, 0.3)
    window.cut_sound()
    assert editor.doc.corrections.unvoiced == (pytest.approx((0.4, 0.6)),)
    settled(qtbot, editor)
    pitch = editor.manager.results["pitch"]
    inside = (pitch.times > 0.42) & (pitch.times < 0.58)
    assert inside.any() and np.isnan(pitch.frequencies[inside]).all()
    assert not np.isnan(pitch.frequencies[pitch.times > 0.65]).all()


# ---------------------------------------------------------------------- paste


def test_paste_modes_put_the_audio_in_the_right_place(window, qtbot, tmp_path):  # noqa: F811
    path = tmp_path / "ramp.wav"
    Sound(np.arange(1000) / 2000, 1000.0).save(path)
    window.open_sound(str(path))
    editor = window.editor
    original = editor.doc.sound.mono.copy()

    editor.axis.set_selection(0.1, 0.2)
    window.copy_sound()
    clip = original[100:200]

    editor.axis.set_selection(0.5, 0.6)
    window.paste_sound("before")
    assert np.array_equal(editor.doc.sound.mono, np.concatenate([original[:500], clip, original[500:]]))
    assert editor.axis.selection == pytest.approx((0.5, 0.6))
    editor.doc.undo_stack.undo()

    editor.axis.set_selection(0.5, 0.6)
    window.paste_sound("after")
    assert np.array_equal(editor.doc.sound.mono, np.concatenate([original[:600], clip, original[600:]]))
    editor.doc.undo_stack.undo()

    editor.axis.set_selection(0.5, 0.8)
    window.paste_sound("here")
    assert np.array_equal(editor.doc.sound.mono, np.concatenate([original[:500], clip, original[800:]]))
    editor.doc.undo_stack.undo()

    editor.axis.clear_selection()
    editor.axis.set_cursor(0.3)
    window.paste_sound("here")
    assert np.array_equal(editor.doc.sound.mono, np.concatenate([original[:300], clip, original[300:]]))
    editor.doc.undo_stack.undo()
    assert np.array_equal(editor.doc.sound.mono, original)


def test_copying_doesnt_change_anything(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.1, 0.2)
    window.copy_sound()
    assert not editor.doc.is_dirty and editor.doc.undo_stack.count() == 0


def test_paste_works_across_tabs(window, qtbot, tmp_path):  # noqa: F811
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    make_sine(200, duration=1.0).save(a)
    make_sine(400, duration=1.0).save(b)
    window.open_sound(str(a))
    window.editor.axis.set_selection(0.0, 0.5)
    window.copy_sound()
    window.open_sound(str(b))
    assert window.tabs.count() == 2
    window.editor.axis.set_cursor(1.0)
    window.paste_sound("here")
    assert window.editor.doc.sound.duration == pytest.approx(1.5)
    assert window.tabs.widget(0).doc.sound.duration == pytest.approx(1.0)


def test_a_clip_stays_usable_after_its_tab_closes(window, qtbot, tmp_path):  # noqa: F811
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    make_sine(200).save(a)
    make_sine(400).save(b)
    window.open_sound(str(a))
    window.editor.axis.set_selection(0.0, 0.5)
    window.copy_sound()
    window.close_tab(0)
    window.open_sound(str(b))
    window.editor.axis.set_cursor(0.0)
    window.paste_sound("here")
    assert window.editor.doc.sound.duration == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("other", "word"),
    [
        (make_sine(200, sr=8000), "Resample"),
        (make_sine(200, channels=2), "mono"),
    ],
)
def test_incompatible_paste_explains_and_changes_nothing(window, qtbot, tmp_path, other, word):  # noqa: F811
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    make_sine(200).save(a)
    other.save(b)
    window.open_sound(str(b))
    window.editor.axis.set_selection(0.0, 0.5)
    window.copy_sound()
    window.open_sound(str(a))
    editor = window.editor
    messages = []
    editor.message.connect(messages.append)
    editor.axis.set_cursor(0.5)
    window.paste_sound("here")
    assert any(word in m for m in messages)
    assert editor.doc.sound.duration == pytest.approx(1.0) and not editor.doc.is_dirty


def test_stereo_edits_keep_channels_apart(window, qtbot, tmp_path):  # noqa: F811
    path = tmp_path / "s.wav"
    left, right = make_sine(200).mono, make_sine(500).mono
    Sound(np.column_stack([left, right]), 16000.0).save(path)
    window.open_sound(str(path))
    editor = window.editor
    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    samples = editor.doc.sound.samples
    assert samples.shape[1] == 2
    assert np.allclose(samples[:4000, 0], left[:4000], atol=1e-4)
    assert np.allclose(samples[4000:, 1], right[8000:], atol=1e-4)
    assert len(editor.waveform.envelopes) == 2


@pytest.mark.parametrize("command", ["cut_sound", "copy_sound"])
def test_nothing_selected_says_so(window, qtbot, wav, command):  # noqa: F811
    editor = opened(window, wav, qtbot)
    messages = []
    editor.message.connect(messages.append)
    getattr(window, command)()
    assert any("Select" in m for m in messages) and not editor.doc.is_dirty


def test_pasting_with_an_empty_clipboard_says_so(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    messages = []
    editor.message.connect(messages.append)
    window.paste_sound("here")
    assert any("Nothing to paste" in m for m in messages)


def test_cutting_the_whole_sound_explains_itself(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    messages = []
    editor.message.connect(messages.append)
    editor.axis.select_all()
    window.cut_sound()
    assert any("whole sound" in m for m in messages) and editor.doc.sound.duration == pytest.approx(1.0)


def test_a_failed_cut_keeps_the_previous_clip(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.1, 0.2)
    window.copy_sound()
    clip = window.sound_clip
    editor.axis.select_all()
    window.cut_sound()
    assert window.sound_clip is clip


# ---------------------------------------------------------------------- shortcuts


def test_cut_copy_paste_shortcuts_reach_the_sound(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.textgrid_view.setFocus()
    window.activateWindow()
    editor.axis.set_selection(0.1, 0.2)
    assert action(window, "Cut sound").shortcut().toString() == "Ctrl+X"
    action(window, "Cut sound").trigger()
    assert editor.doc.sound.duration == pytest.approx(0.9)


def test_ctrl_c_in_the_label_box_copies_text_not_sound(window, qtbot, wav):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.set_textgrid(TextGrid.for_duration(1.0))
    window.activateWindow()
    qtbot.waitExposed(window)
    editor.textgrid_view.selected_tier, editor.textgrid_view.selected_item = 0, 0
    editor.label_edit.setFocus()
    editor.label_edit.setText("hello")
    editor.label_edit.selectAll()
    editor.axis.set_selection(0.1, 0.2)
    QTest.keyClick(editor.label_edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor.label_edit, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert window.sound_clip is None and editor.doc.sound.duration == pytest.approx(1.0)
    QTest.keyClick(editor.label_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert editor.label_edit.text() == "hello" and editor.doc.sound.duration == pytest.approx(1.0)


# ---------------------------------------------------------------------- saving


def save_to(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_closing_edited_audio_offers_to_save_it(window, qtbot, wav, tmp_path, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or Buttons.Save)
    target = tmp_path / "edited.wav"
    save_to(monkeypatch, target)
    window.close_tab(0)
    assert any("edited sound" in text for text in asked)
    assert Sound.from_file(target).duration == pytest.approx(0.9)


def test_cancel_keeps_edited_audio_open(window, qtbot, wav, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: Buttons.Cancel)
    window.close_tab(0)
    assert window.tabs.count() == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a: Buttons.Discard)


def test_discarding_audio_edits_never_saves_corrections_with_shifted_times(window, qtbot, wav, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.correct("Unvoice", Corrections(unvoiced=((0.6, 0.8),)))
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[1]) or Buttons.Discard)
    window.close_tab(0)
    assert asked == ["Unsaved sound"]
    assert not Corrections.path_for(wav).exists()


def test_discarding_audio_edits_warns_about_the_textgrid(window, qtbot, wav, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.set_textgrid(TextGrid.for_duration(1.0))
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or Buttons.Discard)
    window.close_tab(0)
    assert any("audio edits you just discarded" in text for text in asked)


def test_saving_corrections_saves_edited_audio_first(window, qtbot, wav, tmp_path, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.correct("Unvoice", Corrections(unvoiced=((0.6, 0.8),)))
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    target = tmp_path / "edited.wav"
    save_to(monkeypatch, target)
    assert window.save_corrections()
    assert Sound.from_file(target).duration == pytest.approx(0.9)
    assert Corrections.load_for(target).unvoiced == (pytest.approx((0.5, 0.7)),)
    assert not Corrections.path_for(wav).exists()


def test_cancelling_that_save_saves_no_corrections(window, qtbot, wav, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.doc.correct("Unvoice", Corrections(unvoiced=((0.6, 0.8),)))
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    assert not window.save_corrections()
    assert not Corrections.path_for(wav).exists()


def test_reopening_an_edited_save_gives_the_same_analysis(window, qtbot, wav, tmp_path, monkeypatch):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.1, 0.3)
    window.cut_sound()
    target = tmp_path / "edited.wav"
    save_to(monkeypatch, target)
    window.save_sound_as()
    settled(qtbot, editor)
    assert not editor.doc.is_dirty
    reopened = Sound.from_file(target)
    fresh = registry.compute("pitch", reopened, editor.manager.settings)
    shown = editor.manager.raw_results["pitch"]
    assert len(fresh.times) == len(shown.times)
    assert np.allclose(fresh.frequencies, shown.frequencies, rtol=1e-3, equal_nan=True)


# ---------------------------------------------------------------------- long recordings


def test_long_recordings_refuse_cut_and_paste_clearly(long_window, qtbot):  # noqa: F811
    editor = long_window.editor
    messages = []
    editor.message.connect(messages.append)
    editor.axis.set_selection(0.5, 1.0)
    long_window.cut_sound()
    assert any("extract" in m.lower() for m in messages)
    assert editor.doc.sound.duration == pytest.approx(3.0) and not editor.doc.is_dirty


def test_copying_from_a_long_recording_into_a_normal_sound(long_window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    from phonolab.core import sound as sound_module

    long_window.editor.axis.set_selection(0.5, 1.0)
    long_window.copy_sound()
    assert long_window.sound_clip is not None
    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 10**9)
    path = tmp_path / "short.wav"
    make_vowel(duration=1.0).save(path)
    long_window.open_sound(str(path))
    editor = long_window.editor
    editor.axis.set_cursor(1.0)
    long_window.paste_sound("here")
    assert editor.doc.sound.duration == pytest.approx(1.5, abs=1e-3)


# ---------------------------------------------------------------------- against Praat itself


@pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
def test_a_cut_matches_the_same_cut_made_in_praat(window, qtbot, wav, tmp_path):  # noqa: F811
    editor = opened(window, wav, qtbot)
    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    theirs = tmp_path / "praat.wav"
    praat_engine.run_script(
        f'''sound = Read from file: "{wav.as_posix()}"
a = Extract part: 0, 0.25, "rectangular", 1, "no"
selectObject: sound
b = Extract part: 0.5, 1, "rectangular", 1, "no"
selectObject: a, b
Concatenate
Save as WAV file: "{theirs.as_posix()}"
'''
    )
    reference = Sound.from_file(theirs)
    assert reference.n_samples == editor.doc.sound.n_samples
    assert np.allclose(reference.mono, editor.doc.sound.mono, atol=1 / 2**15)
    settled(qtbot, editor)
    theirs_pitch = registry.compute("pitch", reference, editor.manager.settings)
    ours = editor.manager.raw_results["pitch"]
    assert np.allclose(theirs_pitch.frequencies, ours.frequencies, rtol=1e-3, equal_nan=True)


@pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
def test_praat_reads_a_textgrid_edited_by_a_cut(window, qtbot, wav, tmp_path):  # noqa: F811
    editor = opened(window, wav, qtbot)
    grid = TextGrid.for_duration(1.0)
    for t in (0.2, 0.4, 0.6, 0.8):
        grid.tiers[0].add_boundary(t)
    editor.doc.set_textgrid(grid)
    editor.axis.set_selection(0.3, 0.7)
    window.cut_sound()
    path = tmp_path / "cut.TextGrid"
    editor.doc.save_textgrid(path)
    out = praat_engine.run_script(
        f'Read from file: "{path.as_posix()}"\n'
        'n = Get number of intervals: 1\nd = Get total duration\nwriteInfoLine: n, " ", d\n'
    )
    count, duration = out.split()
    assert int(count) == 4 and float(duration) == pytest.approx(0.6)
