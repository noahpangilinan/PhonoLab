import parselmouth
import pytest
from parselmouth.praat import call

from phonolab.core.textgrid import IntervalTier, PointTier, TextGrid, TextGridError

LABEL = 'say "hi" ü'  # quotes and non-ASCII exercise escaping and encodings


@pytest.fixture
def grid():
    tg = TextGrid.for_duration(2.0, ["words"], ["tones"])
    words = tg.tiers[0]
    words.add_boundary(0.5)
    words.add_boundary(1.5)
    words.set_text(1, LABEL)
    tg.tiers[1].add_point(1.0, "H*")
    return tg


def assert_contiguous(tier: IntervalTier):
    assert tier.intervals[0].xmin == tier.xmin
    assert tier.intervals[-1].xmax == tier.xmax
    for a, b in zip(tier.intervals, tier.intervals[1:], strict=False):
        assert a.xmax == b.xmin and a.xmin < a.xmax


def test_add_boundary_splits_and_keeps_text_left():
    tier = IntervalTier("w", 0, 1)
    tier.set_text(0, "abc")
    assert tier.add_boundary(0.4) == 1
    assert [iv.text for iv in tier.intervals] == ["abc", ""]
    assert_contiguous(tier)


@pytest.mark.parametrize("t", [0.0, 1.0, -1, 2, 0.4])
def test_add_boundary_rejects_edges_and_duplicates(t):
    tier = IntervalTier("w", 0, 1)
    tier.add_boundary(0.4)
    with pytest.raises(TextGridError):
        tier.add_boundary(t)


def test_remove_boundary_merges_text(grid):
    words = grid.tiers[0]
    words.set_text(0, "a")
    words.remove_boundary(1)
    assert words.intervals[0].text == "a" + LABEL
    assert len(words.intervals) == 2
    assert_contiguous(words)


def test_move_boundary_is_clamped_between_neighbours(grid):
    words = grid.tiers[0]
    t = words.move_boundary(1, 5.0)
    assert 0.5 < t < 1.5
    assert_contiguous(words)


def test_interval_at_and_boundary_near(grid):
    words = grid.tiers[0]
    assert words.interval_at(0.1) == 0
    assert words.interval_at(0.5) == 1  # boundary belongs to the right interval
    assert words.interval_at(1.99) == 2
    assert words.boundary_near(0.52, 0.05) == 1
    assert words.boundary_near(1.0, 0.05) is None


def test_points_stay_sorted():
    tier = PointTier("p", 0, 2)
    tier.add_point(1.5, "b")
    tier.add_point(0.5, "a")
    assert [p.mark for p in tier.points] == ["a", "b"]
    with pytest.raises(TextGridError):
        tier.add_point(0.5)
    assert tier.move_point(0, 1.9) < 1.5


@pytest.mark.parametrize("short", [False, True])
def test_roundtrip_via_our_reader(grid, tmp_path, short):
    path = tmp_path / "g.TextGrid"
    grid.write(path, short=short)
    assert TextGrid.read(path) == grid


@pytest.mark.parametrize("short", [False, True])
def test_praat_reads_our_files(grid, tmp_path, short):
    path = tmp_path / "g.TextGrid"
    grid.write(path, short=short)
    obj = parselmouth.read(str(path))
    assert call(obj, "Get number of tiers") == 2
    assert call(obj, "Get label of interval", 1, 2) == LABEL
    assert call(obj, "Get label of point", 2, 1) == "H*"
    assert call(obj, "Get time of point", 2, 1) == pytest.approx(1.0)


@pytest.mark.parametrize("command", ["Save as text file", "Save as short text file"])
def test_we_read_praat_files(grid, tmp_path, command):
    src = tmp_path / "ours.TextGrid"
    grid.write(src)
    obj = parselmouth.read(str(src))
    praat_path = tmp_path / "praat.TextGrid"
    call(obj, command, str(praat_path))  # Praat writes UTF-16 for non-ASCII labels
    assert TextGrid.read(praat_path) == grid


def test_empty_textgrid_roundtrip(tmp_path):
    tg = TextGrid(0, 1)
    path = tmp_path / "e.TextGrid"
    tg.write(path)
    assert TextGrid.read(path) == tg


def test_truncated_file_raises(tmp_path):
    path = tmp_path / "bad.TextGrid"
    path.write_text('File type = "ooTextFile"\nObject class = "TextGrid"\n0\n1\n<exists>\n3\n')
    with pytest.raises(TextGridError):
        TextGrid.read(path)
