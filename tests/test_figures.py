import pytest

from phonolab.core import figures
from phonolab.core.figures import FigureRequest, FigureSettings
from phonolab.core.textgrid import TextGrid
from tests.conftest import make_vowel


@pytest.fixture
def vowel():
    return make_vowel(duration=1.0)


@pytest.fixture
def grid():
    tg = TextGrid.for_duration(1.0, ["words"], ["tones"])
    tg.tiers[0].add_boundary(0.5)
    tg.tiers[0].set_text(0, r"\ae")
    tg.tiers[1].add_point(0.3, "H*")
    return tg


@pytest.mark.parametrize("ext", ["pdf", "svg", "png"])
def test_all_panels_export(vowel, grid, tmp_path, ext):
    settings = FigureSettings(show_pitch_on_spectrogram=True, colour=True, dpi=100)
    req = FigureRequest(panels=figures.PANELS, start=0.1, end=0.9, figure=settings)
    fig = figures.make_figure(vowel, grid, req)
    assert len(fig.axes) == 6  # five panels + the pitch axis twinned on the spectrogram
    path = tmp_path / f"fig.{ext}"
    figures.save_figure(fig, path, dpi=settings.dpi)
    assert path.stat().st_size > 1000


def test_figure_size_follows_settings(vowel):
    fig = figures.make_figure(
        vowel, None, FigureRequest(panels=("waveform", "pitch"), figure=FigureSettings(width=5, panel_height=1.5))
    )
    assert tuple(fig.get_size_inches()) == pytest.approx((5, 3))


def test_textgrid_panel_skipped_without_tiers_and_errors(vowel, grid):
    with pytest.raises(ValueError):
        figures.make_figure(vowel, None, FigureRequest(panels=("textgrid",)))
    fig = figures.make_figure(vowel, grid, FigureRequest(panels=("textgrid",), tiers=("words",)))
    labels = [t.get_text() for t in fig.axes[0].texts]
    assert labels == ["æ"]  # backslash code drawn as IPA, only the chosen tier
    with pytest.raises(ValueError):
        figures.make_figure(vowel, None, FigureRequest(start=0.5, end=0.5))
