import pickle

import numpy as np
import pytest

from phonolab.core import scripting
from phonolab.core.textgrid import TextGrid
from tests.conftest import make_vowel


@pytest.fixture
def vowel():
    return make_vowel(duration=0.5)


def test_parse_arguments():
    assert scripting.parse_arguments('1000 "two words" x') == [1000.0, "two words", "x"]


def test_praat_script_output_and_new_sound(vowel):
    script = 'dur = Get total duration\nwriteInfoLine: "dur ", fixed$(dur, 2)\nCopy: "quiet"\nMultiply: 0.5\n'
    r = scripting.run_praat(vowel, None, script)
    assert r.error is None and r.output.strip() == "dur 0.50"
    ((name, samples, sr),) = r.sounds
    assert name == "quiet" and sr == vowel.sampling_rate
    assert np.allclose(samples[:, 0], vowel.mono * 0.5)


def test_praat_script_with_form_and_textgrid(vowel):
    tg = TextGrid.for_duration(vowel.duration, ["words"])
    script = (
        "form F\n    sentence Label hello\nendform\n"
        'selectObject: "TextGrid ' + vowel.name + '"\nInsert boundary: 1, 0.2\nSet interval text: 1, 1, label$\n'
    )
    r = scripting.run_praat(vowel, tg, script, '"hi there"')
    assert r.error is None
    assert r.textgrid.tiers[0].intervals[0].text == "hi there"
    assert r.sounds == []  # the unchanged input sound is not returned


def test_praat_script_error_is_reported(vowel):
    r = scripting.run_praat(vowel, None, "No such command: 1\n")
    assert r.error and "No such command" in r.error


def test_python_script(vowel):
    code = (
        "print(round(sound.duration, 2))\nnew_sounds = [Sound(sound.samples[:100], sound.sampling_rate, title='head')]"
    )
    r = scripting.run_python(vowel, None, code)
    assert r.output.strip() == "0.5" and r.sounds[0][0] == "head"
    bad = scripting.run_python(vowel, None, "1/0")
    assert "ZeroDivisionError" in bad.error


def test_sound_pickles_without_caches(vowel):
    vowel.praat  # noqa: B018 - build the cache
    copy = pickle.loads(pickle.dumps(vowel))
    assert copy._praat is None and np.array_equal(copy.samples, vowel.samples)
