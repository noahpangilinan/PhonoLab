import numpy as np
import pytest

from phonolab.audio.player import PlaybackBuffer
from phonolab.core.analysis import PitchSettings
from phonolab.core.settings import MemoryStore, Preferences
from phonolab.core.sound import Sound, SoundLoadError
from tests.conftest import make_sine


def test_playback_buffer_respects_range():
    samples = np.arange(10, dtype=np.float32)[:, None]
    buf = PlaybackBuffer(samples, 2, 7)
    out = np.empty((4, 1), dtype=np.float32)
    assert buf.fill(out) == 4
    assert out[:, 0].tolist() == [2, 3, 4, 5]
    assert buf.fill(out) == 1
    assert out[:, 0].tolist() == [6, 0, 0, 0]
    assert buf.done


def test_playback_buffer_clamps_out_of_range():
    buf = PlaybackBuffer(np.zeros((5, 2)), -3, 100)
    assert (buf.start, buf.end) == (0, 5)


def test_sound_save_load_and_extract(tmp_path):
    snd = make_sine(duration=1.0, channels=2)
    path = tmp_path / "a.wav"
    snd.save(path)
    loaded = Sound.from_file(path)
    assert loaded.n_channels == 2 and loaded.sampling_rate == 16000
    assert loaded.duration == pytest.approx(1.0)
    part = loaded.extract(0.75, 0.25)
    assert part.duration == pytest.approx(0.5)


def write_m4a(path, freq=200.0, duration=1.0, sr=44100, channels=2):
    """Encode a sine as AAC in an MP4 container, like a phone voice memo."""
    import av

    t = np.arange(int(duration * sr)) / sr
    x = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    with av.open(str(path), "w", format="mp4") as out:
        stream = out.add_stream("aac", rate=sr, layout="stereo" if channels == 2 else "mono")
        frame_size = 1024
        for i in range(0, len(x), frame_size):
            block = np.tile(x[i : i + frame_size], (channels, 1))
            frame = av.AudioFrame.from_ndarray(block, format="fltp", layout=stream.layout.name)
            frame.sample_rate = sr
            frame.pts = i
            out.mux(stream.encode(frame))
        out.mux(stream.encode(None))


def test_load_m4a(tmp_path):
    path = tmp_path / "memo.m4a"
    write_m4a(path)
    snd = Sound.from_file(path)
    assert snd.sampling_rate == 44100 and snd.n_channels == 2
    assert snd.duration == pytest.approx(1.0, abs=0.06)  # AAC pads to whole frames
    from phonolab.core.analysis import compute_pitch

    assert np.nanmedian(compute_pitch(snd, PitchSettings()).frequencies) == pytest.approx(200, abs=2)


def test_sound_load_error(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(SoundLoadError):
        Sound.from_file(bad)


def test_preferences_persist_settings_and_recent(tmp_path):
    prefs = Preferences(MemoryStore())
    assert prefs.analysis_settings("pitch") == PitchSettings()
    prefs.set_analysis_settings("pitch", PitchSettings(ceiling=300))
    assert prefs.analysis_settings("pitch").ceiling == 300
    for i in range(15):
        prefs.add_recent_file(tmp_path / f"{i}.wav")
    recent = prefs.recent_files()
    assert len(recent) == 10 and recent[0].endswith("14.wav")
    prefs.add_recent_file(tmp_path / "3.wav")
    assert prefs.recent_files()[0].endswith("3.wav")
