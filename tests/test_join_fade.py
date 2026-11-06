"""The optional crossfade at the joins of audio edits."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtWidgets import QInputDialog  # noqa: E402

from phonolab.core.settings import DEFAULT_JOIN_FADE_MS, Preferences  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid  # noqa: E402
from phonolab.core.time_edit import smooth_joins  # noqa: E402
from phonolab.ui.document import Document  # noqa: E402
from tests.test_time_edit import check_valid  # noqa: E402
from tests.test_ui_smoke import wait_for_analyses, wav, window  # noqa: E402, F401

RATE = 1000.0
RECORDING = Path(__file__).parent / "recordings/timit/ldc93s1.wav"


def column(values):
    return np.asarray(values, dtype=float)[:, np.newaxis]


def steps():
    """Two levels meeting in the middle: the worst possible join."""
    return column([1.0] * 500 + [-1.0] * 500)


# ---------------------------------------------------------------------- what a crossfade does


def test_a_cut_keeps_its_length():
    s = column(np.arange(1000.0))
    end, new = smooth_joins(s, 100, 300, None, 20)
    assert end == 320 and len(new) == 20
    result = np.concatenate([s[:100], new, s[end:]])
    assert len(result) == 800


def test_a_crossfade_runs_from_one_side_to_the_other():
    left, right = np.full((100, 1), 1.0), np.full((100, 1), -1.0)
    s = np.concatenate([left, right])
    _, new = smooth_joins(s, 50, 100, None, 20)
    assert new[0, 0] == pytest.approx(1.0, abs=0.02) and new[-1, 0] == pytest.approx(-1.0, abs=0.02)
    assert np.all(np.diff(new[:, 0]) < 0)


def test_samples_before_a_join_and_past_the_fade_stay_exact():
    doc = Document(Sound(np.sin(np.arange(2000) / 7), RATE))
    original = doc.sound.mono.copy()
    doc.splice_audio("Cut", 500, 800, fade=30)
    assert np.array_equal(doc.sound.mono[:500], original[:500])
    assert np.array_equal(doc.sound.mono[530:], original[830:])


@pytest.mark.parametrize(("start", "end"), [(0, 100), (900, 1000)])
def test_a_cut_at_either_end_of_the_sound_joins_nothing(start, end):
    s = steps()
    assert smooth_joins(s, start, end, None, 20) == (end, None)


def test_a_fade_longer_than_the_cut_is_limited_by_it():
    s = steps()
    end, new = smooth_joins(s, 400, 410, None, 100)
    assert end == 420 and len(new) == 10


def test_a_fade_near_the_end_is_limited_by_whats_left():
    end, new = smooth_joins(steps(), 800, 990, None, 100)
    assert end == 1000 and len(new) == 10


def test_a_paste_crossfades_both_ends_and_keeps_its_length():
    s = steps()
    clip = np.zeros((100, 1))
    end, new = smooth_joins(s, 200, 200, clip, 20)
    assert end == 200 and len(new) == 100
    assert new[0, 0] == pytest.approx(1.0, abs=0.02)  # continues from what's before it
    assert new[-1, 0] == pytest.approx(1.0, abs=0.02)  # and into what's after it
    assert np.array_equal(new[20:80], clip[20:80])


def test_a_short_clip_keeps_its_two_fades_apart():
    _, new = smooth_joins(steps(), 200, 200, np.zeros((10, 1)), 100)
    assert len(new) == 10


def test_a_one_sample_clip_is_left_alone():
    clip = column([0.25])
    assert smooth_joins(steps(), 200, 200, clip, 20)[1].tolist() == [[0.25]]


def test_pasting_at_the_very_start_and_end_fades_only_the_real_join():
    """There's no audio beyond the edge to blend with, so the join leads to the nearest real sample."""
    s = steps()
    clip = np.zeros((100, 1))
    _, at_start = smooth_joins(s, 0, 0, clip, 20)
    assert at_start[0, 0] == 0 and at_start[-1, 0] == pytest.approx(s[0, 0], abs=0.02)
    _, at_end = smooth_joins(s, 1000, 1000, clip, 20)
    assert at_end[-1, 0] == 0 and at_end[0, 0] == pytest.approx(s[-1, 0], abs=0.02)


def test_a_paste_close_to_the_edges_is_still_smooth():
    s = steps()
    clip = np.zeros((100, 1))
    _, near_start = smooth_joins(s, 3, 3, clip, 20)
    assert near_start[-1, 0] == pytest.approx(s[3, 0], abs=0.02)
    _, near_end = smooth_joins(s, 997, 997, clip, 20)
    assert near_end[0, 0] == pytest.approx(s[997, 0], abs=0.02)


def test_the_clip_passed_in_is_not_changed():
    clip = np.zeros((100, 1))
    smooth_joins(steps(), 200, 200, clip, 20)
    assert not clip.any()


def test_every_channel_is_faded():
    s = np.column_stack([np.ones(200), -np.ones(200)])
    _, new = smooth_joins(s, 50, 100, None, 10)
    assert new.shape == (10, 2) and np.array_equal(new[:, 0], -new[:, 1])


# ---------------------------------------------------------------------- with the document


@pytest.mark.parametrize("seed", range(30))
def test_random_faded_edits_keep_the_timing_and_undo_exactly(qapp, seed):
    rng = np.random.default_rng(seed)
    sound = Sound(rng.normal(0, 0.1, (4000, 2)), RATE, title="s")
    plain, faded = Document(sound), Document(sound)
    grid = TextGrid(0.0, 4.0, [IntervalTier("t", 0.0, 4.0, [Interval(0.0, 1.0, "a"), Interval(1.0, 4.0, "b")])])
    plain.set_textgrid(grid.copy())
    faded.set_textgrid(grid.copy())
    original = sound.samples.copy()
    done = 0
    for _ in range(12):
        n = faded.sound.n_samples
        a = int(rng.integers(0, n))
        b = min(n, a + int(rng.integers(1, 500)))
        clip = rng.normal(0, 0.1, (int(rng.integers(1, 300)), 2)) if rng.random() < 0.5 else None
        if clip is None and b - a >= n:
            continue
        plain.splice_audio("Edit", a, b, clip)
        faded.splice_audio("Edit", a, b, clip, fade=int(rng.integers(1, 60)))
        done += 1
        assert faded.sound.n_samples == plain.sound.n_samples
        assert faded.textgrid == plain.textgrid  # the fade never touches timing
        check_valid(faded.textgrid)
    for _ in range(done):
        faded.undo_stack.undo()
    assert np.array_equal(faded.sound.samples, original) and faded.textgrid == grid


def test_no_fade_is_bit_exact(qapp):
    sound = Sound(np.sin(np.arange(1000) / 3), RATE)
    doc = Document(sound)
    doc.splice_audio("Cut", 100, 200)
    assert np.array_equal(doc.sound.mono, np.concatenate([sound.mono[:100], sound.mono[200:]]))


def test_undo_history_stays_small_with_a_fade(qapp):
    doc = Document(Sound(np.zeros(100_000), RATE))
    doc.splice_audio("Cut", 100, 200, fade=20)
    command = doc.undo_stack.command(0)
    assert len(command.removed) == 120 and command.removed.base is None and command.inserted.base is None


# ---------------------------------------------------------------------- on real speech


@pytest.mark.skipif(not RECORDING.exists(), reason="run tests/fetch_recordings.py first")
def test_a_faded_join_is_as_smooth_as_undisturbed_speech(qapp):
    """A click is the jump across the join, so compare that with the jump between ordinary neighbouring samples."""
    sound = Sound.from_file(RECORDING)
    x = sound.mono
    rng = np.random.default_rng(0)
    fade = round(0.005 * sound.sampling_rate)
    natural, plain, faded = [], [], []
    for _ in range(200):
        a = int(rng.integers(8000, 30000))
        b = a + int(rng.integers(800, 6000))
        natural.append(abs(x[a] - x[a - 1]))
        for amount, jumps in ((0, plain), (fade, faded)):
            doc = Document(sound)
            doc.splice_audio("Cut", a, b, fade=amount)
            jumps.append(abs(doc.sound.mono[a] - doc.sound.mono[a - 1]))
    assert np.mean(plain) > 3 * np.mean(natural)  # the problem being solved is real here
    assert np.mean(faded) < 1.2 * np.mean(natural)  # measured: equal
    assert np.percentile(faded, 95) < 0.4 * np.percentile(plain, 95)


# ---------------------------------------------------------------------- the setting


def test_its_off_by_default():
    prefs = Preferences(_Store())
    assert prefs.smooth_joins() is False and prefs.join_fade_ms() == DEFAULT_JOIN_FADE_MS


class _Store:
    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self.data[key] = value


def test_the_setting_is_remembered():
    store = _Store()
    Preferences(store).set_smooth_joins(True)
    Preferences(store).set_join_fade_ms(12.5)
    assert Preferences(store).smooth_joins() is True and Preferences(store).join_fade_ms() == 12.5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9999", 100.0),
        ("-3", 0.1),
        ('"x"', DEFAULT_JOIN_FADE_MS),
        ("true", DEFAULT_JOIN_FADE_MS),
        ("not json", DEFAULT_JOIN_FADE_MS),
    ],
)  # noqa: E501
def test_a_damaged_setting_stays_sensible(raw, expected):
    store = _Store()
    store.data["edit/join_fade_ms"] = raw
    assert Preferences(store).join_fade_ms() == expected


def test_the_menu_setting_reaches_a_cut(window, qtbot, wav):  # noqa: F811
    window.open_sound(str(wav))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    original = editor.doc.sound.mono.copy()
    a = int(0.25 * editor.doc.sound.sampling_rate)
    b = int(0.5 * editor.doc.sound.sampling_rate)

    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    assert np.array_equal(editor.doc.sound.mono, np.concatenate([original[:a], original[b:]]))
    editor.doc.undo_stack.undo()

    window.smooth_joins_action.trigger()
    assert window.prefs.smooth_joins()
    editor.axis.set_selection(0.25, 0.5)
    window.cut_sound()
    assert len(editor.doc.sound.mono) == len(original) - (b - a)
    assert not np.array_equal(editor.doc.sound.mono[a : a + 40], original[b : b + 40])
    fade = round(0.005 * editor.doc.sound.sampling_rate)
    assert np.array_equal(editor.doc.sound.mono[a + fade :], original[b + fade :])
    editor.doc.undo_stack.undo()
    assert np.array_equal(editor.doc.sound.mono, original)
    window.smooth_joins_action.trigger()
    assert not window.prefs.smooth_joins()


def test_the_length_setting_is_used(window, qtbot, wav, monkeypatch):  # noqa: F811
    window.open_sound(str(wav))
    editor = window.editor
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *a: (20.0, True))
    window.set_join_fade()
    window.smooth_joins_action.trigger()
    assert editor._join_fade() == round(0.02 * editor.doc.sound.sampling_rate)
    window.smooth_joins_action.trigger()
    assert editor._join_fade() == 0


def test_cancelling_the_length_dialog_changes_nothing(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *a: (50.0, False))
    window.set_join_fade()
    assert window.prefs.join_fade_ms() == DEFAULT_JOIN_FADE_MS
