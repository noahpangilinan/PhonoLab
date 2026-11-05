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
