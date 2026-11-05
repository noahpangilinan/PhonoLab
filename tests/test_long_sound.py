import pickle

import numpy as np
import pytest

from phonolab.core import sound as sound_module
from phonolab.core.sound import LongSoundError, Sound, SoundLoadCancelledError
from tests.conftest import make_sine
from tests.test_core_misc import write_m4a


@pytest.fixture
def long_threshold(monkeypatch):
    """Treat anything over 1000 sample values as long, so small test files take the long path."""
    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 1000)


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "s.wav"
    make_sine(freq=200, amplitude=0.5, duration=3.0, channels=2).save(path)
    return path


def test_long_sound_matches_normal_loading(wav, monkeypatch):
    normal = Sound.from_file(wav)
    assert not normal.is_long
    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 1000)
    long = Sound.from_file(wav)
    assert long.is_long and long.n_channels == 2 and long.duration == normal.duration
    assert np.allclose(long.samples[1000:2000], normal.samples[1000:2000], atol=1e-6)
    assert long.peak == pytest.approx(normal.peak, abs=1e-6)
    block = long.block_envelope[1][0, 0]  # max of the first block, channel 0
    assert block == pytest.approx(normal.samples[:256, 0].max(), abs=1e-6)


def test_long_sound_refuses_whole_file_access(wav, long_threshold):
    long = Sound.from_file(wav)
    with pytest.raises(LongSoundError):
        long.mono  # noqa: B018
    with pytest.raises(LongSoundError):
        long.praat  # noqa: B018


def test_extract_gives_an_ordinary_sound(wav, long_threshold, monkeypatch):
    long = Sound.from_file(wav)
    part = long.extract(1.0, 1.5)
    assert not part.is_long and part.duration == pytest.approx(0.5) and part.mono.shape == (8000,)
    monkeypatch.setattr(sound_module, "MAX_PART_SECONDS", 1.0)
    with pytest.raises(LongSoundError, match="or less"):
        long.extract(0.0, 2.0)


def test_part_is_transparent_for_ordinary_sounds(wav):
    normal = Sound.from_file(wav)
    assert normal.part(1.0, 2.0) == (normal, 1.0, 2.0)


def test_pickling_sends_the_file_name_not_the_samples(wav, long_threshold):
    long = Sound.from_file(wav)
    data = pickle.dumps(long)
    assert len(data) < 5000
    copy = pickle.loads(data)
    assert copy.is_long and np.array_equal(copy.samples[:100], long.samples[:100])


def test_loading_reports_progress_and_can_be_cancelled(wav, long_threshold, monkeypatch):
    monkeypatch.setattr(sound_module, "_CHUNK_FRAMES", 4096)
    seen = []
    Sound.from_file(wav, progress=lambda f: seen.append(f))
    assert seen == sorted(seen) and seen[-1] == 1.0 and len(seen) > 3
    with pytest.raises(SoundLoadCancelledError):
        Sound.from_file(wav, progress=lambda f: False)


def test_m4a_takes_the_long_path(tmp_path, long_threshold):
    path = tmp_path / "memo.m4a"
    write_m4a(path)
    long = Sound.from_file(path)
    assert long.is_long and long.duration == pytest.approx(1.0, abs=0.06) and long.n_channels == 2


def test_saving_a_long_sound_streams_it(wav, long_threshold, tmp_path, monkeypatch):
    long = Sound.from_file(wav)
    out = tmp_path / "copy.flac"
    monkeypatch.setattr(sound_module, "_CHUNK_FRAMES", 4096)
    long.save(out)
    monkeypatch.setattr(sound_module, "LONG_SOUND_VALUES", 10**9)
    assert Sound.from_file(out).duration == pytest.approx(3.0)


def test_not_enough_disk_space_is_reported(wav, long_threshold, monkeypatch):
    usage = sound_module.shutil.disk_usage("/")
    monkeypatch.setattr(sound_module.shutil, "disk_usage", lambda _: usage._replace(free=10))
    with pytest.raises(sound_module.SoundLoadError, match="free disk space"):
        Sound.from_file(wav)


def test_shift_times_moves_every_time_field():
    from phonolab.core.analysis import PitchResult, shift_times
    from phonolab.core.voice import VoicingResult

    assert shift_times(PitchResult(np.array([1.0]), np.array([100.0])), 10).times[0] == 11
    moved = shift_times(VoicingResult(np.array([1.0]), np.array([2.0])), 10)
    assert (moved.starts[0], moved.ends[0]) == (11, 12)


def test_analyses_work_on_stretches_of_a_long_sound(long_threshold, tmp_path):
    from phonolab.core import queries, spectrum, voice
    from phonolab.core.analysis import FormantSettings, PitchSettings, SpectrogramSettings, compute_spectrogram
    from tests.conftest import make_vowel

    path = tmp_path / "v.wav"
    make_vowel(f0=120, duration=2.0).save(path)
    long = Sound.from_file(path)
    report = voice.voice_report(long, PitchSettings(), voice.VoiceSettings(), 0.5, 1.5)
    assert float(report.value("Median pitch").split()[0]) == pytest.approx(120, abs=2)
    assert spectrum.cpps(long, 0.2, 1.8) > 5
    r = spectrum.compute_slice(long, spectrum.SpectrumSettings(), 0.5, 0.6)
    assert (r.start, r.end) == (0.5, 0.6)
    assert compute_spectrogram(long, SpectrogramSettings(), 1.0, 1.5).times[0] >= 1.0
    assert len(queries.formant_bandwidths_at(long, FormantSettings(), 1.0)) == 5


def test_batch_measures_long_files_in_chunks(long_threshold, tmp_path, monkeypatch):
    from phonolab.core import batch
    from phonolab.core.batch import BatchOptions
    from phonolab.core.textgrid import TextGrid
    from tests.conftest import make_vowel

    monkeypatch.setattr(batch, "MAX_PART_SECONDS", 0.5)  # four chunks
    path = tmp_path / "v.wav"
    make_vowel(f0=120, duration=2.0).save(path)
    (row,) = batch.measure_file(path, BatchOptions())
    assert row["f0_median_hz"] == pytest.approx(120, abs=2) and row["F1_mean_hz"] > 300
    assert "skipped" in row["error"]
    grid = TextGrid.for_duration(2.0, ["words"])
    grid.tiers[0].add_boundary(1.0)
    grid.tiers[0].set_text(1, "hi")
    grid.write(path.with_suffix(".TextGrid"))
    (row,) = batch.measure_file(path, BatchOptions(measures=frozenset({"pitch"}), tier="words"))
    assert row["start_s"] == 1.0 and row["f0_median_hz"] == pytest.approx(120, abs=2) and "error" not in row
