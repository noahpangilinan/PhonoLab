"""Moving several boundaries at once, converting tiers, extracting and merging."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from phonolab.core import praat_engine  # noqa: E402
from phonolab.core.textgrid import (  # noqa: E402
    Interval,
    IntervalTier,
    Point,
    PointTier,
    TextGrid,
    TextGridError,
    aligned_handles,
    extract_tier,
    intervals_from_points,
    merge_tiers,
    move_together,
    points_from_intervals,
    rubber_band,
)
from tests.test_time_edit import check_valid  # noqa: E402
from tests.test_ui_smoke import wait_for_analyses, wav, window  # noqa: E402, F401


def tier_with(*bounds, name="t", xmax=10.0, labels=None):
    times = [0.0, *bounds, xmax]
    texts = labels or [""] * (len(times) - 1)
    intervals = [Interval(a, b, s) for a, b, s in zip(times[:-1], times[1:], texts, strict=True)]
    return IntervalTier(name, 0.0, xmax, intervals)


def bounds(tier):
    return tier.boundaries


# ---------------------------------------------------------------------- aligned boundaries


def aligned_grid():
    return TextGrid(
        0.0,
        10.0,
        [
            tier_with(2, 5, name="a"),
            tier_with(3, 5, 7, name="b"),
            PointTier("p", 0, 10, [Point(1), Point(5), Point(6)]),
            tier_with(4, name="other"),
        ],
    )


def test_aligned_handles_finds_every_tier_at_that_time():
    assert aligned_handles(aligned_grid(), 5.0) == [(0, 2), (1, 2), (2, 1)]


def test_near_misses_arent_aligned():
    assert aligned_handles(aligned_grid(), 5.01) == []


def test_moving_together_keeps_them_aligned():
    grid = aligned_grid()
    assert move_together(grid, aligned_handles(grid, 5.0), 4.5) == 4.5
    assert 4.5 in bounds(grid.tiers[0]) and 4.5 in bounds(grid.tiers[1]) and grid.tiers[2].points[1].time == 4.5
    check_valid(grid)


def test_the_nearest_neighbour_on_any_tier_stops_them_all():
    grid = aligned_grid()
    t = move_together(grid, aligned_handles(grid, 5.0), 6.5)  # the point at 6 stops it, though 7 is further
    assert t == pytest.approx(6.0, abs=1e-6)
    assert bounds(grid.tiers[0])[1] == bounds(grid.tiers[1])[1] == grid.tiers[2].points[1].time == t
    check_valid(grid)


def test_moving_together_can_go_no_further_than_the_lower_neighbour():
    grid = aligned_grid()
    t = move_together(grid, aligned_handles(grid, 5.0), 0.5)
    assert t == pytest.approx(3.0, abs=1e-6)  # tier b's boundary at 3
    check_valid(grid)


# ---------------------------------------------------------------------- rubber banding


def banded(start_bounds, index, t, low=0.0, high=10.0):
    original = tier_with(*start_bounds)
    tier = tier_with(*start_bounds)
    rubber_band(tier, original, index, t, low, high)
    return tier


def test_rubber_band_stretches_both_sides_in_proportion():
    assert bounds(banded((2, 4, 6, 8), 2, 6.0)) == pytest.approx([3, 6, 7.3333333, 8.6666666])


def test_rubber_band_leaves_things_outside_the_anchors_alone():
    assert bounds(banded((1, 3, 5, 7, 9), 3, 4.0, low=2.0, high=8.0)) == pytest.approx([1, 2.6666666, 4, 6.6666666, 9])


def test_rubber_band_back_to_the_start_restores_exactly():
    original = tier_with(1.1, 2.2, 3.3, 7.7)
    tier = tier_with(1.1, 2.2, 3.3, 7.7)
    for t in (5.0, 9.0, 0.5, 3.0, 8.0):
        rubber_band(tier, original, 2, t, 0.0, 10.0)
    rubber_band(tier, original, 2, 2.2, 0.0, 10.0)
    assert bounds(tier) == pytest.approx(bounds(original), abs=1e-12)


@pytest.mark.parametrize("seed", range(30))
def test_rubber_banding_never_crosses_or_collapses_boundaries(seed):
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.01, 9.99, 15)).tolist()
    original, tier = tier_with(*times), tier_with(*times)
    for _ in range(50):
        index = int(rng.integers(1, 16))
        rubber_band(tier, original, index, float(rng.uniform(-1, 11)), 0.0, 10.0)
        check_valid(TextGrid(0.0, 10.0, [tier]))


# ---------------------------------------------------------------------- converting


LABELLED = tier_with(2, 4, 8, labels=["a", "", "b", "c"])


@pytest.mark.parametrize(
    ("where", "times"),
    [("start", [0, 4, 8]), ("centre", [1, 6, 9]), ("end", [2, 8, 10])],
)
def test_points_from_intervals_skip_empty_ones(where, times):
    tier = points_from_intervals(LABELLED, where)
    assert [p.time for p in tier.points] == times and [p.mark for p in tier.points] == ["a", "b", "c"]
    assert tier.name == f"t_{where}"


def test_intervals_from_points():
    tier = intervals_from_points(PointTier("p", 0, 10, [Point(2, "a"), Point(5, "b")]))
    assert [(i.xmin, i.xmax, i.text) for i in tier.intervals] == [(0, 2, ""), (2, 5, "a"), (5, 10, "b")]


def test_points_on_the_tier_ends_make_no_empty_intervals():
    tier = intervals_from_points(PointTier("p", 0, 10, [Point(0, "first"), Point(5, "b"), Point(10, "end")]))
    assert [(i.xmin, i.text) for i in tier.intervals] == [(0, "first"), (5, "b")]


def test_no_points_gives_one_empty_interval():
    assert len(intervals_from_points(PointTier("p", 0, 10)).intervals) == 1


def test_converting_to_start_points_and_back_keeps_labels():
    back = intervals_from_points(points_from_intervals(tier_with(3, 6, labels=["a", "b", "c"]), "start"))
    assert [(i.xmin, i.text) for i in back.intervals] == [(0, "a"), (3, "b"), (6, "c")]


@pytest.mark.parametrize("seed", range(20))
def test_conversions_always_give_valid_tiers(seed):
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.01, 9.99, 10)).tolist()
    labels = [str(i) if rng.random() < 0.7 else "" for i in range(11)]
    tier = tier_with(*times, labels=labels)
    for where in ("start", "centre", "end"):
        points = points_from_intervals(tier, where)
        grid = TextGrid(0.0, 10.0, [points, intervals_from_points(points)])
        check_valid(grid)


# ---------------------------------------------------------------------- extracting and merging


def test_extract_copies_rather_than_shares():
    grid = aligned_grid()
    part = extract_tier(grid, 1)
    part.tiers[0].set_text(0, "changed")
    assert len(part.tiers) == 1 and grid.tiers[1].get_text(0) == ""


def test_merge_adds_copies_and_keeps_names_unique():
    grid, other = aligned_grid(), aligned_grid()
    merge_tiers(grid, other)
    assert [t.name for t in grid.tiers] == ["a", "b", "p", "other", "a_2", "b_2", "p_2", "other_2"]
    other.tiers[0].set_text(0, "changed")
    assert grid.tiers[4].get_text(0) == ""
    check_valid(grid)


def test_merging_twice_keeps_counting():
    grid = TextGrid(0.0, 10.0, [tier_with(name="a")])
    other = TextGrid(0.0, 10.0, [tier_with(name="a")])
    merge_tiers(grid, other)
    merge_tiers(grid, other)
    assert [t.name for t in grid.tiers] == ["a", "a_2", "a_3"]


def test_merging_a_different_length_is_refused_and_changes_nothing():
    grid = aligned_grid()
    with pytest.raises(TextGridError, match="covers"):
        merge_tiers(grid, TextGrid(0.0, 5.0, [tier_with(name="a", xmax=5.0)]))
    assert len(grid.tiers) == 4


def test_a_rounding_difference_in_length_is_absorbed():
    grid = aligned_grid()
    other = TextGrid(0.0, 10.0004, [IntervalTier("x", 0.0, 10.0004), PointTier("y", 0.0, 10.0004, [Point(10.0002)])])
    merge_tiers(grid, other)
    check_valid(grid)
    assert grid.tiers[-1].points == []


@pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
def test_praat_reads_converted_and_merged_tiers(tmp_path):
    grid = TextGrid(0.0, 10.0, [tier_with(2, 4, 8, labels=["a", "", "b", "c"], name="w")])
    grid.tiers.append(points_from_intervals(grid.tiers[0], "centre"))
    grid.tiers.append(intervals_from_points(grid.tiers[1]))
    merge_tiers(grid, TextGrid(0.0, 10.0, [tier_with(5, name="w")]))
    path = tmp_path / "g.TextGrid"
    grid.write(path)
    out = praat_engine.run_script(f'Read from file: "{path.as_posix()}"\nn = Get number of tiers\nwriteInfoLine: n\n')
    assert out.strip() == "4"


# ---------------------------------------------------------------------- real mouse drags in the running app


def press_drag_release(view, start, end, modifiers):
    left = Qt.MouseButton.LeftButton
    for kind, point, button, buttons in (
        (QEvent.Type.MouseButtonPress, start, left, left),
        (QEvent.Type.MouseMove, (start + end) / 2, Qt.MouseButton.NoButton, left),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, left),
        (QEvent.Type.MouseButtonRelease, end, left, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(view, QMouseEvent(kind, point, view.mapToGlobal(point), button, buttons, modifiers))


@pytest.fixture
def editor(window, qtbot, wav):  # noqa: F811
    window.open_sound(str(wav))
    ed = window.editor
    wait_for_analyses(qtbot, ed)
    grid = TextGrid(0.0, ed.doc.sound.duration, [
        tier_with(0.2, 0.5, 0.8, name="words", xmax=ed.doc.sound.duration, labels=["a", "b", "c", "d"]),
        tier_with(0.5, name="phrase", xmax=ed.doc.sound.duration),
    ])  # fmt: skip
    ed.doc.set_textgrid(grid)
    qtbot.waitExposed(window)
    ed.textgrid_view.resize(ed.textgrid_view.width(), 200)
    return ed


def at(view, t, tier=0):
    left, right = view.plot_area()
    v0, v1 = view.axis.view
    offset = view.mapTo(view.window(), view.rect().topLeft()).x() * 0
    return QPointF(left + (t - v0) / (v1 - v0) * (right - left) + offset, 10 + tier * 40)


def test_plain_drag_moves_one_boundary_only(editor):
    view = editor.textgrid_view
    press_drag_release(view, at(view, 0.5), at(view, 0.6), Qt.KeyboardModifier.NoModifier)
    words, phrase = editor.doc.textgrid.tiers
    assert words.boundaries[1] == pytest.approx(0.6, abs=0.01) and phrase.boundaries[0] == 0.5


def test_alt_drag_moves_aligned_boundaries_as_one_undo_step(editor):
    view = editor.textgrid_view
    before = editor.doc.textgrid.copy()
    press_drag_release(view, at(view, 0.5), at(view, 0.6), Qt.KeyboardModifier.AltModifier)
    words, phrase = editor.doc.textgrid.tiers
    assert words.boundaries[1] == phrase.boundaries[0] == pytest.approx(0.6, abs=0.01)
    assert editor.doc.undo_stack.undoText().startswith("Move 2 aligned")
    editor.doc.undo_stack.undo()
    assert editor.doc.textgrid == before


def test_ctrl_drag_stretches_the_neighbours_as_one_undo_step(editor):
    view = editor.textgrid_view
    before = editor.doc.textgrid.copy()
    press_drag_release(view, at(view, 0.5), at(view, 0.75), Qt.KeyboardModifier.ControlModifier)
    words, phrase = editor.doc.textgrid.tiers
    assert words.boundaries[0] == pytest.approx(0.3, abs=0.01)  # 0.2 scaled by 0.75 / 0.5
    assert words.boundaries[2] == pytest.approx(0.9, abs=0.01)
    assert phrase.boundaries[0] == 0.5
    check_valid(editor.doc.textgrid)
    editor.doc.undo_stack.undo()
    assert editor.doc.textgrid == before


def test_ctrl_drag_inside_a_selection_only_stretches_within_it(editor):
    view = editor.textgrid_view
    editor.axis.set_selection(0.3, 0.9)
    press_drag_release(view, at(view, 0.5), at(view, 0.6), Qt.KeyboardModifier.ControlModifier)
    words = editor.doc.textgrid.tiers[0]
    assert words.boundaries[0] == 0.2  # outside the selection
    assert words.boundaries[1] == pytest.approx(0.6, abs=0.01)
    assert words.boundaries[2] == pytest.approx(0.825, abs=0.01)


def test_alt_click_without_moving_adds_no_undo_step(editor):
    view = editor.textgrid_view
    press_drag_release(view, at(view, 0.5), at(view, 0.5), Qt.KeyboardModifier.AltModifier)
    assert not editor.doc.textgrid_dirty


# ---------------------------------------------------------------------- menu commands


def test_convert_commands_add_a_tier_and_undo(editor):
    view = editor.textgrid_view
    view.selected_tier = 0
    view.to_points("centre")
    grid = editor.doc.textgrid
    assert isinstance(grid.tiers[1], PointTier) and view.selected_tier == 1
    view.to_intervals()
    assert isinstance(editor.doc.textgrid.tiers[2], IntervalTier)
    editor.doc.undo_stack.undo()
    editor.doc.undo_stack.undo()
    assert len(editor.doc.textgrid.tiers) == 2


def test_converting_the_wrong_kind_of_tier_says_so(editor):
    messages = []
    view = editor.textgrid_view
    view.message.connect(messages.append)
    view.selected_tier = 0
    view.to_intervals()
    view.selected_tier = 1  # intervals with no labels
    view.to_points("start")
    assert any("point tier" in m for m in messages) and any("no labelled" in m for m in messages)
    assert len(editor.doc.textgrid.tiers) == 2


def test_extract_writes_one_tier(window, editor, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "words.TextGrid"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), ""))
    editor.textgrid_view.selected_tier = 0
    window.extract_tier_to_file()
    saved = TextGrid.read(path)
    assert [t.name for t in saved.tiers] == ["words"] and len(saved.tiers[0].intervals) == 4


def test_merge_file_is_undoable(window, editor, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "other.TextGrid"
    d = editor.doc.sound.duration
    TextGrid(0.0, d, [tier_with(0.3, name="extra", xmax=d)]).write(path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    window.merge_textgrid_file()
    assert [t.name for t in editor.doc.textgrid.tiers] == ["words", "phrase", "extra"]
    editor.doc.undo_stack.undo()
    assert len(editor.doc.textgrid.tiers) == 2


def test_merging_a_mismatched_file_warns_and_changes_nothing(window, editor, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "other.TextGrid"
    TextGrid(0.0, 99.0, [tier_with(name="extra", xmax=99.0)]).write(path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    window.merge_textgrid_file()
    assert warned and len(editor.doc.textgrid.tiers) == 2 and editor.doc.undo_stack.count() == 0
