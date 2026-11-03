import numpy as np
import pytest

from phonolab.core import sound_ops as ops
from phonolab.core.analysis import PitchSettings, compute_pitch
from phonolab.core.sound import Sound
from phonolab.core.spectrum import SpectrumSettings, compute_ltas
from phonolab.ui.dialogs.record_dialog import RecordingBuffer
from tests.conftest import make_sine, make_vowel


def test_extract_and_mono_and_reverse():
    snd = make_sine(duration=1.0, channels=2)
    part = ops.extract(snd, 0.25, 0.75)
    assert part.duration == pytest.approx(0.5) and part.n_channels == 2
    assert part.path is None and part.name.endswith("_part")
    assert ops.to_mono(snd).n_channels == 1
    rev = ops.reverse(snd)
    assert np.allclose(rev.samples[0], snd.samples[-1])


def test_resample_keeps_pitch_and_channels():
    snd = make_vowel(f0=150, duration=0.6, sr=16000)
    out = ops.resample(snd, ops.ResampleSettings(sampling_rate=8000))
    assert out.sampling_rate == 8000 and out.duration == pytest.approx(0.6, abs=0.01)
    assert np.nanmedian(compute_pitch(out, PitchSettings()).frequencies) == pytest.approx(150, abs=2)


def test_band_filters_shape_the_spectrum():
    rng = np.random.default_rng(1)
    noise = Sound(rng.normal(0, 0.1, 32000), 16000)
    band = ops.BandSettings(low=1000, high=2000, smoothing=100)

    def level(snd, lo, hi):
        r = compute_ltas(snd, SpectrumSettings(max_frequency=8000), 0, snd.duration)
        return r.db[(r.frequencies > lo) & (r.frequencies < hi)].mean()

    passed = ops.pass_band(noise, band)
    assert level(passed, 1200, 1800) - level(passed, 3000, 5000) > 30
    stopped = ops.stop_band(noise, band)
    assert level(stopped, 3000, 5000) - level(stopped, 1200, 1800) > 30


def test_scale_peak_and_concatenate():
    a = make_sine(amplitude=0.2, duration=0.5)
    scaled = ops.scale_peak(a, ops.ScalePeakSettings(peak=0.9))
    assert np.max(np.abs(scaled.samples)) == pytest.approx(0.9)
    joined = ops.concatenate([a, make_sine(duration=0.25, channels=2)])
    assert joined.duration == pytest.approx(0.75) and joined.n_channels == 2
    with pytest.raises(ValueError):
        ops.concatenate([a, make_sine(sr=8000)])


@pytest.mark.parametrize("waveform", list(ops.Waveform))
def test_generate(waveform):
    snd = ops.generate(ops.ToneSettings(waveform=waveform, frequency=200, duration=0.5, sampling_rate=16000))
    assert snd.duration == pytest.approx(0.5) and np.max(np.abs(snd.samples)) <= 0.5 + 1e-9
    if waveform in (ops.Waveform.SINE, ops.Waveform.PULSE_TRAIN):
        assert np.nanmedian(compute_pitch(snd, PitchSettings()).frequencies) == pytest.approx(200, abs=2)


def test_save_as_adopts_path(tmp_path):
    snd = ops.generate(ops.ToneSettings(duration=0.2))
    assert snd.path is None
    for ext in ("wav", "flac", "aiff", "ogg"):
        snd.save(tmp_path / f"x.{ext}")
        assert Sound.from_file(tmp_path / f"x.{ext}").duration == pytest.approx(0.2, abs=0.01)
    snd.save_as(tmp_path / "tone.wav")
    assert snd.path == tmp_path / "tone.wav" and snd.name == "tone"


def test_recording_buffer():
    buf = RecordingBuffer(channels=1)
    buf.add(np.full((100, 1), 0.5, dtype=np.float32))
    buf.add(np.ones((50, 1), dtype=np.float32))
    assert buf.n_frames == 150 and buf.clipped and buf.peak == 1.0
    assert buf.samples().shape == (150, 1)
