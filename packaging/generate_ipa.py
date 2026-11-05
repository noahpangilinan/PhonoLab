"""Regenerate the table in core/ipa.py from the bundled Praat (run: uv run python packaging/generate_ipa.py).

Asks Praat which backslash + two-character codes it converts, by labelling a TextGrid with every
candidate and running "Convert to Unicode". Space-ended codes and ASCII results are parser artefacts.
"""

import re
import string
import tempfile
import unicodedata
from pathlib import Path

from phonolab.core import praat_engine
from phonolab.core.textgrid import Interval, IntervalTier, TextGrid

IPA_MODULE = Path(__file__).parents[1] / "src/phonolab/core/ipa.py"


def main() -> None:
    chars = [c for c in string.printable[:95] if c != '"']
    codes = ["\\" + a + b for a in chars for b in chars]
    grid = TextGrid(0.0, float(len(codes)))
    grid.tiers.append(IntervalTier("x", 0.0, float(len(codes)), [Interval(i, i + 1.0, c) for i, c in enumerate(codes)]))
    with tempfile.TemporaryDirectory() as folder:
        source, result = Path(folder) / "in.TextGrid", Path(folder) / "out.TextGrid"
        grid.write(source)
        praat_engine.run_script(
            f'Read from file: "{source.as_posix()}"\nConvert to Unicode\nSave as text file: "{result.as_posix()}"\n'
        )
        converted = TextGrid.read(result).tiers[0].intervals
    table = {c: iv.text for c, iv in zip(codes, converted, strict=True) if iv.text != c}
    keep = {k: v for k, v in sorted(table.items()) if k[2] != " " and not v.isascii()}

    def line(code: str, symbol: str) -> str:
        name = " + ".join(unicodedata.name(ch, "").lower() for ch in symbol)
        return f"    {code!r}: {ascii(symbol)},  # {name}"

    body = "\n".join(line(k, v) for k, v in keep.items())
    text = IPA_MODULE.read_text(encoding="utf-8")
    text = re.sub(
        r"TRIGRAPHS: dict\[str, str\] = \{.*?\n\}\n",
        lambda _: f"TRIGRAPHS: dict[str, str] = {{\n{body}\n}}\n",
        text,
        flags=re.S,
    )
    text = re.sub(r"Generated from Praat [\d.]+", f"Generated from Praat {praat_engine.version()}", text)
    text = text.replace("by trying every\nbackslash", "by packaging/generate_ipa.py, trying every\nbackslash")
    IPA_MODULE.write_text(text, encoding="utf-8")
    print(f"{len(keep)} symbols written to {IPA_MODULE.name}")


if __name__ == "__main__":
    main()
