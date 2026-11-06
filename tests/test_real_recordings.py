"""PhonoLab on real speech, from tests/fetch_recordings.py. These tests skip until that has been run.

Synthetic sounds can't find everything: alignment once failed on any recording not at 44.1 kHz, which no test
noticed because all the speech they used came from the synthesizer, at 44.1 kHz.

Reference points, strongest first:
- TIMIT's word and phone labels were checked by hand.
- The EGG channel of ARCTIC's recordings measures the vocal folds directly, so it's independent of the speech.
- Praat 7, run on the same audio.
- ARCTIC's labels are automatic, so they only show that results are in the right place.
"""

import csv
import json
import os
import re
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from phonolab.core import batch, corpus, manipulation, praat_engine, registry, sound_ops, speech, voice  # noqa: E402
from phonolab.core.corrections import Corrections  # noqa: E402
from phonolab.core.manipulation import ManipulationSettings, Tier  # noqa: E402
from phonolab.core.sound import Sound  # noqa: E402
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid  # noqa: E402
from phonolab.ui.document import Document  # noqa: E402
from tests.test_time_edit import check_valid  # noqa: E402
from tests.test_ui_smoke import wait_for_analyses, window  # noqa: E402, F401

R = Path(__file__).parent / "recordings"
MANIFEST = json.loads((Path(__file__).parent / "recordings.json").read_text(encoding="utf-8"))
pytestmark = pytest.mark.skipif(
    not all((R / name).exists() for name in MANIFEST["files"]), reason="run tests/fetch_recordings.py first"
)
needs_praat = pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
SPEAKERS = ("slt", "bdl", "ksp", "awb")
ARCTIC = [p for s in SPEAKERS for p in sorted((R / "arctic" / s).glob("*.wav"))]
EGG = sorted((R / "arctic" / "egg").glob("*.wav"))
AUDIO = [R / "timit/ldc93s1.wav", *ARCTIC, *EGG, R / "commons/De-essen.ogg", R / "commons/Navajo_numbers_1_to_10.mp3"]


def settings() -> dict:
    return {name: registry.ANALYSES[name][0]() for name in registry.ANALYSES}


def timit() -> Sound:
    return Sound.from_file(R / "timit/ldc93s1.wav")


def timit_labels(suffix: str) -> list[tuple[float, float, str]]:
    rate = timit().sampling_rate
    rows = [line.split() for line in (R / f"timit/ldc93s1.{suffix}").read_text().splitlines() if line.strip()]
    return [(int(a) / rate, int(b) / rate, label) for a, b, label in rows]


def arctic_text(path: Path) -> str:
    prompts = (path.parent / "prompts.txt").read_text()
    return dict(re.findall(r'\( (arctic_a\d+) "(.*)" \)', prompts))[path.stem]


def arctic_phones(path: Path) -> list[tuple[float, float, str]]:
    out, start = [], 0.0
    for line in path.with_suffix(".lab").read_text().split("#", 1)[1].strip().splitlines():
        end, _, label = line.split()[:3]
        out.append((start, float(end), label))
        start = float(end)
    return out


def speech_span(phones) -> tuple[float, float]:
    spoken = [p for p in phones if p[2] not in ("pau", "ssil", "sil")]
    return spoken[0][0], spoken[-1][1]


def words_of(alignment) -> list[tuple[float, float, str]]:
    return [w for w in alignment.words if w[2].strip()]


def phone_grid(sound: Sound) -> TextGrid:
    """TIMIT's hand labels as a TextGrid, gaps included."""
    intervals = [Interval(a, b, label) for a, b, label in timit_labels("phn")]
    intervals[-1].xmax = sound.duration
    return TextGrid(0.0, sound.duration, [IntervalTier("phones", 0.0, sound.duration, intervals)])


# ---------------------------------------------------------------------- loading


@pytest.mark.parametrize("path", AUDIO, ids=lambda p: f"{p.parent.name}-{p.name}")
def test_every_recording_loads_and_analyses(path):
    sound = Sound.from_file(path)
    assert sound.duration > 0.3 and 0 < sound.peak <= 1.01 and np.isfinite(sound.samples).all()
    s = settings()
    pitch = registry.compute("pitch", sound, s)
    formants = registry.compute("formants", sound, s)
    intensity = registry.compute("intensity", sound, s)
    assert len(pitch.times) and len(formants.times) and np.isfinite(intensity.db).any()


def test_each_format_was_really_exercised():
    heads = {p.suffix: p.read_bytes()[:4] for p in AUDIO}
    assert heads[".ogg"] == b"OggS" and heads[".wav"] == b"RIFF" and heads[".mp3"][:1] in (b"\xff", b"I")
    assert Sound.from_file(EGG[0]).n_channels == 2 and Sound.from_file(EGG[0]).sampling_rate == 32000


@pytest.mark.parametrize("suffix", [".wav", ".flac", ".aiff", ".ogg"])
def test_real_speech_survives_saving(tmp_path, suffix):
    sound = timit()
    path = tmp_path / f"a{suffix}"
    sound.save(path)
    back = Sound.from_file(path)
    assert back.sampling_rate == sound.sampling_rate
    assert back.n_samples == pytest.approx(sound.n_samples, abs=2000)
    n = min(back.n_samples, sound.n_samples)
    tolerance = 0.03 if suffix == ".ogg" else 1e-4
    assert np.abs(back.mono[:n] - sound.mono[:n]).max() < tolerance


# ---------------------------------------------------------------------- pitch against the vocal folds


def agreement(ours, reference):
    n = min(len(ours.frequencies), len(reference.frequencies))
    a, b = ours.frequencies[:n], reference.frequencies[:n]
    both = ~np.isnan(a) & ~np.isnan(b)
    return np.abs(a[both] - b[both]) / b[both], both.sum()


@pytest.mark.parametrize("path", EGG, ids=lambda p: p.stem)
def test_pitch_from_speech_matches_the_vocal_folds(path):
    """The EGG measures vibration directly, so this checks pitch against something other than software."""
    sound = Sound.from_file(path)
    s = settings()
    from_speech = registry.compute("pitch", Sound(sound.samples[:, 0:1], sound.sampling_rate), s)
    from_egg = registry.compute("pitch", Sound(sound.samples[:, 1:2], sound.sampling_rate), s)
    errors, frames = agreement(from_speech, from_egg)
    assert frames > 100
    assert np.median(errors) < 0.01 and np.mean(errors < 0.05) > 0.95


@pytest.mark.parametrize("path", EGG, ids=lambda p: p.stem)
def test_the_two_channels_really_differ(path):
    sound = Sound.from_file(path)
    assert abs(np.corrcoef(sound.samples[:, 0], sound.samples[:, 1])[0, 1]) < 0.9


@pytest.mark.parametrize(
    ("speaker", "low", "high"), [("slt", 140, 260), ("bdl", 90, 200), ("ksp", 70, 160), ("awb", 90, 200)]
)
def test_each_speaker_is_in_a_plausible_range(speaker, low, high):
    sound = Sound.from_file(R / f"arctic/{speaker}/arctic_a0001.wav")
    assert low < np.nanmedian(registry.compute("pitch", sound, settings()).frequencies) < high


# ---------------------------------------------------------------------- against Praat 7 and the fallback


@needs_praat
@pytest.mark.parametrize("path", [R / "timit/ldc93s1.wav", *ARCTIC[:6]], ids=lambda p: f"{p.parent.name}-{p.stem}")
def test_the_fallback_agrees_with_praat_7_on_real_speech(path, monkeypatch):
    sound = Sound.from_file(path)
    s = settings()
    used = []
    real = praat_engine.run_script
    monkeypatch.setattr(praat_engine, "run_script", lambda *a, **k: used.append(a) or real(*a, **k))
    seven = registry.compute("pitch", sound, s)
    formants = registry.compute("formants", sound, s)
    assert len(used) == 2  # otherwise this would compare the fallback with itself
    monkeypatch.setattr(praat_engine, "available", lambda: False)
    monkeypatch.setattr(praat_engine, "run_script", lambda *a, **k: pytest.fail("this should be the fallback"))
    fresh = Sound.from_file(path)
    old = registry.compute("pitch", fresh, s)
    old_formants = registry.compute("formants", fresh, s)
    errors, frames = agreement(old, seven)
    assert frames > 30 and np.median(errors) < 0.001
    n = min(len(formants.times), len(old_formants.times))
    f1 = np.abs(formants.frequencies[0, :n] - old_formants.frequencies[0, :n])  # (formants, frames)
    assert np.nanmedian(f1) < 1.0


@needs_praat
def test_formants_of_a_real_vowel_are_vowel_like():
    word_start, word_end, _ = timit_labels("wrd")[3]  # "dark"
    vowels = ("aa", "ao", "ah", "ax", "ae", "eh", "ih", "iy", "uh", "uw", "er", "axr")
    start, end, label = next(p for p in timit_labels("phn") if word_start <= p[0] < word_end and p[2] in vowels)
    sound = timit()
    formants = registry.compute("formants", sound, settings())
    inside = (formants.times > start) & (formants.times < end)
    f1, f2 = np.nanmedian(formants.frequencies[:2, inside], axis=1)
    assert label == "aa" or label == "ao" or label == "ah", label
    assert 450 < f1 < 1100 and 800 < f2 < 1800  # an open back vowel


@needs_praat
@pytest.mark.parametrize("path", EGG[:1] + ARCTIC[:1], ids=lambda p: p.stem)
def test_the_voice_report_works_on_real_speech(path):
    s = settings()
    sound = Sound.from_file(path)
    report = voice.voice_report(sound, s["pitch"], s["pulses"], 0.0, sound.duration)
    text = str(report)
    assert "itter" in text and "immer" in text


# ---------------------------------------------------------------------- alignment


@needs_praat
def test_alignment_against_hand_labelled_words():
    truth = timit_labels("wrd")
    sound = timit()
    found = words_of(speech.align(sound, 0.0, sound.duration, " ".join(w[2] for w in truth)))
    assert [w[2] for w in found] == [w[2] for w in truth]
    errors = np.array([abs(f[0] - t[0]) for f, t in zip(found, truth, strict=True)])
    assert errors.mean() < 0.04 and errors.max() < 0.1  # measured: 24 ms and 50 ms


@needs_praat
@pytest.mark.parametrize("speaker", SPEAKERS)
def test_alignment_of_each_speaker_including_accents(speaker):
    errors = []
    for path in sorted((R / "arctic" / speaker).glob("*.wav")):
        sound = Sound.from_file(path)
        found = words_of(speech.align(sound, 0.0, sound.duration, arctic_text(path)))
        assert len(found) >= 5
        start, end = speech_span(arctic_phones(path))
        errors += [abs(found[0][0] - start), abs(found[-1][1] - end)]
    assert np.mean(errors) < 0.08 and np.max(errors) < 0.2  # measured: 27 to 42 ms, worst 111 ms


@needs_praat
@pytest.mark.parametrize("rate", [8000, 11025, 16000, 22050, 32000, 44100, 48000, 96000])
def test_alignment_works_at_any_sampling_frequency(rate):
    resampled = sound_ops.resample(timit(), sound_ops.ResampleSettings(sampling_rate=float(rate)))
    text = " ".join(w[2] for w in timit_labels("wrd"))
    assert len(words_of(speech.align(resampled, 0.0, resampled.duration, text))) == 11


@needs_praat
def test_alignment_of_a_stereo_recording():
    sound = Sound.from_file(EGG[0])
    path = R / "arctic/slt/arctic_a0001.wav"
    assert len(words_of(speech.align(sound, 0.0, sound.duration, arctic_text(path)))) >= 5


@needs_praat
def test_alignment_of_one_stretch_finds_its_words():
    truth = timit_labels("wrd")
    sound = timit()
    start, end = truth[3][0], truth[6][1]  # dark suit in greasy
    found = words_of(speech.align(sound, start, end, "dark suit in greasy"))
    assert [w[2] for w in found] == ["dark", "suit", "in", "greasy"]
    assert abs(found[1][0] - truth[4][0]) < 0.08 and found[-1][1] <= end + 1e-6


@needs_praat
def test_alignment_gets_phonemes_of_real_speech():
    sound = timit()
    result = speech.align(sound, 0.0, sound.duration, "she had your dark suit in greasy wash water all year")
    assert len([p for p in result.phonemes if p[2].strip()]) >= 25


@needs_praat
def test_aligning_in_the_app_at_a_real_rate(window, qtbot, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QInputDialog

    window.open_sound(str(R / "timit/ldc93s1.wav"))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    grid = TextGrid.for_duration(editor.doc.sound.duration, interval_tiers=("sentence",))
    grid.tiers[0].set_text(0, "she had your dark suit in greasy wash water all year")
    editor.doc.set_textgrid(grid)
    editor.textgrid_view.selected_tier, editor.textgrid_view.selected_item = 0, 0
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a: ("English (America)", True))
    messages = []
    editor.message.connect(messages.append)
    window.align(False)
    qtbot.waitUntil(lambda: any("ligned 1" in m or "could not" in m for m in messages), timeout=20000)
    assert not any("could not" in m for m in messages), messages
    assert len(editor.doc.textgrid.tiers) == 3
    check_valid(editor.doc.textgrid)


# ---------------------------------------------------------------------- corpus files


@needs_praat
def test_real_timit_files(tmp_path):
    for suffix in ("wav", "phn", "wrd", "txt"):
        shutil.copy(R / f"timit/ldc93s1.{suffix}", tmp_path / f"sa1.{suffix}")
    grid = corpus.read_adjacent(tmp_path / "sa1.wav", "TIMIT")
    check_valid(grid)
    assert [t.name for t in grid.tiers] == ["phon-ipa", "phon-arpa", "words", "text"]
    arpa = next(t for t in grid.tiers if t.name == "phon-arpa")
    truth = timit_labels("phn")
    labelled = [iv for iv in arpa.intervals if iv.text]  # Praat fills up to the end of the sound
    assert [iv.text for iv in labelled] == [p[2] for p in truth]
    assert [iv.xmin for iv in labelled[1:]] == pytest.approx([p[0] for p in truth[1:]])


@needs_praat
def test_timits_overlapping_words_dont_break_the_tier(tmp_path):
    """Hand labels overlap: "had" ends after "your" begins."""
    words = timit_labels("wrd")
    assert words[1][1] > words[2][0]
    for suffix in ("wav", "phn", "wrd", "txt"):
        shutil.copy(R / f"timit/ldc93s1.{suffix}", tmp_path / f"sa1.{suffix}")
    grid = corpus.read_adjacent(tmp_path / "sa1.wav", "TIMIT")
    tier = next(t for t in grid.tiers if t.name == "words")
    labels = " ".join(iv.text for iv in tier.intervals)
    assert all(w[2] in labels for w in words)


@needs_praat
@pytest.mark.parametrize("path", ARCTIC[:3], ids=lambda p: p.stem)
def test_real_esps_label_files(path):
    grid = corpus.read_esps(path.with_suffix(".lab"))
    check_valid(grid)
    phones = arctic_phones(path)
    assert [iv.text for iv in grid.tiers[0].intervals] == [p[2] for p in phones]
    assert [iv.xmax for iv in grid.tiers[0].intervals] == pytest.approx([p[1] for p in phones])


# ---------------------------------------------------------------------- editing real speech


@needs_praat
def test_cutting_a_word_matches_praat_and_leaves_the_rest_alone(tmp_path):
    sound = timit()
    start, end, _ = timit_labels("wrd")[3]  # dark
    a, b = sound.time_to_index(start), sound.time_to_index(end)
    doc = Document(sound)
    doc.set_textgrid(phone_grid(sound))
    doc.splice_audio("Cut", a, b)
    check_valid(doc.textgrid)
    ours = tmp_path / "ours.wav"
    theirs = tmp_path / "theirs.wav"
    Sound(timit().samples, sound.sampling_rate).save(ours)
    rate = sound.sampling_rate
    praat_engine.run_script(
        f'x = Read from file: "{ours.as_posix()}"\n'
        f'p = Extract part: 0, {a / rate!r}, "rectangular", 1, "no"\nselectObject: x\n'
        f'q = Extract part: {b / rate!r}, {sound.duration!r}, "rectangular", 1, "no"\n'
        f'selectObject: p, q\nConcatenate\nSave as WAV file: "{theirs.as_posix()}"\n'
    )
    reference = Sound.from_file(theirs)
    assert reference.n_samples == doc.sound.n_samples
    assert np.abs(reference.mono - doc.sound.mono).max() <= 1.5 / 32768


def test_every_label_stays_on_its_sound_after_a_cut():
    """The audio of each phone after a cut must be exactly the audio it labelled before."""
    sound = timit()
    labels = timit_labels("phn")
    before = {i: sound.extract(a, b).mono.copy() for i, (a, b, _) in enumerate(labels)}
    start, end, _ = timit_labels("wrd")[3]
    doc = Document(sound)
    doc.set_textgrid(phone_grid(sound))
    doc.splice_audio("Cut", sound.time_to_index(start), sound.time_to_index(end))
    after = [iv for iv in doc.textgrid.tiers[0].intervals if iv.xmin >= start]
    tail = [i for i, p in enumerate(labels) if p[0] >= end]
    checked = 0
    for iv, i in zip(after[-len(tail) + 1 : -1], tail[1:-1], strict=True):
        assert iv.text == labels[i][2]
        assert np.array_equal(doc.sound.extract(iv.xmin, iv.xmax).mono, before[i])
        checked += 1
    assert checked > 10


def test_pasting_a_word_gives_that_word_twice():
    sound = timit()
    start, end, _ = timit_labels("wrd")[4]  # suit
    a, b = sound.time_to_index(start), sound.time_to_index(end)
    word = sound.samples[a:b].copy()
    doc = Document(sound)
    doc.splice_audio("Paste", b, b, word)
    assert np.array_equal(doc.sound.samples[b : b + (b - a)], word)
    assert doc.sound.n_samples == sound.n_samples + (b - a)


@pytest.mark.parametrize("seed", range(10))
def test_random_edits_of_real_speech_undo_exactly(qapp, seed):
    rng = np.random.default_rng(seed)
    sound = timit()
    doc = Document(sound)
    doc.set_textgrid(phone_grid(sound))
    original, grid = sound.samples.copy(), doc.textgrid.copy()
    edits = 0
    for _ in range(15):
        n = doc.sound.n_samples
        a = int(rng.integers(0, n - 1))
        b = min(n, a + int(rng.integers(1, 4000)))
        clip = doc.sound.samples[a:b].copy() if rng.random() < 0.5 else None
        if b - a < n:
            doc.splice_audio("Edit", b if clip is not None else a, b, clip)
            edits += 1
            check_valid(doc.textgrid)
    for _ in range(edits):
        doc.undo_stack.undo()
    assert np.array_equal(doc.sound.samples, original) and doc.textgrid == grid


def test_corrections_on_real_speech(qapp):
    sound = timit()
    doc = Document(sound)
    start, end, _ = timit_labels("wrd")[6]  # greasy
    doc.correct("Unvoice", Corrections(unvoiced=((start, end),)))
    cut_start, cut_end, _ = timit_labels("wrd")[3]
    doc.splice_audio("Cut", sound.time_to_index(cut_start), sound.time_to_index(cut_end))
    ((a, b),) = doc.corrections.unvoiced
    assert (b - a) == pytest.approx(end - start) and a == pytest.approx(start - (cut_end - cut_start), abs=1e-3)
    pitch = doc.corrections.apply_pitch(registry.compute("pitch", doc.sound, settings()))
    inside = (pitch.times > a) & (pitch.times < b)
    assert inside.any() and np.isnan(pitch.frequencies[inside]).all()


# ---------------------------------------------------------------------- manipulation, measured afterwards


def median_f0(samples, rate):
    return np.nanmedian(registry.compute("pitch", Sound(samples, rate), settings()).frequencies)


@pytest.fixture(scope="module")
def vocal():
    return Sound.from_file(R / "arctic/slt/arctic_a0001.wav")


@pytest.mark.parametrize("semitones", [-5.0, 3.0, 7.0])
def test_shifting_real_speech_changes_its_measured_pitch(vocal, semitones):
    s = ManipulationSettings()
    tier = manipulation.analyse(vocal, s)
    shifted = manipulation.shift_semitones(tier, semitones, 0.0, vocal.duration)
    out, rate = manipulation.resynthesize(vocal, s, shifted, Tier.empty())
    ratio = median_f0(out, rate) / np.nanmedian(registry.compute("pitch", vocal, settings()).frequencies)
    assert ratio == pytest.approx(2 ** (semitones / 12), rel=0.04)


def test_stretching_real_speech_keeps_its_pitch(vocal):
    s = ManipulationSettings()
    tier = manipulation.analyse(vocal, s)
    longer = manipulation.set_duration_factor(Tier.empty(), 0.0, vocal.duration, 1.5)
    out, rate = manipulation.resynthesize(vocal, s, tier, longer)
    assert len(out) / rate == pytest.approx(1.5 * vocal.duration, rel=0.02)
    original = np.nanmedian(registry.compute("pitch", vocal, settings()).frequencies)
    assert median_f0(out, rate) == pytest.approx(original, rel=0.04)


def test_loudness_of_real_speech(vocal):
    s = ManipulationSettings()
    tier = manipulation.analyse(vocal, s)
    gain = manipulation.set_gain(Tier.empty(), 1.0, 2.0, -12.0)
    quiet, rate = manipulation.resynthesize(vocal, s, tier, Tier.empty(), gain)
    plain, _ = manipulation.resynthesize(vocal, s, tier, Tier.empty())
    middle = slice(int(1.2 * rate), int(1.8 * rate))
    change = 20 * np.log10(np.sqrt(np.mean(quiet[middle] ** 2)) / np.sqrt(np.mean(plain[middle] ** 2)))
    assert change == pytest.approx(-12, abs=0.1)


# ---------------------------------------------------------------------- the app with real two-channel audio


def test_analysing_each_channel_of_a_real_recording(window, qtbot):  # noqa: F811
    window.open_sound(str(EGG[0]))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    results = {}
    for channel in (None, 0, 1):
        editor.set_analysis_channel(channel)
        wait_for_analyses(qtbot, editor)
        results[channel] = editor.manager.raw_results["pitch"]
        fresh = registry.compute("pitch", editor.doc.analysis_sound, editor.manager.settings)
        assert np.allclose(results[channel].frequencies, fresh.frequencies, equal_nan=True)
    speech_only, egg = results[0].frequencies, results[1].frequencies
    assert not np.array_equal(np.isnan(speech_only), np.isnan(egg))


def test_cutting_a_real_stereo_recording_in_the_app(window, qtbot):  # noqa: F811
    window.open_sound(str(EGG[0]))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    original = editor.doc.sound.samples.copy()
    editor.axis.set_selection(1.0, 1.5)
    window.cut_sound()
    wait_for_analyses(qtbot, editor)
    a, b = int(round(1.0 * 32000)), int(round(1.5 * 32000))
    assert np.array_equal(editor.doc.sound.samples, np.concatenate([original[:a], original[b:]]))
    editor.doc.undo_stack.undo()
    assert np.array_equal(editor.doc.sound.samples, original)


@pytest.mark.parametrize("name", ["commons/De-essen.ogg", "commons/Navajo_numbers_1_to_10.mp3"])
def test_compressed_files_can_be_edited_and_saved(window, qtbot, tmp_path, monkeypatch, name):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog

    window.open_sound(str(R / name))
    editor = window.editor
    wait_for_analyses(qtbot, editor)
    d = editor.doc.sound.duration
    editor.axis.set_selection(d * 0.25, d * 0.5)
    window.cut_sound()
    target = tmp_path / "edited.wav"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.save_sound_as()
    assert Sound.from_file(target).duration == pytest.approx(d * 0.75, abs=0.01) and not editor.doc.is_dirty


# ---------------------------------------------------------------------- batch and long recordings


def test_batch_over_real_recordings(tmp_path):
    for path in ARCTIC[:4]:
        shutil.copy(path, tmp_path / f"{path.parent.name}_{path.name}")
    rows = [row for path in batch.find_sounds(tmp_path) for row in batch.measure_file(path, batch.BatchOptions())]
    assert len(rows) == 4 and not any(row.get("error") for row in rows)
    out = tmp_path / "out.csv"
    assert batch.write_csv(rows, out) == 4
    with out.open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 4


def test_a_real_recording_treated_as_long_gives_the_same_pitch(tmp_path, monkeypatch):
    from phonolab.core import sound as sound_module

    path = R / "arctic/slt/arctic_a0001.wav"
    whole = registry.compute("pitch", Sound.from_file(path), settings())
    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 1000)
    long_sound = Sound.from_file(path)
    assert long_sound.is_long
    part = registry.compute("pitch", long_sound.extract(0.0, long_sound.duration), settings())
    errors, frames = agreement(part, whole)
    assert frames > 100 and np.median(errors) < 0.001
    long_sound.release()


def test_sound_operations_on_real_speech():
    sound = timit()
    assert sound_ops.reverse(sound).mono[0] == sound.mono[-1]
    assert sound_ops.scale_peak(sound, sound_ops.ScalePeakSettings(peak=0.5)).peak == pytest.approx(0.5, abs=1e-3)
    assert sound_ops.to_mono(Sound.from_file(EGG[0])).n_channels == 1
    assert sound_ops.resample(sound, sound_ops.ResampleSettings(sampling_rate=8000.0)).sampling_rate == 8000
