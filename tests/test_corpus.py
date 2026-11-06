"""Corpus annotations, read through the bundled Praat from files laid out as in each corpus."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402
from PyQt6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from phonolab.core import corpus, praat_engine  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.core.textgrid import IntervalTier, PointTier, TextGrid  # noqa: E402
from tests.test_time_edit import check_valid  # noqa: E402
from tests.test_ui_smoke import wait_for_analyses, wav, window  # noqa: E402, F401

needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
HEADER = "signal s01\ntype 0\ncolor 121\nfont *\nseparator ;\nnfields {}\n#\n"
BUCKEYE_WORDS = "    0.5  121 {B_TRANS}; ; ; null\n    0.9  121 okay; ow k ey; ow k ey; UH\n    1.4  121 um; ah m; ah m; UH\n    2.0  121 {E_TRANS}; ; ; null\n"  # noqa: E501
BUCKEYE_PHONES = "    0.5  122 {B_TRANS}\n    0.7  122 ow\n    0.8  122 k\n    0.9  122 ey\n    2.0  122 {E_TRANS}\n"


def tier(grid, name):
    return next(t for t in grid.tiers if t.name == name)


def texts(t):
    return [iv.text for iv in t.intervals]


@pytest.fixture
def timit(tmp_path):
    """TIMIT audio really is NIST SPHERE under a .wav name."""
    path = tmp_path / "sa1.wav"
    sf.write(str(path), np.sin(np.arange(20000) / 20) * 0.3, 16000, format="NIST", subtype="PCM_16")
    (tmp_path / "sa1.phn").write_text(
        "0 3050 h#\n3050 4559 sh\n4559 5723 ix\n5723 6642 hv\n6642 8772 eh\n"
        "8772 9190 dcl\n9190 10337 jh\n10337 20000 h#\n"
    )
    (tmp_path / "sa1.wrd").write_text("3050 5723 she\n5723 10337 had\n")
    (tmp_path / "sa1.txt").write_text("0 20000 She had.\n")
    return path


@pytest.fixture
def buckeye(tmp_path):
    path = tmp_path / "s01.wav"
    sf.write(str(path), np.sin(np.arange(32000) / 20) * 0.3, 16000)
    (tmp_path / "s01.words").write_text(HEADER.format(4) + BUCKEYE_WORDS)
    (tmp_path / "s01.phones").write_text(HEADER.format(1) + BUCKEYE_PHONES)
    (tmp_path / "s01.log").write_text(HEADER.format(1) + "    0.5  121 <EXCLUDE>\n    2.0  121 <EXCLUDE>\n")
    (tmp_path / "s01.txt").write_text("okay um\n")
    return path


@pytest.fixture
def esps(tmp_path):
    path = tmp_path / "labels.lab"
    path.write_text(HEADER.format(1) + "    0.500000  121 a\n    1.250000  121 b\n    2.000000  121 c\n")
    return path


# ---------------------------------------------------------------------- reading


@needs_praat
def test_timit_gives_phones_as_ipa_and_arpabet_on_the_right_samples(timit):
    grid = corpus.read_adjacent(timit, "TIMIT")
    check_valid(grid)
    ipa, arpa = tier(grid, "phon-ipa"), tier(grid, "phon-arpa")
    assert texts(arpa)[1:3] == ["sh", "ix"]
    assert texts(ipa)[1:3] == [r"\sh", r"\i-"]
    assert arpa.intervals[1].xmin == pytest.approx(3050 / 16000)
    assert grid.xmax == pytest.approx(20000 / 16000)


@needs_praat
def test_timit_words_are_there(timit):
    grid = corpus.read_adjacent(timit, "TIMIT")
    labels = [text for t in grid.tiers for text in texts(t) if isinstance(t, IntervalTier)]
    assert "she" in labels and "had" in labels


def test_our_sound_loader_reads_timits_sphere_audio(timit):
    sound = Sound.from_file(timit)
    assert sound.sampling_rate == 16000 and sound.n_samples == 20000


@needs_praat
def test_upper_case_names_from_original_timit_discs(tmp_path):
    wav_path = tmp_path / "SA1.WAV"
    sf.write(str(wav_path), np.zeros(16000), 16000, format="NIST", subtype="PCM_16")
    (tmp_path / "SA1.PHN").write_text("0 16000 h#\n")
    (tmp_path / "SA1.WRD").write_text("0 16000 x\n")
    (tmp_path / "SA1.TXT").write_text("0 16000 x\n")
    assert corpus.read_adjacent(wav_path, "TIMIT").xmax == pytest.approx(1.0)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SA1.PHN", "SA1.TXT", "SA1.WAV", "SA1.WRD"]


@needs_praat
def test_buckeye_gives_phones_and_words(buckeye):
    grid = corpus.read_adjacent(buckeye, "Buckeye")
    check_valid(grid)
    assert texts(tier(grid, "phon"))[1:4] == ["ow", "k", "ey"]
    words = tier(grid, "words")
    assert texts(words)[1:3] == ["okay", "um"]
    assert (words.intervals[1].xmin, words.intervals[1].xmax) == pytest.approx((0.5, 0.9))


@needs_praat
def test_esps_as_intervals(esps):
    grid = corpus.read_esps(esps)
    t = grid.tiers[0]
    assert isinstance(t, IntervalTier) and [(i.xmax, i.text) for i in t.intervals] == [
        (0.5, "a"),
        (1.25, "b"),
        (2, "c"),
    ]


@needs_praat
def test_esps_as_points(esps):
    t = corpus.read_esps(esps, points=True).tiers[0]
    assert isinstance(t, PointTier) and [(p.time, p.mark) for p in t.points] == [(0.5, "a"), (1.25, "b"), (2, "c")]


@needs_praat
def test_a_lone_phn_file_reads_as_a_textgrid(timit):
    grid = corpus.read_with_praat(timit.with_suffix(".phn"))
    assert isinstance(grid, TextGrid) and grid.xmax == pytest.approx(1.25)


@needs_praat
def test_a_path_with_spaces_and_an_apostrophe(tmp_path):
    folder = tmp_path / "it's a folder"
    folder.mkdir()
    path = folder / "labels.lab"
    path.write_text(HEADER.format(1) + "    0.5  121 a\n")
    assert corpus.read_esps(path).xmax == pytest.approx(0.5)


@needs_praat
def test_a_non_ascii_path(tmp_path):
    folder = tmp_path / "données_语音"
    folder.mkdir()
    path = folder / "labels.lab"
    path.write_text(HEADER.format(1) + "    0.5  121 a\n")
    assert corpus.read_esps(path).xmax == pytest.approx(0.5)


# ---------------------------------------------------------------------- failing well


@needs_praat
@pytest.mark.parametrize("name", corpus.CORPORA)
def test_a_recording_without_its_annotations_says_so(tmp_path, name):
    path = tmp_path / "lonely.wav"
    sf.write(str(path), np.zeros(16000), 16000)
    with pytest.raises(corpus.CorpusError, match="lonely"):
        corpus.read_adjacent(path, name)


def test_unknown_corpora_never_reach_praat():
    with pytest.raises(corpus.CorpusError, match="Unknown corpus"):
        corpus.read_adjacent("x.wav", 'TIMIT): "a"\nwriteFile: "pwned", "x')


@needs_praat
def test_a_sound_read_as_annotations_is_refused(tmp_path):
    path = tmp_path / "not-annotations.wav"
    sf.write(str(path), np.zeros(16000), 16000)
    with pytest.raises(corpus.CorpusError):
        corpus.read_with_praat(path)


@needs_praat
def test_rubbish_is_refused(tmp_path):
    path = tmp_path / "rubbish.lab"
    path.write_bytes(b"\x00\x01rubbish")
    with pytest.raises(corpus.CorpusError):
        corpus.read_with_praat(path)


def test_without_praat_the_message_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(praat_engine, "available", lambda: False)
    with pytest.raises(corpus.CorpusError, match="bundled Praat"):
        corpus.read_esps(tmp_path / "x.lab")


# ---------------------------------------------------------------------- CGN's TextGrids, which need no Praat


def test_cgn_style_latin1_textgrids_open(tmp_path):
    path = tmp_path / "fn000001.awd"
    grid = TextGrid.for_duration(1.0)
    grid.tiers[0].set_text(0, "één café")
    path.write_bytes(grid.to_text().encode("latin-1"))
    assert TextGrid.read(path).tiers[0].get_text(0) == "één café"


# ---------------------------------------------------------------------- in the app


@needs_praat
def test_opening_a_corpus_recording_brings_its_tiers(window, qtbot, timit, monkeypatch):  # noqa: F811
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(timit), ""))
    window.open_corpus_recording("TIMIT")
    doc = window.editor.doc
    assert doc.sound.path == timit and doc.textgrid is not None and doc.textgrid_dirty
    assert "phon-ipa" in [t.name for t in doc.textgrid.tiers]
    wait_for_analyses(qtbot, window.editor)


@needs_praat
def test_a_failed_corpus_read_warns_and_opens_nothing(window, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "lonely.wav"
    sf.write(str(path), np.zeros(16000), 16000)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    window.open_corpus_recording("Buckeye")
    assert warned and window.tabs.count() == 0


@needs_praat
def test_esps_labels_attach_to_the_current_sound(window, qtbot, wav, esps, monkeypatch):  # noqa: F811
    window.open_sound(str(wav))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(esps), ""))
    window.open_annotation_file("esps points")
    assert isinstance(window.editor.doc.textgrid.tiers[0], PointTier)


@needs_praat
def test_annotations_never_silently_replace_unsaved_work(window, qtbot, wav, esps, monkeypatch):  # noqa: F811
    window.open_sound(str(wav))
    doc = window.editor.doc
    doc.set_textgrid(TextGrid.for_duration(1.0), saved=False)
    mine = doc.textgrid
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(esps), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    window.open_annotation_file("esps")
    assert doc.textgrid is mine
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    window.open_annotation_file("esps")
    assert doc.textgrid is not mine
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Discard)
