import csv

import numpy as np
import pytest

from phonolab.core import batch
from phonolab.core.batch import BatchOptions
from phonolab.core.textgrid import TextGrid
from tests.conftest import make_vowel


@pytest.fixture
def folder(tmp_path):
    make_vowel(f0=120, duration=1.0).save(tmp_path / "a.wav")
    sub = tmp_path / "sub"
    sub.mkdir()
    make_vowel(f0=200, duration=0.8).save(sub / "b.flac")
    (tmp_path / "notes.txt").write_text("not audio")
    return tmp_path


def test_find_sounds(folder):
    assert [p.name for p in batch.find_sounds(folder)] == ["a.wav", "b.flac"]
    assert [p.name for p in batch.find_sounds(folder, recursive=False)] == ["a.wav"]


def test_measure_whole_file(folder):
    (row,) = batch.measure_file(folder / "a.wav", BatchOptions())
    assert row["f0_mean_hz"] == pytest.approx(120, abs=2)
    assert row["F1_mean_hz"] == pytest.approx(700, rel=0.1)
    assert row["jitter_local_pct"] < 0.1
    assert row["cpps_db"] > 10
    assert "error" not in row


def test_measure_per_interval(folder):
    tg = TextGrid.for_duration(1.0, ["words"])
    tg.tiers[0].add_boundary(0.3)
    tg.tiers[0].add_boundary(0.7)
    tg.tiers[0].set_text(1, r"h\ae t")
    tg.write(folder / "a.TextGrid")
    rows = batch.measure_file(folder / "a.wav", BatchOptions(measures=frozenset({"pitch"}), tier="words"))
    assert len(rows) == 1  # only labelled intervals
    assert rows[0]["label"] == "hæ t" and rows[0]["start_s"] == 0.3
    assert rows[0]["f0_median_hz"] == pytest.approx(120, abs=2)


def test_errors_become_rows(folder):
    (row,) = batch.measure_file(folder / "a.wav", BatchOptions(tier="words"))  # no TextGrid yet
    assert "no TextGrid" in row["error"]
    bad = folder / "broken.wav"
    bad.write_bytes(b"junk")
    (row,) = batch.measure_file(bad, BatchOptions())
    assert "Could not read" in row["error"]


def test_write_csv_unions_columns(tmp_path):
    rows = [{"file": "a", "x": 1.0, "error": "oops"}, {"file": "b", "y": np.nan}]
    path = tmp_path / "out.csv"
    assert batch.write_csv(rows, path) == 2
    with open(path, encoding="utf-8") as fh:
        data = list(csv.DictReader(fh))
    assert list(data[0]) == ["file", "x", "y", "error"]
    assert data[1]["y"] == ""
