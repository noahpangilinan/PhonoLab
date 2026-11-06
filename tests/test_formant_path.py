import numpy as np
import pytest

from phonolab.core import formant_path as fp
from phonolab.core import praat_engine
from phonolab.core.analysis import FormantSettings
from tests.conftest import make_vowel

needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")


def result(stresses):
    candidates = [
        fp.Candidate(4000.0 + 500 * i, s, np.array([0.1, 0.2]), np.array([[500.0, 510], [1500, 1510], [2500, 2510]]))
        for i, s in enumerate(stresses)
    ]
    return fp.FormantPathResult(0.0, 1.0, candidates)


def test_best_is_the_lowest_stress_and_edges_are_flagged():
    assert result([5.0, 3.0, 4.0]).best == 1 and not result([5.0, 3.0, 4.0]).best_is_at_edge
    assert result([2.0, 3.0, 4.0]).best_is_at_edge
    assert result([float("nan"), 3.0, 4.0]).best == 1
    assert result([float("nan")] * 3).best is None


@needs_praat
def test_compare_ceilings_on_a_vowel():
    r = fp.compare_ceilings(make_vowel(duration=1.0), 0.2, 0.8, FormantSettings(), fp.FormantPathSettings())
    assert len(r.candidates) == 9
    ceilings = [c.ceiling for c in r.candidates]
    assert ceilings == sorted(ceilings) and ceilings[4] == pytest.approx(5500, abs=1)
    assert r.best is not None
    middle = r.candidates[4]
    assert middle.frequencies.shape[0] == 3 and middle.times[0] >= 0
    assert np.nanmedian(middle.frequencies[0]) == pytest.approx(700, rel=0.15)


@needs_praat
def test_refuses_long_stretches():
    with pytest.raises(ValueError, match="seconds or less"):
        fp.compare_ceilings(make_vowel(duration=1.0), 0.0, 40.0, FormantSettings(), fp.FormantPathSettings())


def test_needs_praat(monkeypatch):
    monkeypatch.setenv("PHONOLAB_PRAAT", "none")
    with pytest.raises(ValueError, match="bundled Praat 7"):
        fp.compare_ceilings(make_vowel(duration=1.0), 0.1, 0.5, FormantSettings(), fp.FormantPathSettings())
