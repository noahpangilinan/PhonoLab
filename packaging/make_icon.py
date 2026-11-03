"""Write packaging/phonolab.ico from the icon drawn in code (run: uv run python packaging/make_icon.py)."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from phonolab.ui.icon import render


def main():
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 - pixmaps need an app
    out = Path(__file__).with_name("phonolab.ico")
    # Qt's ICO writer stores one image per file; 256 px is what Windows scales down from.
    if not render(256).toImage().save(str(out), "ICO"):
        raise SystemExit("Could not write the icon (Qt's ICO image plugin is missing)")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
