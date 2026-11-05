"""Write phonolab.ico and phonolab.icns from the icon drawn in code (run: uv run python packaging/make_icon.py)."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from phonolab.ui.icon import render


def main():
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 - pixmaps need an app
    # Qt's writers store one image per file, which each OS scales down from.
    for name, size, image_format in (("phonolab.ico", 256, "ICO"), ("phonolab.icns", 512, "ICNS")):
        out = Path(__file__).with_name(name)
        if not render(size).toImage().save(str(out), image_format):
            raise SystemExit(f"Could not write {name} (Qt's {image_format} image plugin is missing)")
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
