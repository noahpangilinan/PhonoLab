"""Audio edits and everything that has to follow them on the timeline.

Most of the checks are invariants run over random edits, because the awkward cases are the ones nobody
thinks to write down: boundaries on the edit, cuts across several intervals, edits at the very ends.
"""

import gc
import os
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from phonolab.core.corrections import Corrections  # noqa: E402
from phonolab.core.sound import LongSoundError, Sound  # noqa: E402
from phonolab.core.textgrid import (  # noqa: E402
    Interval,
    IntervalTier,
    Point,
    PointTier,
    TextGrid,
    TextGridError,
)
from phonolab.core.time_edit import Splice  # noqa: E402
from phonolab.ui.document import Document  # noqa: E402

RATE = 1000.0


def grid_of(*bounds_and_labels, duration=10.0):
    """``grid_of((2, "a"), (5, "b"))``: intervals ending at 2 and 5, then an empty one to the end."""
    intervals, start = [], 0.0
    for end, text in bounds_and_labels:
        intervals.append(Interval(start, end, text))
        start = end
    if start < duration:
        intervals.append(Interval(start, duration, ""))
    return TextGrid(0.0, duration, [IntervalTier("t", 0.0, duration, intervals)])


def spans(grid, tier=0):
    return [(round(i.xmin, 9), round(i.xmax, 9), i.text) for i in grid.tiers[tier].intervals]


def check_valid(grid: TextGrid):
    """Everything Praat itself requires of a TextGrid."""
    assert grid.xmax > grid.xmin
    for tier in grid.tiers:
        assert (tier.xmin, tier.xmax) == (grid.xmin, grid.xmax)
        if isinstance(tier, IntervalTier):
            assert tier.intervals[0].xmin == grid.xmin and tier.intervals[-1].xmax == grid.xmax
            for iv in tier.intervals:
                assert iv.xmax > iv.xmin
            for left, right in zip(tier.intervals, tier.intervals[1:], strict=False):
                assert left.xmax == right.xmin
        else:
            times = [p.time for p in tier.points]
            assert times == sorted(times) and len(set(times)) == len(times)
            assert all(grid.xmin <= t <= grid.xmax for t in times)


# ---------------------------------------------------------------------- cutting


def test_cut_inside_an_interval_shrinks_it():
    out = Splice(3.0, 1.0, 0.0).applied_to(grid_of((2, "a"), (6, "b")))
    assert spans(out) == [(0, 2, "a"), (2, 5, "b"), (5, 9, "")] and out.xmax == 9


def test_cut_across_a_boundary_trims_both_sides():
    out = Splice(1.0, 2.0, 0.0).applied_to(grid_of((2, "a"), (6, "b")))
    assert spans(out) == [(0, 1, "a"), (1, 4, "b"), (4, 8, "")]


def test_interval_wholly_inside_a_cut_goes():
    out = Splice(1.0, 5.0, 0.0).applied_to(grid_of((2, "a"), (4, "gone"), (6, "b")))
    assert spans(out) == [(0, 1, "a"), (1, 5, "")]


def test_cutting_exactly_one_interval_keeps_its_neighbours_whole():
    out = Splice(2.0, 2.0, 0.0).applied_to(grid_of((2, "a"), (4, "gone"), (6, "b")))
    assert spans(out) == [(0, 2, "a"), (2, 4, "b"), (4, 8, "")]


@pytest.mark.parametrize(("start", "removed", "first"), [(0.0, 2.0, (0, 2, "b")), (0.0, 1.0, (0, 1, "a"))])
def test_cut_from_the_very_start(start, removed, first):
    assert spans(Splice(start, removed, 0.0).applied_to(grid_of((2, "a"), (4, "b"))))[0] == first


def test_cut_to_the_very_end():
    out = Splice(8.0, 2.0, 0.0).applied_to(grid_of((2, "a"), (9, "b")))
    assert spans(out) == [(0, 2, "a"), (2, 8, "b")] and out.xmax == 8


def test_points_in_a_cut_go_and_later_ones_move():
    grid = TextGrid(
        0,
        10,
        [
            PointTier(
                "p",
                0,
                10,
                [Point(1, "keep"), Point(3, "at start"), Point(4, "in"), Point(5, "at end"), Point(7, "after")],
            )
        ],
    )  # noqa: E501
    out = Splice(3.0, 2.0, 0.0).applied_to(grid)
    assert [(p.time, p.mark) for p in out.tiers[0].points] == [(1, "keep"), (3, "at end"), (5, "after")]


def test_cutting_a_whole_grid_is_refused():
    with pytest.raises(TextGridError):
        Splice(0.0, 10.0, 0.0).applied_to(grid_of((5, "a")))


# ---------------------------------------------------------------------- inserting


def test_insert_inside_an_interval_stretches_it():
    out = Splice(1.0, 0.0, 3.0).applied_to(grid_of((2, "a"), (4, "b")))
    assert spans(out) == [(0, 5, "a"), (5, 7, "b"), (7, 13, "")] and out.xmax == 13


def test_insert_at_a_boundary_gets_an_empty_interval():
    out = Splice(2.0, 0.0, 3.0).applied_to(grid_of((2, "a"), (4, "b")))
    assert spans(out) == [(0, 2, "a"), (2, 5, ""), (5, 7, "b"), (7, 13, "")]


def test_insert_at_the_very_start_and_end():
    grid = grid_of((10, "a"))
    assert spans(Splice(0.0, 0.0, 1.0).applied_to(grid)) == [(0, 1, ""), (1, 11, "a")]
    assert spans(Splice(10.0, 0.0, 1.0).applied_to(grid)) == [(0, 10, "a"), (10, 11, "")]


def test_a_point_at_an_insertion_stays_on_its_sample():
    grid = TextGrid(0, 10, [PointTier("p", 0, 10, [Point(2, "before"), Point(3, "on"), Point(4, "after")])])
    out = Splice(3.0, 0.0, 1.0).applied_to(grid)
    assert [p.time for p in out.tiers[0].points] == [2, 4, 5]


# ---------------------------------------------------------------------- replacing


def test_replacing_rescales_labels_inside():
    out = Splice(2.0, 4.0, 2.0).applied_to(grid_of((2, "a"), (4, "b"), (6, "c")))
    assert spans(out) == [(0, 2, "a"), (2, 3, "b"), (3, 4, "c"), (4, 8, "")]


def test_replacing_exactly_an_interval_keeps_its_label():
    assert spans(Splice(2.0, 2.0, 5.0).applied_to(grid_of((2, "a"), (4, "b"))))[1] == (2, 7, "b")


# ---------------------------------------------------------------------- a TextGrid not matching the sound


def test_a_grid_shorter_than_the_sound_ignores_edits_past_its_end():
    grid = grid_of((2, "a"), duration=5.0)
    assert Splice(6.0, 1.0, 0.0).applied_to(grid) == grid
    assert Splice(6.0, 0.0, 1.0).applied_to(grid) == grid


def test_a_cut_running_past_the_grids_end_stops_there():
    out = Splice(4.0, 3.0, 0.0).applied_to(grid_of((2, "a"), duration=5.0))
    assert out.xmax == 4 and spans(out)[-1] == (2, 4, "")


# ---------------------------------------------------------------------- corrections


def test_corrections_after_a_cut_shift_and_trim():
    c = Corrections(unvoiced=((1, 2), (3, 6), (8, 9)), added_pulses=(1.5, 4.0, 8.5))
    out = c.spliced(Splice(4.0, 3.0, 0.0))
    assert out.unvoiced == ((1, 2), (3, 4), (5, 6)) and out.added_pulses == (1.5, 5.5)


def test_a_cut_inside_a_correction_shrinks_it_in_one_piece():
    assert Corrections(octaves=((1, 9, 2.0),)).spliced(Splice(4.0, 2.0, 0.0)).octaves == ((1, 7, 2.0),)


def test_a_correction_doesnt_cover_pasted_sound():
    out = Corrections(unvoiced=((1, 5),)).spliced(Splice(3.0, 0.0, 2.0))
    assert out.unvoiced == ((1, 3), (5, 7))


def test_a_correction_inside_a_replaced_stretch_goes():
    assert Corrections(unvoiced=((3, 4),)).spliced(Splice(2.0, 4.0, 1.0)).is_empty


# ---------------------------------------------------------------------- sounds


def test_splicing_makes_a_new_sound_and_leaves_the_old_alone():
    sound = Sound(np.arange(10.0), RATE, title="s")
    new = sound.spliced(2, 5, np.array([[7.0]]))
    assert new.mono.tolist() == [0, 1, 7, 5, 6, 7, 8, 9] and sound.n_samples == 10
    assert new.id != sound.id and new.title == "s"


def test_splicing_keeps_every_channel():
    sound = Sound(np.column_stack([np.arange(6.0), -np.arange(6.0)]), RATE)
    assert sound.spliced(1, 3).samples[:, 1].tolist() == [0, -3, -4, -5]


# ---------------------------------------------------------------------- random edits: the invariants


def ramp(n=4000, channels=1):
    """Every sample holds its own index, so any sample can be identified after any number of edits."""
    return Sound(np.column_stack([np.arange(n, dtype=float) * (c + 1) for c in range(channels)]), RATE, title="ramp")


def annotated(sound):
    """A grid with boundaries and points on exact samples, named after the sample they mark."""
    rng = np.random.default_rng(sound.n_samples)
    picks = np.sort(rng.choice(np.arange(1, sound.n_samples - 1), 12, replace=False))
    bounds = [0.0, *(picks / RATE), sound.duration]
    intervals = [Interval(a, b, str(int(round(a * RATE)))) for a, b in zip(bounds, bounds[1:], strict=False)]
    points = [Point(i / RATE, str(int(i))) for i in picks[::2] + 1]
    return TextGrid(
        0, sound.duration, [IntervalTier("i", 0, sound.duration, intervals), PointTier("p", 0, sound.duration, points)]
    )  # noqa: E501


def random_edit(rng, doc):
    n = doc.sound.n_samples
    a = int(rng.integers(0, n + 1))
    kind = rng.choice(["cut", "insert", "replace"])
    if rng.random() < 0.3:  # aim at existing boundaries, the awkward case
        boundaries = doc.textgrid.tiers[0].boundaries
        if boundaries:
            a = doc.sound.time_to_index(boundaries[int(rng.integers(len(boundaries)))])
    b = min(n, a + int(rng.integers(1, max(2, n // 4))))
    new = -1.0 - np.arange(int(rng.integers(1, 300)), dtype=float)[:, None]  # negative: visibly not original
    new = np.repeat(new, doc.sound.n_channels, axis=1) * np.arange(1, doc.sound.n_channels + 1)
    if kind == "cut":
        return ("Cut", a, b, None) if 0 < b - a < n else None
    return ("Insert", a, a, new) if kind == "insert" else ("Replace", a, b, new)


@pytest.mark.parametrize("seed", range(40))
def test_labels_stay_on_their_samples_through_random_cuts_and_inserts(qapp, seed):
    """A boundary named after a sample must still sit on that sample, however many edits have happened."""
    rng = np.random.default_rng(seed)
    doc = Document(ramp())
    doc.set_textgrid(annotated(doc.sound), saved=False)
    for _ in range(25):
        step = random_edit(rng, doc)
        if step is None or step[0] == "Replace":
            continue
        doc.splice_audio(*step)
        check_valid(doc.textgrid)
        assert doc.textgrid.xmax == pytest.approx(doc.sound.duration)
        samples = doc.sound.mono
        for iv in doc.textgrid.tiers[0].intervals[1:]:
            i = doc.sound.time_to_index(iv.xmin)
            # A trimmed interval begins on a later sample than its name, but never an earlier one.
            if iv.text and i < len(samples) and samples[i] >= 0:
                assert samples[i] >= int(iv.text)
        for p in doc.textgrid.tiers[1].points:
            assert samples[doc.sound.time_to_index(p.time)] == int(p.mark)


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("channels", [1, 2])
def test_undoing_random_edits_restores_everything_exactly(qapp, seed, channels):
    rng = np.random.default_rng(1000 + seed)
    doc = Document(ramp(channels=channels))
    doc.set_textgrid(annotated(doc.sound))
    doc.corrections = Corrections(unvoiced=((0.5, 0.9),), octaves=((1.0, 2.0, 2.0),), added_pulses=(0.2, 3.0))
    original = doc.sound.samples.copy()
    grid, corrections = doc.textgrid.copy(), doc.corrections
    states = []
    for _ in range(20):
        step = random_edit(rng, doc)
        if step is None:
            continue
        states.append((doc.sound.samples.copy(), doc.textgrid.copy(), doc.corrections))
        doc.splice_audio(*step)
        check_valid(doc.textgrid)
    finals = doc.sound.samples.copy(), doc.textgrid.copy(), doc.corrections
    for samples, tg, corr in reversed(states):
        doc.undo_stack.undo()
        assert np.array_equal(doc.sound.samples, samples) and doc.textgrid == tg and doc.corrections == corr
    assert np.array_equal(doc.sound.samples, original) and doc.textgrid == grid and doc.corrections == corrections
    assert not doc.audio_dirty
    while doc.undo_stack.canRedo():
        doc.undo_stack.redo()
    assert np.array_equal(doc.sound.samples, finals[0]) and doc.textgrid == finals[1] and doc.corrections == finals[2]


@pytest.mark.parametrize("seed", range(20))
def test_grids_from_random_edits_survive_a_round_trip_through_the_file_format(qapp, seed, tmp_path):
    rng = np.random.default_rng(2000 + seed)
    doc = Document(ramp())
    doc.set_textgrid(annotated(doc.sound))
    for _ in range(15):
        if step := random_edit(rng, doc):
            doc.splice_audio(*step)
    path = tmp_path / "g.TextGrid"
    doc.textgrid.write(path)
    assert TextGrid.read(path) == doc.textgrid


def test_corrections_never_cover_negative_or_out_of_range_time(qapp):
    rng = np.random.default_rng(7)
    doc = Document(ramp())
    doc.set_textgrid(annotated(doc.sound))
    doc.corrections = Corrections(unvoiced=((0.5, 1.5), (2.0, 3.5)), added_pulses=(0.1, 3.9))
    for _ in range(200):
        step = random_edit(rng, doc)
        if step is None or doc.sound.n_samples < 50 or doc.sound.n_samples > 20000:
            continue
        doc.splice_audio(*step)
        for start, end in doc.corrections.unvoiced:
            assert 0 <= start < end <= doc.sound.duration + 1e-9
        assert all(0 <= t <= doc.sound.duration for t in doc.corrections.added_pulses)


# ---------------------------------------------------------------------- the document


def test_undo_history_holds_only_what_changed(qapp):
    doc = Document(ramp(n=1_000_000))
    doc.splice_audio("Cut", 10, 20)
    command = doc.undo_stack.command(0)
    assert len(command.removed) == 10 and len(command.inserted) == 0


@pytest.mark.parametrize("inserted", [None, np.ones((5, 1))], ids=["cut", "paste"])
def test_undo_history_never_pins_the_old_audio(qapp, inserted):
    """A view of the old samples, even an empty one, would keep all of them in memory."""
    doc = Document(ramp(n=100_000))
    old = weakref.ref(doc.sound.samples)
    doc.splice_audio("Edit", 10, 20, inserted)
    gc.collect()
    assert old() is None
    command = doc.undo_stack.command(0)
    assert command.removed.base is None and command.inserted.base is None


def test_memory_stays_flat_over_many_edits(qapp):
    doc = Document(ramp(n=100_000))
    refs = []
    for i in range(30):
        refs.append(weakref.ref(doc.sound.samples))
        doc.splice_audio("Cut", i, i + 5)
    gc.collect()
    assert sum(r() is not None for r in refs) == 0


def test_undoing_back_to_the_saved_audio_is_clean(qapp, tmp_path):
    path = tmp_path / "a.wav"
    ramp().save(path)
    doc = Document(Sound.from_file(path))
    assert not doc.is_dirty
    doc.splice_audio("Cut", 10, 20)
    assert doc.audio_dirty and doc.is_dirty and doc.title.endswith("*")
    doc.undo_stack.undo()
    assert not doc.audio_dirty and not doc.is_dirty
    doc.undo_stack.redo()
    assert doc.audio_dirty


def test_undo_past_a_save_is_dirty_again(qapp, tmp_path):
    doc = Document(ramp())
    doc.splice_audio("Cut", 10, 20)
    doc.save_sound(tmp_path / "a.wav")
    assert not doc.audio_dirty
    doc.undo_stack.undo()
    assert doc.audio_dirty and doc.sound.path == tmp_path / "a.wav"


def test_a_saved_edit_reads_back_identically(qapp, tmp_path):
    sound = Sound(np.sin(np.arange(4000) / 30) * 0.5, RATE, title="s")
    doc = Document(sound)
    doc.splice_audio("Cut", 100, 900)
    path = tmp_path / "a.flac"
    doc.save_sound(path)
    assert np.allclose(Sound.from_file(path).mono, doc.sound.mono, atol=1e-4)


def test_saving_elsewhere_makes_corrections_unsaved_there(qapp, tmp_path):
    path = tmp_path / "a.wav"
    ramp().save(path)
    doc = Document(Sound.from_file(path))
    doc.correct("Unvoice", Corrections(unvoiced=((1, 2),)))
    doc.save_corrections()
    assert not doc.corrections_dirty
    doc.save_sound(tmp_path / "b.wav")
    assert doc.corrections_dirty


def test_cutting_everything_is_refused_and_changes_nothing(qapp):
    doc = Document(ramp())
    with pytest.raises(TextGridError):
        doc.splice_audio("Cut", 0, doc.sound.n_samples)
    assert doc.sound.n_samples == 4000 and doc.undo_stack.count() == 0


def test_a_refused_edit_leaves_no_trace(qapp):
    doc = Document(ramp())
    doc.set_textgrid(TextGrid.for_duration(1.0))  # shorter than the sound
    grid = doc.textgrid.copy()
    with pytest.raises(TextGridError):
        doc.splice_audio("Cut", 0, 1000)
    assert doc.textgrid == grid and doc.sound.n_samples == 4000 and not doc.audio_dirty


def test_empty_edits_add_nothing_to_undo(qapp):
    doc = Document(ramp())
    doc.splice_audio("Nothing", 5, 5)
    assert doc.undo_stack.count() == 0 and not doc.audio_dirty


def test_long_sounds_refuse_edits(qapp, tmp_path, monkeypatch):
    from phonolab.core import sound as sound_module

    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 100)
    path = tmp_path / "long.wav"
    ramp().save(path)
    long_sound = Sound.from_file(path)
    assert long_sound.is_long
    with pytest.raises(LongSoundError):
        Document(long_sound).splice_audio("Cut", 0, 10)
    with pytest.raises(LongSoundError):
        long_sound.spliced(0, 10)
    long_sound.release()


# ---------------------------------------------------------------------- caches that once held per-object state


def test_praat_gets_the_edited_audio_not_a_cached_wav(qapp):
    from phonolab.core import praat_engine

    if not praat_engine.available():
        pytest.skip("run packaging/fetch_praat.py first")
    doc = Document(Sound(np.sin(np.arange(8000) / 10) * 0.5, 8000.0, title="s"))
    first = praat_engine.sound_file(doc.sound)
    doc.splice_audio("Cut", 0, 4000)
    second = praat_engine.sound_file(doc.sound)
    assert first != second
    script = f'Read from file: "{second.as_posix()}"\nd = Get total duration\nwriteInfoLine: d\n'
    duration = praat_engine.run_script(script)
    assert float(duration.split()[0]) == pytest.approx(0.5)


def test_the_manipulation_cache_keys_on_the_sound_not_its_address():
    import inspect

    from phonolab.core import manipulation

    assert "sound.id" in inspect.getsource(manipulation._manipulation)
    a = Sound(np.zeros(10), RATE)
    b = a.spliced(0, 1)
    assert a.id != b.id
