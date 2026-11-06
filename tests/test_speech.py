"""Speech synthesis and alignment through the bundled Praat."""

import contextlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt6.QtWidgets import QInputDialog, QMessageBox  # noqa: E402

from phonolab.core import praat_engine, sound_ops, speech  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid  # noqa: E402
from phonolab.ui.dialogs.speech_dialog import SpeechDialog  # noqa: E402
from tests.test_time_edit import check_valid  # noqa: E402
from tests.test_ui_smoke import wait_for_analyses, wav, window  # noqa: E402, F401

needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
SENTENCE = "the quick brown fox jumps over the lazy dog"


def tier(grid, name):
    return next(t for t in grid.tiers if t.name == name)


def labelled(t):
    return [iv for iv in t.intervals if iv.text.strip()]


# ---------------------------------------------------------------------- the list of languages


@needs_praat
def test_praat_accepts_every_language_and_voice_we_offer():
    script = "".join(f'x = Create SpeechSynthesizer: "{name}", "Male1"\nremoveObject: x\n' for name in speech.LANGUAGES)
    voices = "".join(
        f'x = Create SpeechSynthesizer: "English (America)", "{v}"\nremoveObject: x\n' for v in speech.VOICES
    )
    praat_engine.run_script(script + voices + 'writeInfoLine: "ok"\n', timeout=120)


def test_we_offer_all_133_languages_without_duplicates():
    assert len(speech.LANGUAGES) == len(set(speech.LANGUAGES)) == 133
    assert speech.DEFAULT_LANGUAGE in speech.LANGUAGES


# ---------------------------------------------------------------------- synthesis


@needs_praat
def test_synthesis_gives_audio_and_matching_annotations():
    sound, grid = speech.synthesize(SENTENCE)
    assert sound.path is None and sound.title == "the quick brown"
    assert sound.sampling_rate == 44100 and sound.peak > 0.05
    assert [t.name for t in grid.tiers] == ["sentence", "clause", "word", "phoneme"]
    assert grid.xmax == pytest.approx(sound.duration, abs=1e-3)
    assert [iv.text for iv in labelled(tier(grid, "word"))] == SENTENCE.split()
    check_valid(grid)


@needs_praat
def test_the_words_really_are_where_the_textgrid_says():
    sound, grid = speech.synthesize(SENTENCE)
    rms = lambda a, b: np.sqrt(np.mean(sound.extract(a, b).mono ** 2))  # noqa: E731
    for iv in labelled(tier(grid, "word")):
        assert rms(iv.xmin, iv.xmax) > 0.01


@needs_praat
def test_rate_changes_the_length():
    slow, _ = speech.synthesize(SENTENCE, words_per_minute=100)
    fast, _ = speech.synthesize(SENTENCE, words_per_minute=300)
    assert slow.duration > 1.5 * fast.duration


@needs_praat
def test_voice_changes_the_sound():
    a, _ = speech.synthesize("hello", voice="Male1")
    b, _ = speech.synthesize("hello", voice="Female3")
    assert a.n_samples != b.n_samples or not np.allclose(a.mono, b.mono)


@needs_praat
@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("French (France)", "ça coûte très cher"),
        ("German", "Grüße aus Köln"),
        ("Greek", "καλημέρα"),
        ("Russian", "привет мир"),
    ],
)
def test_non_ascii_text_survives_the_trip(language, text):
    sound, grid = speech.synthesize(text, language=language)
    assert sound.duration > 0.2
    assert " ".join(iv.text for iv in labelled(tier(grid, "sentence"))) == text


@needs_praat
@pytest.mark.parametrize(
    "text",
    [
        'she said "hello"',
        "it's 'folder$' and 'text$'",
        "'text$'",
        'quote" then\nwriteFile: "x.txt", "pwned',
        "back\\slash",
    ],
)
def test_text_can_never_become_script(text, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sound, grid = speech.synthesize(text)
    assert sound.duration > 0
    assert not list(tmp_path.iterdir())
    assert tier(grid, "sentence").intervals[0].text or labelled(tier(grid, "sentence"))


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_nothing_to_say_is_refused(text):
    if not praat_engine.available():
        pytest.skip("needs Praat")
    with pytest.raises(speech.SpeechError, match="Type something"):
        speech.synthesize(text)


def test_bad_language_or_voice_is_refused_before_reaching_praat(monkeypatch):
    monkeypatch.setattr(praat_engine, "available", lambda: True)
    with pytest.raises(speech.SpeechError, match="language"):
        speech.synthesize("hi", language='English"\nwriteFile: "x", "y')
    with pytest.raises(speech.SpeechError, match="voice"):
        speech.synthesize("hi", voice="Nobody")


def test_without_praat_the_message_says_so(monkeypatch):
    monkeypatch.setattr(praat_engine, "available", lambda: False)
    with pytest.raises(speech.SpeechError, match="bundled Praat"):
        speech.synthesize("hi")


# ---------------------------------------------------------------------- alignment


@pytest.fixture(scope="module")
def spoken():
    if not praat_engine.available():
        pytest.skip("run packaging/fetch_praat.py first")
    return speech.synthesize(SENTENCE, voice="Female2", language="English (America)")


@needs_praat
def test_alignment_finds_every_word_in_order(spoken):
    sound, _ = spoken
    result = speech.align(sound, 0.0, sound.duration, SENTENCE)
    assert [w[2] for w in result.words if w[2].strip()] == SENTENCE.split()
    assert any(p[2].strip() for p in result.phonemes)
    starts = [w[0] for w in result.words]
    assert starts == sorted(starts)


@needs_praat
@pytest.mark.parametrize("rate", [16000.0, 48000.0])
def test_alignment_doesnt_need_the_synthesizers_own_sampling_frequency(spoken, rate):
    """Praat refuses to compare sounds at different rates, and synthesized speech is always at 44.1 kHz."""
    sound, _ = spoken
    other = sound_ops.resample(sound, sound_ops.ResampleSettings(sampling_rate=rate))
    assert [w[2] for w in speech.align(other, 0.0, other.duration, SENTENCE).words if w[2].strip()] == SENTENCE.split()


@needs_praat
def test_alignment_lands_close_to_the_known_word_timings(spoken):
    """Aligned with a different voice and accent from the one that spoke, against the true timings."""
    sound, grid = spoken
    truth = {iv.text: iv.xmin for iv in labelled(tier(grid, "word"))}
    found = {
        w[2]: w[0]
        for w in speech.align(sound, 0.0, sound.duration, SENTENCE, "English (Great Britain)").words
        if w[2].strip()
    }
    errors = [abs(truth[w] - found[w]) for w in truth]
    assert np.mean(errors) < 0.08 and max(errors) < 0.25


@needs_praat
def test_alignment_of_a_stretch_uses_the_original_clock(spoken):
    sound, grid = spoken
    silence = np.zeros((int(sound.sampling_rate), 1))
    padded = Sound(np.concatenate([silence, sound.samples]), sound.sampling_rate)
    result = speech.align(padded, 1.0, padded.duration, SENTENCE)
    first = next(w for w in result.words if w[2].strip())
    assert 1.0 <= first[0] < 1.3
    assert result.words[-1][1] == pytest.approx(padded.duration, abs=0.01)


@needs_praat
def test_alignment_text_can_never_become_script(spoken, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sound, _ = spoken
    with contextlib.suppress(speech.SpeechError):  # failing to align is fine; running it isn't
        speech.align(sound, 0.0, sound.duration, 'x" \nwriteFile: "pwned.txt", "y')
    assert not list(tmp_path.iterdir())


@needs_praat
@pytest.mark.parametrize("text", ['she said "hello" twice', "it's 'folder$' and 'text$' here"])
def test_awkward_alignment_text_arrives_unchanged(text):
    """Quotes would break a script line, and Praat would expand 'folder$' there."""
    sound, _ = speech.synthesize(text)
    result = speech.align(sound, 0.0, sound.duration, text)
    found = " ".join(w[2] for w in result.words if w[2].strip())
    assert "hello" in found or "folder" in found
    assert "phonolab-" not in found and "Temp" not in found


@needs_praat
def test_silence_gives_a_clear_failure_or_nothing_harmful():
    sound = Sound(np.zeros(16000), 16000.0)
    try:
        result = speech.align(sound, 0.0, 1.0, "hello there")
    except speech.SpeechError as e:
        assert str(e)
    else:
        assert result.start == 0.0


@needs_praat
def test_align_many_carries_on_past_a_failure(spoken, monkeypatch):
    sound, _ = spoken
    real = speech.align

    def flaky(s, start, end, text, language):
        if text == "bad":
            raise speech.SpeechError("could not")
        return real(s, start, end, text, language)

    monkeypatch.setattr(speech, "align", flaky)
    done, problems = speech.align_many(sound, [(0.0, 1.0, "bad"), (0.0, sound.duration, SENTENCE)], "English (America)")
    assert len(done) == 1 and len(problems) == 1 and "could not" in problems[0]


# ---------------------------------------------------------------------- putting results on tiers


def plain_tier(*bounds_and_labels, xmax=10.0):
    out, start = [], 0.0
    for end, text in bounds_and_labels:
        out.append(Interval(start, end, text))
        start = end
    return IntervalTier("t", 0.0, xmax, out + ([Interval(start, xmax)] if start < xmax else []))


def spans(t):
    return [(i.xmin, i.xmax, i.text) for i in t.intervals]


def test_fill_range_into_an_empty_tier():
    t = IntervalTier("t", 0.0, 10.0)
    speech.fill_range(t, 2.0, 6.0, ((2.0, 4.0, "a"), (4.0, 6.0, "b")))
    assert spans(t) == [(0, 2, ""), (2, 4, "a"), (4, 6, "b"), (6, 10, "")]


def test_fill_range_replaces_only_that_stretch():
    t = plain_tier((2, "keep"), (6, "old"), (10, "keep too"))
    speech.fill_range(t, 2.0, 6.0, ((2.0, 6.0, "new"),))
    assert spans(t) == [(0, 2, "keep"), (2, 6, "new"), (6, 10, "keep too")]


def test_fill_range_to_the_tier_ends():
    t = IntervalTier("t", 0.0, 10.0)
    speech.fill_range(t, 0.0, 10.0, ((0.0, 5.0, "a"), (5.0, 10.0, "b")))
    assert spans(t) == [(0, 5, "a"), (5, 10, "b")]


def test_fill_range_clips_what_overruns_and_closes_gaps_at_the_ends():
    t = IntervalTier("t", 0.0, 10.0)
    speech.fill_range(t, 2.0, 6.0, ((2.5, 4.0, "a"), (4.0, 7.0, "b")))
    assert spans(t) == [(0, 2, ""), (2, 4, "a"), (4, 6, "b"), (6, 10, "")]


def test_fill_range_with_nothing_clears_the_stretch():
    t = plain_tier((2, "a"), (6, "b"))
    speech.fill_range(t, 2.0, 6.0, ())
    assert spans(t) == [(0, 2, "a"), (2, 6, ""), (6, 10, "")]


@pytest.mark.parametrize("seed", range(30))
def test_fill_range_always_leaves_a_valid_tier(seed):
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.1, 9.9, 8))
    t = plain_tier(*[(float(x), str(i)) for i, x in enumerate(times)])
    for _ in range(10):
        a, b = sorted(rng.uniform(0, 10, 2).tolist())
        cuts = np.sort(rng.uniform(a, b, 4)).tolist()
        pieces = tuple((x, y, "n") for x, y in zip([a, *cuts], [*cuts, b], strict=True))
        speech.fill_range(t, a, b, pieces)
        check_valid(TextGrid(0.0, 10.0, [t]))


def test_alignments_go_on_new_tiers_beside_the_source_and_reuse_them():
    grid = TextGrid(0.0, 10.0, [plain_tier((5, "hello there")), IntervalTier("other", 0.0, 10.0)])
    result = speech.Alignment(0.0, 5.0, ((0.0, 2.0, "hello"), (2.0, 5.0, "there")), ((0.0, 5.0, "h"),))
    speech.apply_alignments(grid, "t", [result])
    assert [t.name for t in grid.tiers] == ["t", "t_words", "t_phonemes", "other"]
    speech.apply_alignments(grid, "t", [result])
    assert len(grid.tiers) == 4 and len(grid.tiers[1].intervals) == 3


# ---------------------------------------------------------------------- in the app


@needs_praat
def test_synthesize_opens_an_unsaved_tab_with_its_textgrid(window, qtbot, monkeypatch):  # noqa: F811
    def accept(dialog):
        dialog.text.setPlainText("hello world")
        return True

    monkeypatch.setattr(SpeechDialog, "exec", accept)
    window.synthesize_speech()
    doc = window.editor.doc
    assert doc.sound.path is None and doc.textgrid is not None and doc.is_dirty
    assert [iv.text for iv in labelled(tier(doc.textgrid, "word"))] == ["hello", "world"]


@needs_praat
def test_synthesis_failure_warns_and_opens_nothing(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(SpeechDialog, "exec", lambda d: True)  # no text typed
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    window.synthesize_speech()
    assert warned and window.tabs.count() == 0


def test_the_menu_explains_without_praat(window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(praat_engine, "available", lambda: False)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    window.synthesize_speech()
    assert "bundled Praat" in warned[0]


@pytest.fixture
def spoken_tab(window, qtbot, tmp_path, spoken):  # noqa: F811
    sound, _ = spoken
    path = tmp_path / "speech.wav"
    sound.save(path)
    window.open_sound(str(path))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    grid = TextGrid.for_duration(editor.doc.sound.duration, interval_tiers=("sentence",))
    grid.tiers[0].set_text(0, SENTENCE)
    editor.doc.set_textgrid(grid)
    editor.textgrid_view.selected_tier, editor.textgrid_view.selected_item = 0, 0
    return editor


@needs_praat
def test_align_adds_tiers_as_one_undo_step(window, spoken_tab, qtbot, monkeypatch):  # noqa: F811
    editor = spoken_tab
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("English (America)", True))
    window.align(False)
    qtbot.waitUntil(lambda: len(editor.doc.textgrid.tiers) == 3, timeout=20000)
    words = tier(editor.doc.textgrid, "sentence_words")
    assert [iv.text for iv in labelled(words)] == SENTENCE.split()
    check_valid(editor.doc.textgrid)
    editor.doc.undo_stack.undo()
    assert len(editor.doc.textgrid.tiers) == 1


@needs_praat
def test_align_all_covers_each_labelled_interval(window, spoken_tab, qtbot, monkeypatch):  # noqa: F811
    editor = spoken_tab
    grid = editor.doc.textgrid
    d = grid.xmax
    cut = next(
        iv.xmin for iv in labelled(tier(speech.synthesize(SENTENCE, voice="Female2")[1], "word")) if iv.text == "jumps"
    )
    grid.tiers[0].add_boundary(cut)
    grid.tiers[0].set_text(0, "the quick brown fox")
    grid.tiers[0].set_text(1, "jumps over the lazy dog")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("English (America)", True))
    window.align(True)
    qtbot.waitUntil(lambda: len(editor.doc.textgrid.tiers) == 3, timeout=30000)
    words = tier(editor.doc.textgrid, "sentence_words")
    assert [iv.text for iv in labelled(words)] == SENTENCE.split() and words.xmax == d


@needs_praat
@pytest.mark.parametrize(
    ("setup", "expected"), [("point", "interval tier"), ("none", "Select an interval"), ("empty", "Type the text")]
)
def test_align_explains_what_it_needs(spoken_tab, setup, expected):
    editor = spoken_tab
    view = editor.textgrid_view
    messages = []
    editor.message.connect(messages.append)
    if setup == "point":
        view.add_tier("point", "p")
    elif setup == "none":
        view.selected_item = None
    else:
        editor.doc.textgrid.tiers[0].set_text(0, "")
    editor.align("English (America)")
    assert any(expected in m for m in messages) and len(editor.doc.textgrid.tiers) <= 2


@needs_praat
def test_an_audio_edit_during_alignment_drops_the_result(window, spoken_tab, qtbot, monkeypatch):  # noqa: F811
    editor = spoken_tab
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("English (America)", True))
    window.align(False)
    editor.axis.set_selection(0.1, 0.2)
    window.cut_sound()
    qtbot.wait(2500)
    assert [t.name for t in editor.doc.textgrid.tiers] == ["sentence"]


@needs_praat
def test_removing_the_tier_during_alignment_is_harmless(window, spoken_tab, qtbot, monkeypatch):  # noqa: F811
    editor = spoken_tab
    messages = []
    editor.message.connect(messages.append)
    editor.doc.edit("Add", lambda g: g.tiers.append(IntervalTier("x", g.xmin, g.xmax)))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("English (America)", True))
    window.align(False)
    editor.doc.edit("Remove", lambda g: g.tiers.pop(0))
    qtbot.waitUntil(lambda: any("has gone" in m for m in messages), timeout=20000)
    assert [t.name for t in editor.doc.textgrid.tiers] == ["x"]


@needs_praat
def test_backslash_codes_are_aligned_as_the_symbols_they_stand_for(window, spoken_tab, qtbot, monkeypatch):  # noqa: F811
    editor = spoken_tab
    submitted = []
    monkeypatch.setattr(editor.manager, "submit", lambda *a: submitted.append(a))
    editor.doc.textgrid.tiers[0].set_text(0, r"caf\e'")
    editor.align("French (France)")
    assert submitted[0][2][0][2] == "café"
