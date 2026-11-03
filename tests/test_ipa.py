from parselmouth.praat import call

from phonolab.core.ipa import TRIGRAPHS, to_trigraphs, to_unicode
from phonolab.ui.ipa_palette import GROUPS


def test_table_matches_praat():
    codes = list(TRIGRAPHS)
    tg = call("Create TextGrid", 0, len(codes), "x", "")
    for i in range(1, len(codes)):
        call(tg, "Insert boundary", 1, i)
    for i, code in enumerate(codes, 1):
        call(tg, "Set interval text", 1, i, code)
    call(tg, "Convert to Unicode")
    praat = [call(tg, "Get label of interval", 1, i) for i in range(1, len(codes) + 1)]
    assert praat == [TRIGRAPHS[c] for c in codes]


def test_conversion_roundtrip():
    text = r"h\ae t \sw\ng\:f"
    assert to_unicode(text) == "hæ t əŋː"
    assert to_unicode(to_trigraphs(to_unicode(text))) == to_unicode(text)
    assert to_unicode("plain") == "plain"


def test_palette_symbols_are_single_codepoints():
    for _, symbols in GROUPS:
        for sym in symbols.split():
            assert len(sym) == 1, sym
