import pytest

from phonolab.core import praat_engine
from phonolab.core.ipa import TRIGRAPHS, to_trigraphs, to_unicode
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid
from phonolab.ui.ipa_palette import GROUPS


@pytest.mark.skipif(not praat_engine.available(), reason="the table comes from the bundled Praat")
def test_table_matches_praat(tmp_path):
    codes = list(TRIGRAPHS)
    grid = TextGrid(0.0, float(len(codes)))
    intervals = [Interval(float(i), i + 1.0, code) for i, code in enumerate(codes)]
    grid.tiers.append(IntervalTier("x", 0.0, float(len(codes)), intervals))
    source, result = tmp_path / "in.TextGrid", tmp_path / "out.TextGrid"
    grid.write(source)
    praat_engine.run_script(
        f'Read from file: "{source.as_posix()}"\nConvert to Unicode\nSave as text file: "{result.as_posix()}"\n'
    )
    assert [iv.text for iv in TextGrid.read(result).tiers[0].intervals] == [TRIGRAPHS[c] for c in codes]


def test_conversion_roundtrip():
    text = r"h\ae t \sw\ng\:f"
    assert to_unicode(text) == "hæ t əŋː"
    assert to_unicode(to_trigraphs(to_unicode(text))) == to_unicode(text)
    assert to_unicode("plain") == "plain"


def test_palette_symbols_are_single_codepoints():
    for _, symbols in GROUPS:
        for sym in symbols.split():
            assert len(sym) == 1, sym


def test_newer_praat_codes_are_included():
    assert to_unicode(r"\NE") == "\u2197"  # diagonal arrow, added in Praat 6.4.29
    assert to_unicode(r"\-5") == "\u02e5"  # tone letter, added in Praat 6.4.29
