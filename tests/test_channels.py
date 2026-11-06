"""Measuring one channel, and muting channels during playback.

The test sound holds a voice at 100 Hz on the left and 200 Hz on the right, so any measurement that
quietly used the wrong channel gives a clearly wrong number.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from phonolab.audio.player import PlaybackBuffer  # noqa: E402
from phonolab.core import registry, spectrum  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.ui.document import Document  # noqa: E402
from tests.conftest import make_sine, make_vowel  # noqa: E402
from tests.test_ui_smoke import long_window, wait_for_analyses, wav, window  # noqa: E402, F401

LEFT, RIGHT = 100, 200


def stereo():
    return Sound(
        np.column_stack([make_vowel(f0=LEFT, duration=1.0).mono, make_vowel(f0=RIGHT, duration=1.0).mono]), 16000.0
    )


@pytest.fixture
def editor(window, qtbot, tmp_path):  # noqa: F811
    path = tmp_path / "stereo.wav"
    stereo().save(path)
    window.open_sound(str(path))
    ed = window.editor
    wait_for_analyses(qtbot, ed)
    return ed


def median_pitch(editor):
    return np.nanmedian(editor.manager.results["pitch"].frequencies)


def choose(editor, qtbot, channel):
    editor.set_analysis_channel(channel)
    wait_for_analyses(qtbot, editor)


# ---------------------------------------------------------------------- the document


def test_mix_is_the_sound_itself():
    doc = Document(stereo())
    assert doc.analysis_sound is doc.sound


def test_a_channel_is_just_that_channel():
    sound = stereo()
    doc = Document(sound)
    doc.analysis_channel = 1
    assert doc.analysis_sound.n_channels == 1 and np.array_equal(doc.analysis_sound.mono, sound.samples[:, 1])


def test_the_channel_is_reused_until_something_changes(qapp):
    doc = Document(stereo())
    doc.analysis_channel = 0
    first = doc.analysis_sound
    assert doc.analysis_sound is first
    doc.analysis_channel = 1
    second = doc.analysis_sound
    assert second is not first
    doc.splice_audio("Cut", 0, 100)
    assert doc.analysis_sound is not second and doc.analysis_sound.n_samples == 15900


def test_edits_change_both_channels_whichever_is_measured(qapp):
    doc = Document(stereo())
    doc.analysis_channel = 1
    doc.splice_audio("Cut", 0, 100)
    assert doc.sound.n_channels == 2 and doc.sound.n_samples == 15900


# ---------------------------------------------------------------------- every measurement follows the channel


def test_the_pitch_curve_follows_the_channel(editor, qtbot):
    choose(editor, qtbot, 0)
    assert median_pitch(editor) == pytest.approx(LEFT, rel=0.03)
    choose(editor, qtbot, 1)
    assert median_pitch(editor) == pytest.approx(RIGHT, rel=0.03)


def test_back_to_the_mix(editor, qtbot):
    choose(editor, qtbot, 1)
    choose(editor, qtbot, None)
    fresh = registry.compute("pitch", editor.doc.sound, editor.manager.settings)
    assert np.allclose(editor.manager.raw_results["pitch"].frequencies, fresh.frequencies, equal_nan=True)


def test_queries_on_hidden_layers_use_the_channel(editor, qtbot):
    choose(editor, qtbot, 1)
    result = editor.manager.compute_now("pitch")
    assert np.nanmedian(result.frequencies) == pytest.approx(RIGHT, rel=0.03)


def test_the_voice_report_uses_the_channel(window, editor, qtbot, monkeypatch):  # noqa: F811
    seen = []
    from phonolab.ui.editor import sound_editor

    real = sound_editor.voice.voice_report
    monkeypatch.setattr(
        sound_editor.voice, "voice_report", lambda sound, *a, **k: seen.append(sound) or real(sound, *a, **k)
    )
    choose(editor, qtbot, 1)
    editor.axis.set_selection(0.2, 0.8)
    window._voice_report()
    assert seen and seen[0] is editor.doc.analysis_sound


def test_the_spectrum_panel_uses_the_channel(window, editor, qtbot, monkeypatch):  # noqa: F811
    seen = []
    real = spectrum.slice_range
    monkeypatch.setattr(spectrum, "slice_range", lambda sound, *a: seen.append(sound) or real(sound, *a))
    choose(editor, qtbot, 0)
    window.spectrum_panel.set_editor(editor)
    window.spectrum_panel.show()
    editor.axis.set_cursor(0.5)
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)
    assert seen[-1] is editor.doc.analysis_sound


def test_manipulation_analyses_the_channel(window, editor, qtbot):  # noqa: F811
    choose(editor, qtbot, 1)
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    assert np.median(editor.doc.manipulation.original.values) == pytest.approx(RIGHT, rel=0.03)


def test_formant_bandwidths_use_the_channel(editor, qtbot, monkeypatch):
    from phonolab.ui.editor import sound_editor

    seen = []
    real = sound_editor.queries.formant_bandwidths_at
    monkeypatch.setattr(
        sound_editor.queries, "formant_bandwidths_at", lambda sound, *a: seen.append(sound) or real(sound, *a)
    )
    choose(editor, qtbot, 1)
    editor.axis.set_cursor(0.5)
    editor.query_formants()
    assert seen and seen[0] is editor.doc.analysis_sound


def test_stylizing_uses_the_channel(window, editor, qtbot, monkeypatch):  # noqa: F811
    from phonolab.ui.editor import sound_editor

    seen = []
    real = sound_editor.manipulation.stylize
    monkeypatch.setattr(
        sound_editor.manipulation, "stylize", lambda tier, st, sound: seen.append(sound) or real(tier, st, sound)
    )
    choose(editor, qtbot, 1)
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    editor.stylize_pitch(2.0)
    assert seen and seen[0] is editor.doc.analysis_sound


def test_figures_use_the_channel(window, editor, qtbot, monkeypatch):  # noqa: F811
    from phonolab.ui.dialogs import figure_dialog

    seen = []
    real = figure_dialog.figures.make_figure
    monkeypatch.setattr(figure_dialog.figures, "make_figure", lambda sound, *a: seen.append(sound) or real(sound, *a))
    choose(editor, qtbot, 1)
    dialog = figure_dialog.FigureDialog(editor, figure_dialog.figures.FigureSettings(), window)
    dialog.render_preview()
    assert seen and seen[-1] is editor.doc.analysis_sound


# ---------------------------------------------------------------------- switching and racing


def test_a_result_for_the_old_channel_never_lands(editor, qtbot):
    editor.set_analysis_channel(0)
    editor.set_analysis_channel(1)  # the first is still running
    wait_for_analyses(qtbot, editor)
    qtbot.wait(500)
    assert median_pitch(editor) == pytest.approx(RIGHT, rel=0.03)


def test_rapid_switching_settles_on_the_last_choice(editor, qtbot):
    for channel in (0, 1, None, 1, 0, None, 0, 1):
        editor.set_analysis_channel(channel)
        qtbot.wait(5)
    wait_for_analyses(qtbot, editor)
    qtbot.wait(500)
    assert median_pitch(editor) == pytest.approx(RIGHT, rel=0.03)


def test_choosing_the_same_channel_does_nothing(editor, qtbot):
    choose(editor, qtbot, 1)
    results = editor.manager.results["pitch"]
    editor.set_analysis_channel(1)
    assert editor.manager.results["pitch"] is results


def test_the_channel_survives_edits_and_undo(window, editor, qtbot):  # noqa: F811
    choose(editor, qtbot, 1)
    editor.axis.set_selection(0.1, 0.3)
    window.cut_sound()
    wait_for_analyses(qtbot, editor)
    assert median_pitch(editor) == pytest.approx(RIGHT, rel=0.03)
    assert editor.manager.sound.n_channels == 1 and editor.manager.sound.duration == pytest.approx(0.8)
    editor.doc.undo_stack.undo()
    wait_for_analyses(qtbot, editor)
    assert median_pitch(editor) == pytest.approx(RIGHT, rel=0.03)
    assert editor.manager.sound.duration == pytest.approx(1.0)


def test_each_tab_keeps_its_own_channel(window, editor, qtbot, tmp_path):  # noqa: F811
    choose(editor, qtbot, 1)
    other = tmp_path / "other.wav"
    stereo().save(other)
    window.open_sound(str(other))
    wait_for_analyses(qtbot, window.editor)
    assert window.editor.doc.analysis_channel is None and editor.doc.analysis_channel == 1


def test_a_modified_manipulation_asks_first(window, editor, qtbot, monkeypatch):  # noqa: F811
    window._show_manipulation()
    qtbot.waitUntil(lambda: editor.doc.manipulation is not None, timeout=15000)
    editor.axis.set_selection(0.2, 0.4)
    editor.set_loudness(6.0)
    state = editor.doc.manipulation
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    window.set_analysis_channel(1)
    assert editor.doc.analysis_channel is None and editor.doc.manipulation is state
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.set_analysis_channel(1)
    assert editor.doc.analysis_channel == 1 and editor.doc.manipulation is not state


def test_the_waveform_marks_the_measured_and_muted_channels(editor, qtbot):
    choose(editor, qtbot, 1)
    editor.set_channel_muted(0, True)
    ticks = editor.waveform.getPlotItem().getAxis("left")._tickLevels[0]
    assert [t[1] for t in ticks] == ["ch 1 muted", "ch 2 ●"]


def test_saving_writes_every_channel_whichever_is_measured(editor, qtbot, tmp_path):
    choose(editor, qtbot, 1)
    path = tmp_path / "saved.wav"
    editor.doc.save_sound(path)
    assert Sound.from_file(path).n_channels == 2


# ---------------------------------------------------------------------- menus


def test_menus_list_the_channels_of_the_current_tab(window, editor):  # noqa: F811
    window._fill_channel_menu()
    window._fill_mute_menu()
    assert [a.text() for a in window.channel_menu.actions()] == ["Mix of all channels", "Channel 1", "Channel 2"]
    assert [a.text() for a in window.mute_menu.actions()] == ["Channel 1", "Channel 2"]
    assert window.channel_menu.actions()[0].isChecked()


def test_the_menus_act(window, editor, qtbot):  # noqa: F811
    window._fill_channel_menu()
    window.channel_menu.actions()[2].trigger()
    wait_for_analyses(qtbot, editor)
    assert editor.doc.analysis_channel == 1
    window._fill_channel_menu()
    assert window.channel_menu.actions()[2].isChecked()
    window._fill_mute_menu()
    window.mute_menu.actions()[0].trigger()
    assert editor.muted == {0}
    window._fill_mute_menu()
    assert window.mute_menu.actions()[0].isChecked()


def test_mono_sounds_have_nothing_to_choose(window, wav, qtbot):  # noqa: F811
    window.open_sound(str(wav))
    window._fill_channel_menu()
    window._fill_mute_menu()
    assert not window.channel_menu.actions()[0].isEnabled() and not window.mute_menu.actions()[0].isEnabled()


def test_with_no_sound_open_the_menus_are_safe(window):  # noqa: F811
    window._fill_channel_menu()
    window._fill_mute_menu()
    assert len(window.channel_menu.actions()) == 1


def test_long_recordings_stay_on_the_mix(long_window, qtbot):  # noqa: F811
    editor = long_window.editor
    messages = []
    editor.message.connect(messages.append)
    editor.set_analysis_channel(0)
    assert editor.doc.analysis_channel is None and any("mix" in m for m in messages)


# ---------------------------------------------------------------------- muting


def blocks(buffer, n=4, channels=2):
    out = np.ones((n, channels), dtype=np.float32)
    buffer.fill(out)
    return out


def test_gains_silence_a_channel():
    samples = np.ones((10, 2), dtype=np.float32)
    out = blocks(PlaybackBuffer(samples, 0, 10, np.array([1, 0], dtype=np.float32)))
    assert out[:, 0].tolist() == [1, 1, 1, 1] and out[:, 1].tolist() == [0, 0, 0, 0]


def test_no_gains_plays_everything():
    assert blocks(PlaybackBuffer(np.ones((10, 2), dtype=np.float32), 0, 10)).min() == 1


def test_muting_takes_effect_on_the_next_block():
    buffer = PlaybackBuffer(np.ones((10, 2), dtype=np.float32), 0, 10)
    assert blocks(buffer).min() == 1
    buffer.gains = np.array([0, 1], dtype=np.float32)
    assert blocks(buffer)[:, 0].max() == 0


def test_muting_pads_a_short_last_block_with_silence():
    buffer = PlaybackBuffer(np.ones((3, 2), dtype=np.float32), 0, 3, np.array([1, 0], dtype=np.float32))
    out = blocks(buffer)
    assert out[:, 0].tolist() == [1, 1, 1, 0] and buffer.done


def test_gains_never_touch_the_samples():
    samples = np.ones((10, 2), dtype=np.float32)
    blocks(PlaybackBuffer(samples, 0, 10, np.array([0, 0], dtype=np.float32)))
    assert samples.min() == 1


def test_gains_are_passed_to_the_player(editor, monkeypatch):
    played = []
    monkeypatch.setattr(editor.player, "play", lambda *a: played.append(a))
    monkeypatch.setattr(type(editor.player), "available", property(lambda _: True))
    editor.set_channel_muted(1, True)
    editor.play(0.0, 0.5)
    assert played[-1][4].tolist() == [1, 0]
    editor.set_channel_muted(1, False)
    editor.play(0.0, 0.5)
    assert played[-1][4] is None


def test_a_mono_resynthesis_isnt_given_stereo_gains(editor, monkeypatch):
    played = []
    monkeypatch.setattr(editor.player, "play", lambda *a: played.append(a))
    monkeypatch.setattr(type(editor.player), "available", property(lambda _: True))
    editor.set_channel_muted(0, True)
    editor.play(0.0, 0.5, samples=make_sine().mono, sampling_rate=16000.0)
    assert played[-1][4] is None


def test_muting_during_playback_reaches_the_buffer(editor):
    buffer = PlaybackBuffer(np.ones((10, 2), dtype=np.float32), 0, 10)
    editor.player._buffer = buffer
    editor.set_channel_muted(0, True)
    assert buffer.gains.tolist() == [0, 1]
    editor.set_channel_muted(0, False)
    assert buffer.gains is None
    editor.player._buffer = None


def test_muting_never_marks_the_sound_as_changed(editor):
    editor.set_channel_muted(0, True)
    assert not editor.doc.is_dirty and editor.doc.undo_stack.count() == 0
