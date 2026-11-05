"""Look and feel: design tokens, plot colours and the application stylesheet.

Widgets read ``COLORS`` when they are built, so the theme is applied once at start-up.
The light theme is built from white surfaces, light blues and cool greys.
"""

import sys

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette

# Interface tokens (chrome): used by the stylesheet and the palette.
UI = {
    "light": {
        "window": "#f3f6fa",  # app background behind cards and panels
        "surface": "#ffffff",  # panels, inputs, plots
        "surface_alt": "#f7f9fc",  # headers, hover rows
        "border": "#dbe3ec",
        "border_strong": "#c3cfdc",
        "text": "#1f2d3d",
        "text_muted": "#6b7a8c",
        "accent": "#3b82c4",
        "accent_hover": "#2f6fa8",
        "accent_soft": "#e4effa",
        "accent_text": "#ffffff",
        "highlight": "#cfe2f6",
        "danger": "#d64545",
    },
    "dark": {
        "window": "#1b1d21",
        "surface": "#23262b",
        "surface_alt": "#2a2e34",
        "border": "#353a42",
        "border_strong": "#454b55",
        "text": "#dde3ea",
        "text_muted": "#8d98a6",
        "accent": "#5a9ee0",
        "accent_hover": "#78b2ea",
        "accent_soft": "#26384b",
        "accent_text": "#0d1520",
        "highlight": "#2c4a69",
        "danger": "#ff6b6b",
    },
}

# Plot and annotation colours.
THEMES = {
    "light": {
        "background": "#ffffff",
        "foreground": "#566578",  # axes and their labels
        "waveform": "#2f6fb0",
        "cursor": "#e5534b",
        "playhead": "#3b82c4",
        "selection": (91, 155, 213, 48),
        "pitch": "#1f6fd1",
        "formant": "#e5534b",
        "intensity": "#e0a526",
        "pulses": "#3b82c4",
        "manipulation": "#2a9d8f",
        "boundary": "#3d5a80",
        "boundary_hover": "#e5534b",
        "tier_selected": (59, 130, 196, 18),
        "interval_selected": (91, 155, 213, 80),
        "muted": "#8a97a8",
        "track": "#eef3f9",
        "voiced": "#a9cdf0",
        "voiced_edge": "#3b82c4",
        "grid": "#e6ecf3",
    },
    "dark": {
        "background": "#23262b",
        "foreground": "#a7b2bf",
        "waveform": "#7fb0ea",
        "cursor": "#ff6b6b",
        "playhead": "#5a9ee0",
        "selection": (90, 158, 224, 45),
        "pitch": "#5aa9f0",
        "formant": "#ff6b6b",
        "intensity": "#f4c430",
        "pulses": "#5a9ee0",
        "manipulation": "#4fd1b5",
        "boundary": "#b6c3d3",
        "boundary_hover": "#ff6b6b",
        "tier_selected": (90, 158, 224, 30),
        "interval_selected": (90, 158, 224, 70),
        "muted": "#8d98a6",
        "track": "#2a2e34",
        "voiced": "#2f5f8f",
        "voiced_edge": "#78b2ea",
        "grid": "#30353c",
    },
}
THEME_CHOICES = ("system", "light", "dark")

COLORS = dict(THEMES["light"])
TOKENS = dict(UI["light"])

SPECTROGRAM_COLORMAPS = {
    "Grey (Praat)": None,  # background = quiet, axis colour = loud
    "Blues": "Blues",
    "Viridis": "viridis",
    "Magma": "magma",
    "Inferno": "inferno",
}


def colormap(name: str) -> pg.ColorMap:
    target = SPECTROGRAM_COLORMAPS.get(name)
    if target is None:
        quiet = QColor(COLORS["background"])
        loud = QColor("#000000" if QColor(COLORS["background"]).lightness() > 128 else "#ffffff")
        return pg.ColorMap([0.0, 1.0], [quiet.getRgb()[:3], loud.getRgb()[:3]])
    if target == "Blues":  # matplotlib's sequential blues, light to dark
        return pg.colormap.get("Blues", source="matplotlib")
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
    """Set fonts, palette, stylesheet and plot colours. Returns the theme actually used."""
    name = resolve(choice, app)
    COLORS.clear()
    COLORS.update(THEMES[name])
    TOKENS.clear()
    TOKENS.update(UI[name])
    if app is not None:
        app.setFont(_ui_font(app))
        app.setPalette(_palette(TOKENS))
        app.setStyleSheet(stylesheet(TOKENS))
    configure_pyqtgraph()
    return name


def _ui_font(app) -> QFont:
    font = QFont(app.font())
    if sys.platform == "win32":  # macOS and Linux already default to their system font
        font.setFamily("Segoe UI")
        font.setPointSizeF(9.5)
    return font


def _palette(t: dict) -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    colours = {
        roles.Window: t["window"],
        roles.WindowText: t["text"],
        roles.Base: t["surface"],
        roles.AlternateBase: t["surface_alt"],
        roles.ToolTipBase: t["surface"],
        roles.ToolTipText: t["text"],
        roles.Text: t["text"],
        roles.Button: t["surface"],
        roles.ButtonText: t["text"],
        roles.BrightText: t["danger"],
        roles.Highlight: t["accent"],
        roles.HighlightedText: t["accent_text"],
        roles.Link: t["accent"],
        roles.PlaceholderText: t["text_muted"],
        roles.Mid: t["border"],
        roles.Dark: t["border_strong"],
        roles.Light: t["surface"],
    }
    for role, colour in colours.items():
        p.setColor(role, QColor(colour))
    for role in (roles.Text, roles.ButtonText, roles.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text_muted"]))
    return p


def stylesheet(t: dict) -> str:
    """The application stylesheet for a set of tokens."""
    return _QSS.format(**t)


_QSS = """
QMainWindow, QDialog {{ background: {window}; }}
QToolTip {{
    background: {surface}; color: {text}; border: 1px solid {border_strong};
    border-radius: 4px; padding: 4px 6px;
}}

/* Menus */
QMenuBar {{ background: {surface}; border-bottom: 1px solid {border}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {accent_soft}; color: {accent_hover}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 5px 28px 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}
QMenu::item:disabled {{ color: {text_muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

/* Document tabs */
QTabWidget::pane {{ border: none; background: {window}; }}
QTabBar {{ background: {window}; }}
QTabBar::tab {{
    background: transparent; color: {text_muted}; padding: 7px 14px; margin: 4px 2px 0 2px;
    border: 1px solid transparent; border-bottom: 2px solid transparent;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QTabBar::tab:hover {{ color: {text}; background: {surface_alt}; }}
QTabBar::tab:selected {{
    color: {text}; background: {surface}; border-color: {border}; border-bottom: 2px solid {accent};
}}

/* Docks */
QDockWidget {{ color: {text_muted}; }}
QDockWidget::title {{
    background: {window}; padding: 6px 8px; text-align: left; font-weight: 600;
}}
QDockWidget > QWidget {{ background: {window}; }}

/* Group boxes as cards */
QGroupBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px;
    margin-top: 14px; padding: 10px 8px 6px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {text_muted}; font-weight: 600;
}}

/* Buttons */
QPushButton {{
    background: {surface}; color: {text}; border: 1px solid {border_strong};
    border-radius: 6px; padding: 5px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {accent_soft}; border-color: {accent}; }}
QPushButton:pressed {{ background: {highlight}; }}
QPushButton:disabled {{ color: {text_muted}; border-color: {border}; background: {surface_alt}; }}
QPushButton:default, QPushButton#primary {{
    background: {accent}; color: {accent_text}; border: 1px solid {accent}; font-weight: 600;
}}
QPushButton:default:hover, QPushButton#primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QToolButton {{ border: 1px solid transparent; border-radius: 5px; padding: 3px 6px; background: transparent; }}
QToolButton:hover {{ background: {accent_soft}; border-color: {border}; }}
QToolButton:checked {{ background: {highlight}; }}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {surface}; color: {text}; border: 1px solid {border_strong}; border-radius: 6px;
    padding: 4px 6px; selection-background-color: {highlight}; selection-color: {text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QListWidget:focus {{ border: 1px solid {accent}; }}
QLineEdit:disabled {{ background: {surface_alt}; color: {text_muted}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; selection-background-color: {accent_soft};
    selection-color: {text}; outline: none;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
QListWidget::item:hover {{ background: {surface_alt}; }}
QListWidget::item:selected {{ background: {accent_soft}; color: {text}; }}

/* Progress and sliders */
QProgressBar {{
    background: {surface_alt}; border: 1px solid {border}; border-radius: 5px; height: 10px; text-align: center;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}

/* Scroll bars */
QScrollBar:horizontal {{ background: {window}; height: 12px; margin: 2px; border: none; }}
QScrollBar:vertical {{ background: {window}; width: 12px; margin: 2px; border: none; }}
QScrollBar::handle {{ background: {border_strong}; border-radius: 4px; min-width: 28px; min-height: 28px; }}
QScrollBar::handle:hover {{ background: {accent}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* Splitters and status bar */
QSplitter::handle {{ background: {window}; }}
QSplitter::handle:vertical {{ height: 5px; }}
QSplitter::handle:hover {{ background: {accent_soft}; }}
QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {text_muted}; }}
QStatusBar QLabel {{ color: {text_muted}; padding: 0 6px; }}

/* Plot panes sit on white cards */
QGraphicsView {{ border: 1px solid {border}; border-radius: 4px; background: {surface}; }}

/* Named widgets */
QWidget#editorPage {{ background: {window}; }}
QLabel#appTitle {{ color: {accent}; }}
QLabel#muted, QLabel#hint {{ color: {text_muted}; }}
QFrame#startCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QLabel#sectionTitle {{ color: {text_muted}; font-weight: 600; }}
"""
