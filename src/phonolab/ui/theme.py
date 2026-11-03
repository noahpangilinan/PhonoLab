"""Colours and global plot options shared by all views.

Widgets read ``COLORS`` when they are built, so the theme is applied once at start-up.
"""

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette

THEMES = {
    "light": {
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
        "track": "#eef1f5",
        "voiced": "#9cc3ea",
        "voiced_edge": "#4a86c5",
    },
    "dark": {
        "background": "#1e1f22",
        "foreground": "#d8dee9",
        "waveform": "#8ab4f8",
        "cursor": "#ff6b6b",
        "playhead": "#4dabf7",
        "selection": (255, 196, 0, 50),
        "pitch": "#4dabf7",
        "formant": "#ff5c5c",
        "intensity": "#f4c430",
        "pulses": "#4dabf7",
        "manipulation": "#51cf66",
        "boundary": "#c0c8d4",
        "boundary_hover": "#ff6b6b",
        "tier_selected": (77, 171, 247, 40),
        "interval_selected": (255, 196, 0, 80),
        "muted": "#8a94a3",
        "track": "#26282d",
        "voiced": "#2f5f8f",
        "voiced_edge": "#6aa7e0",
    },
}
THEME_CHOICES = ("system", "light", "dark")

COLORS = dict(THEMES["light"])

SPECTROGRAM_COLORMAPS = {
    "Grey (Praat)": None,  # background = quiet, foreground = loud (white-to-black in the light theme)
    "Viridis": "viridis",
    "Magma": "magma",
    "Inferno": "inferno",
}


def colormap(name: str) -> pg.ColorMap:
    target = SPECTROGRAM_COLORMAPS.get(name)
    if target is None:
        quiet, loud = QColor(COLORS["background"]), QColor(COLORS["foreground"])
        return pg.ColorMap([0.0, 1.0], [quiet.getRgb()[:3], loud.getRgb()[:3]])
    return pg.colormap.get(target)


def configure_pyqtgraph() -> None:
    pg.setConfigOptions(
        background=COLORS["background"],
        foreground=COLORS["foreground"],
        antialias=False,
        imageAxisOrder="row-major",
    )


def resolve(choice: str, app=None) -> str:
    """'system' becomes 'light' or 'dark' according to the OS setting."""
    if choice in THEMES:
        return choice
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return "dark"
    return "light"


def apply_theme(app, choice: str = "system") -> str:
    """Set the application palette and plot colours. Returns the theme actually used."""
    name = resolve(choice, app)
    COLORS.clear()
    COLORS.update(THEMES[name])
    if app is not None:
        app.setPalette(_dark_palette() if name == "dark" else app.style().standardPalette())
    configure_pyqtgraph()
    return name


def _dark_palette() -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    colours = {
        roles.Window: "#2b2d31",
        roles.WindowText: "#d8dee9",
        roles.Base: "#1e1f22",
        roles.AlternateBase: "#2b2d31",
        roles.ToolTipBase: "#2b2d31",
        roles.ToolTipText: "#d8dee9",
        roles.Text: "#d8dee9",
        roles.Button: "#34363c",
        roles.ButtonText: "#d8dee9",
        roles.BrightText: "#ff6b6b",
        roles.Highlight: "#3d6fb4",
        roles.HighlightedText: "#ffffff",
        roles.Link: "#4dabf7",
        roles.PlaceholderText: "#8a94a3",
    }
    for role, colour in colours.items():
        p.setColor(role, QColor(colour))
    for role in (roles.Text, roles.ButtonText, roles.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6b7280"))
    return p
