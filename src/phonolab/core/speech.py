"""Speech synthesis and alignment through eSpeak, as built into the bundled Praat.

Text never goes on a script line: Praat expands 'name' patterns there, and these scripts run with
full trust, so a label from someone else's TextGrid must not be able to become part of a script.
Text is written to a file and read with readFile$.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from phonolab.core import praat_engine
from phonolab.core.sound import Sound
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid, TextGridError

DEFAULT_LANGUAGE = "English (America)"
VOICES = (
    "Female1", "Female2", "Female3", "Female4", "Female5",
    "Male1", "Male2", "Male3", "Male4", "Male5", "Male6", "Male7", "Male8",
    "Croak", "Whisper", "Klatt",
)  # fmt: skip
# What Praat 7.0.02 accepts. tests/test_speech.py checks this against the bundled program.
LANGUAGES = (
    "Afrikaans",
    "Albanian",
    "Amharic",
    "Arabic",
    "Aragonese",
    "Armenian (East Armenia)",
    "Armenian (West Armenia)",
    "Assamese",
    "Azerbaijani",
    "Bashkir",
    "Basque",
    "Belarusian",
    "Bengali",
    "Bishnupriya Manipuri",
    "Bosnian",
    "Bulgarian",
    "Catalan",
    "Chinese (Cantonese)",
    "Chinese (Cantonese, latin as Jyutping)",
    "Chinese (Mandarin, latin as English)",
    "Chinese (Mandarin, latin as Pinyin)",
    "Chuvash",
    "Croatian",
    "Czech",
    "Danish",
    "Dutch",
    "English (America)",
    "English (America, New York City)",
    "English (Caribbean)",
    "English (Great Britain)",
    "English (Lancaster)",
    "English (Received Pronunciation)",
    "English (Scotland)",
    "English (West Midlands)",
    "Esperanto",
    "Estonian",
    "Faroese",
    "Finnish",
    "French (Belgium)",
    "French (France)",
    "French (Switzerland)",
    "Gaelic (Irish)",
    "Gaelic (Scottish)",
    "Georgian",
    "German",
    "Greek",
    "Greek (Ancient)",
    "Greenlandic",
    "Guarani",
    "Gujarati",
    "Haitian Creole",
    "Hakka Chinese",
    "Hawaiian",
    "Hebrew",
    "Hindi",
    "Hungarian",
    "Icelandic",
    "Ido",
    "Indonesian",
    "Interlingua",
    "Italian",
    "Japanese",
    "K'iche'",
    "Kannada",
    "Karakalpak",
    "Kazakh",
    "Klingon",
    "Konkani",
    "Korean",
    "Kurdish",
    "Kyrgyz",
    "Lang Belta",
    "Latgalian",
    "Latin",
    "Latvian",
    "Lithuanian",
    "Lojban",
    "Lule Saami",
    "Luxembourgish",
    "Macedonian",
    "Malayalam",
    "Maltese",
    "Marathi",
    "Myanmar (Burmese)",
    "Māori",
    "Nahuatl (Classical)",
    "Nepali",
    "Nogai",
    "Norwegian Bokmål",
    "Oriya",
    "Oromo",
    "Papiamento",
    "Persian",
    "Persian (Pinglish)",
    "Polish",
    "Portuguese (Brazil)",
    "Portuguese (Portugal)",
    "Punjabi",
    "Pyash",
    "Quechua",
    "Quenya",
    "Romanian",
    "Russian",
    "Russian (Classic)",
    "Russian (Latvia)",
    "Serbian",
    "Setswana",
    "Shan (Tai Yai)",
    "Sindarin",
    "Sindhi",
    "Sinhala",
    "Slovak",
    "Slovenian",
    "Spanish (Latin America)",
    "Spanish (Spain)",
    "Swahili",
    "Swedish",
    "Tamil",
    "Tatar",
    "Telugu",
    "Thai",
    "Tigrinya",
    "Turkish",
    "Turkmen",
    "Ukrainian",
    "Urdu",
    "Uyghur",
    "Uzbek",
    "Vietnamese (Central)",
    "Vietnamese (Northern)",
    "Vietnamese (Southern)",
    "Welsh",
    "xextan-test",
)
NEEDS_PRAAT = "This needs the bundled Praat program, which wasn't found"


class SpeechError(Exception):
    pass


@dataclass(frozen=True)
class Alignment:
    start: float
    end: float
    words: tuple[tuple[float, float, str], ...]
    phonemes: tuple[tuple[float, float, str], ...]


def _check(language: str, voice: str = "Male1") -> None:
    if not praat_engine.available():
        raise SpeechError(NEEDS_PRAAT)
    if language not in LANGUAGES:
        raise SpeechError(f"Unknown language: {language}")
    if voice not in VOICES:
        raise SpeechError(f"Unknown voice: {voice}")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def synthesize(
    text: str, language: str = DEFAULT_LANGUAGE, voice: str = "Female1", words_per_minute: int = 175,
    sampling_frequency: int = 44100,
) -> tuple[Sound, TextGrid]:  # fmt: skip
    """Speak ``text``. Returns the sound and a TextGrid of its sentences, clauses, words and phonemes."""
    _check(language, voice)
    text = _one_line(text)
    if not text:
        raise SpeechError("Type something to say first")
    folder = Path(tempfile.mkdtemp(prefix="phonolab-speech-"))
    try:
        (folder / "text.txt").write_text(text, encoding="utf-8")
        praat_engine.run_script(
            f'text$ = readFile$ ("{folder.as_posix()}/text.txt")\n'
            f'Create SpeechSynthesizer: "{language}", "{voice}"\n'
            f'Speech output settings: {sampling_frequency}, 0.01, 1, 1, {words_per_minute}, "IPA"\n'
            'To Sound: text$, "yes"\n'
            'sound = selected ("Sound")\n'
            'grid = selected ("TextGrid")\n'
            "selectObject: sound\n"
            f'Save as 32-bit WAV file: "{folder.as_posix()}/speech.wav"\n'
            "selectObject: grid\n"
            f'Save as text file: "{folder.as_posix()}/speech.TextGrid"\n'
        )
        loaded = Sound.from_file(folder / "speech.wav")
        grid = TextGrid.read(folder / "speech.TextGrid")
    except praat_engine.PraatEngineError as e:
        raise SpeechError(str(e)) from e
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return Sound(loaded.samples, loaded.sampling_rate, title=" ".join(text.split()[:3])), grid


def _intervals(grid: TextGrid, name: str, offset: float) -> tuple[tuple[float, float, str], ...]:
    tier = next((t for t in grid.tiers if t.name == name), None)
    if not isinstance(tier, IntervalTier):
        return ()
    return tuple((iv.xmin + offset, iv.xmax + offset, iv.text) for iv in tier.intervals)


def align(sound: Sound, start: float, end: float, text: str, language: str = DEFAULT_LANGUAGE) -> Alignment:
    """Find the words and phonemes of ``text`` in ``[start, end]`` of ``sound``."""
    _check(language)
    text = _one_line(text)
    if not text:
        raise SpeechError("There's no text to align")
    part = sound.extract(start, end)
    folder = Path(tempfile.mkdtemp(prefix="phonolab-align-"))
    try:
        (folder / "text.txt").write_text(text, encoding="utf-8")
        body = (
            f'text$ = readFile$ ("{folder.as_posix()}/text.txt")\n'
            "selectObject: s\n"
            'grid = To TextGrid: "sentence", ""\n'
            "Set interval text: 1, 1, text$\n"
            f'synth = Create SpeechSynthesizer: "{language}", "Male1"\n'
            # Praat refuses to compare sounds with different sampling frequencies.
            f'Speech output settings: {round(part.sampling_rate)}, 0.01, 1, 1, 175, "IPA"\n'
            "selectObject: synth, s, grid\n"
            "To TextGrid (align): 1, 1, 1, -35, 0.1, 0.1\n"
            'Save as text file: folder$ + "/aligned.TextGrid"\n'
        )
        _, out = praat_engine.analyse_with_files(part, body)
        try:
            grid = TextGrid.read(out / "aligned.TextGrid")
        finally:
            shutil.rmtree(out, ignore_errors=True)
    except praat_engine.PraatEngineError as e:
        raise SpeechError(str(e)) from e
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return Alignment(start, end, _intervals(grid, "word", start), _intervals(grid, "phoneme", start))


def align_many(sound: Sound, spans: list[tuple[float, float, str]], language: str) -> tuple[list[Alignment], list[str]]:
    """Align several stretches. One that fails doesn't stop the rest. Returns (alignments, problems)."""
    done, problems = [], []
    for start, end, text in spans:
        try:
            done.append(align(sound, start, end, text, language))
        except SpeechError as e:
            problems.append(f"{start:.3f} s: {e}")
    return done, problems


def fill_range(tier: IntervalTier, start: float, end: float, intervals: tuple[tuple[float, float, str], ...]) -> None:
    """Replace ``[start, end]`` of ``tier`` with ``intervals``, leaving the rest of the tier alone."""
    for t in (start, end):
        with contextlib.suppress(TextGridError):  # there's a boundary here already, or it's the tier's end
            tier.add_boundary(t)
    first = tier.interval_at(start + 1e-9)
    last = tier.interval_at(end - 1e-9)
    new = [(max(a, start), min(b, end), text) for a, b, text in intervals if min(b, end) - max(a, start) > 1e-9]
    if not new:
        new = [(start, end, "")]
    new[0] = (start, new[0][1], new[0][2])
    new[-1] = (new[-1][0], end, new[-1][2])
    tier.intervals[first : last + 1] = [Interval(a, b, text) for a, b, text in new]
    for left, right in zip(tier.intervals, tier.intervals[1:], strict=False):
        right.xmin = left.xmax


def apply_alignments(grid: TextGrid, source: str, alignments: list[Alignment]) -> None:
    """Put alignments on tiers named after ``source``, added next to it the first time."""
    position = next(i for i, tier in enumerate(grid.tiers) if tier.name == source) + 1
    for suffix, pick in (("words", lambda a: a.words), ("phonemes", lambda a: a.phonemes)):
        name = f"{source}_{suffix}"
        tier = next((t for t in grid.tiers if t.name == name), None)
        if tier is None:
            tier = IntervalTier(name, grid.xmin, grid.xmax)
            grid.tiers.insert(position, tier)
        position += 1
        for alignment in alignments:
            fill_range(tier, alignment.start, alignment.end, pick(alignment))
