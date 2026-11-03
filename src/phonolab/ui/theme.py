"""Colours and global plot options shared by all views."""

import pyqtgraph as pg

COLORS = {
    "background": "#ffffff",
    "foreground": "#1f2933",
    "waveform": "#1f3a5f",
    "cursor": "#d62728",
    "playhead": "#1f77b4",
    "selection": (255, 196, 0, 70),
    "pitch": "#1f77d4",
    "formant": "#e0261b",
    "intensity": "#d4a017",
    "pulses": "#1f77d4",
    "manipulation": "#2ca02c",
    "boundary": "#1f3a5f",
    "boundary_hover": "#d62728",
    "tier_selected": (31, 119, 180, 28),
    "interval_selected": (255, 196, 0, 110),
    "muted": "#7b8794",
}

SPECTROGRAM_COLORMAPS = {
    "Grey (Praat)": None,  # built below: white = quiet, black = loud
    "Viridis": "viridis",
    "Magma": "magma",
    "Inferno": "inferno",
}


def colormap(name: str) -> pg.ColorMap:
    target = SPECTROGRAM_COLORMAPS.get(name)
    if target is None:
        return pg.ColorMap([0.0, 1.0], [(255, 255, 255), (0, 0, 0)])
    return pg.colormap.get(target)


def configure_pyqtgraph() -> None:
    pg.setConfigOptions(
        background=COLORS["background"],
        foreground=COLORS["foreground"],
        antialias=False,
        imageAxisOrder="row-major",
    )
