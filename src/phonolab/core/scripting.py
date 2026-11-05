"""Run Praat scripts or Python code on a sound (and its TextGrid).

Results are plain data (arrays, TextGrids, text) so scripts can run in a worker process.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import shlex
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call, run

from phonolab.core import praat_engine
from phonolab.core.sound import Sound
from phonolab.core.textgrid import TextGrid


@dataclass
class ScriptResult:
    output: str = ""
    sounds: list[tuple[str, np.ndarray, float]] = field(default_factory=list)  # (name, samples, sr)
    textgrid: TextGrid | None = None
    error: str | None = None


def parse_arguments(text: str) -> list:
    """Form arguments as typed: numbers become floats, everything else stays a string."""
    args = []
    for token in shlex.split(text, posix=True):
        try:
            args.append(float(token))
        except ValueError:
            args.append(token)
    return args


def _to_praat_textgrid(tg: TextGrid):
    fd, path = tempfile.mkstemp(suffix=".TextGrid")
    os.close(fd)
    try:
        tg.write(path)
        return parselmouth.read(path)
    finally:
        os.remove(path)


def _from_praat_textgrid(obj) -> TextGrid:
    fd, path = tempfile.mkstemp(suffix=".TextGrid")
    os.close(fd)
    try:
        call(obj, "Save as text file", path)
        return TextGrid.read(path)
    finally:
        os.remove(path)


# Runs the user's script with the Sound (and TextGrid) selected, then saves whatever it left selected.
_WRAPPER = """original = Read from file: "{wav}"
Rename: "{name}"
{load_textgrid}
{select}
runScript: "{script}"{arguments}
sounds# = selected# ("Sound")
grids# = selected# ("TextGrid")
for i to size (sounds#)
    selectObject: sounds# [i]
    appendFileLine: "{folder}/names.txt", selected$ ("Sound")
    Save as binary file: "{folder}/sound" + string$ (i) + ".Sound"
endfor
if size (grids#) > 0
    selectObject: grids# [1]
    Save as text file: "{folder}/result.TextGrid"
endif
"""


def _praat_argument(value) -> str:
    if isinstance(value, float):
        return repr(value)
    return '"' + value.replace('"', '""') + '"'


def _run_on_engine(sound: Sound, textgrid: TextGrid | None, script: str, arguments: str) -> ScriptResult:
    """Run on the bundled Praat program. Scripts can save files, as they can from Praat's script window."""
    args = "".join(", " + _praat_argument(a) for a in parse_arguments(arguments))
    with tempfile.TemporaryDirectory(prefix="phonolab-script-") as folder_name:
        folder = Path(folder_name)
        (folder / "user.praat").write_text(script, encoding="utf-8")
        load_textgrid, select = "", "selectObject: original"
        if textgrid is not None:
            textgrid.write(folder / "input.TextGrid")
            load_textgrid = (
                f'grid = Read from file: "{folder.as_posix()}/input.TextGrid"\nRename: "{_safe(sound.name)}"'
            )
            select = "selectObject: original, grid"
        wrapper = _WRAPPER.format(
            wav=praat_engine.sound_file(sound).as_posix(), name=_safe(sound.name), load_textgrid=load_textgrid,
            select=select, script=(folder / "user.praat").as_posix(), arguments=args, folder=folder.as_posix(),
        )  # fmt: skip
        try:
            output = praat_engine.run_script(wrapper)
        except praat_engine.PraatEngineError as e:
            return ScriptResult(error=str(e))
        result = ScriptResult(output=output)
        names_file = folder / "names.txt"
        names = names_file.read_text(encoding="utf-8").split("\n") if names_file.exists() else []
        for i, name in enumerate(filter(None, names), 1):
            out = parselmouth.read(str(folder / f"sound{i}.Sound"))
            values = out.values.T.copy()
            # Leave the input out unless the script changed it: only new sounds come back.
            if values.shape[1] != 1 or len(values) != sound.n_samples or not np.array_equal(values[:, 0], sound.mono):
                result.sounds.append((name, values, out.sampling_frequency))
        if (folder / "result.TextGrid").exists():
            result.textgrid = TextGrid.read(folder / "result.TextGrid")
        return result


def _safe(name: str) -> str:
    """Praat object names allow only letters, digits and underscores."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def run_praat(sound: Sound, textgrid: TextGrid | None, script: str, arguments: str = "") -> ScriptResult:
    """Run a Praat script with the Sound (and TextGrid) selected, like running it from Praat's object list."""
    if praat_engine.available():
        return _run_on_engine(sound, textgrid, script, arguments)
    praat_sound = sound.praat.copy()
    praat_sound.name = sound.name
    objects = [praat_sound]
    if textgrid is not None:
        praat_tg = _to_praat_textgrid(textgrid)
        praat_tg.name = sound.name
        objects.append(praat_tg)
    try:
        selected, output = run(objects, script, *parse_arguments(arguments), capture_output=True)
    except Exception as e:  # PraatError carries Praat's own message
        return ScriptResult(error=str(e).strip())
    result = ScriptResult(output=output)
    for obj in selected if isinstance(selected, list) else [selected]:
        kind = getattr(obj, "class_name", "")
        if isinstance(obj, parselmouth.Sound):
            # Leave the input untouched: only new (or modified copies of) sounds come back.
            if obj is not praat_sound or not np.array_equal(obj.values[0], sound.mono):
                result.sounds.append((obj.name or "script_output", obj.values.T.copy(), obj.sampling_frequency))
        elif kind == "TextGrid":
            result.textgrid = _from_praat_textgrid(obj)
    return result


PYTHON_HELP = """\
# Python with these names available:
#   sound      the current Sound (sound.samples, sound.sampling_rate, sound.praat)
#   textgrid   a copy of its TextGrid, or None
#   np, parselmouth, call (parselmouth.praat.call), Sound, TextGrid
# print() goes to the output. To open results, assign:
#   new_sounds   = [Sound(...), ...]
#   new_textgrid = TextGrid(...)   (replaces the current annotations, undoably)
"""


def run_python(sound: Sound, textgrid: TextGrid | None, code: str) -> ScriptResult:
    namespace = {
        "sound": sound,
        "textgrid": textgrid.copy() if textgrid is not None else None,
        "np": np,
        "parselmouth": parselmouth,
        "call": call,
        "Sound": Sound,
        "TextGrid": TextGrid,
    }
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exec(compile(code, "<script>", "exec"), namespace)  # noqa: S102 - the user's own script
    except Exception:
        return ScriptResult(output=buffer.getvalue(), error=traceback.format_exc(limit=-3).strip())
    result = ScriptResult(output=buffer.getvalue())
    for s in namespace.get("new_sounds") or []:
        if isinstance(s, Sound):
            result.sounds.append((s.name, s.samples, s.sampling_rate))
    if isinstance(namespace.get("new_textgrid"), TextGrid):
        result.textgrid = namespace["new_textgrid"]
    return result


EXAMPLES = {
    "Praat: mean pitch and duration": (
        "praat",
        'dur = Get total duration\npitch = To Pitch: 0, 75, 500\nf0 = Get mean: 0, 0, "Hertz"\n'
        'writeInfoLine: "Duration: ", fixed$(dur, 3), " s"\nappendInfoLine: "Mean F0: ", fixed$(f0, 1), " Hz"\n',
    ),
    "Praat: lowpass-filtered copy (form)": (
        "praat",
        "form Low-pass\n    positive Cutoff_(Hz) 1000\nendform\n"
        'Filter (pass Hann band): 0, cutoff, 100\nRename: "lowpass"\n',
    ),
    "Python: formants at each labelled interval": (
        "python",
        "from phonolab.core import analysis, queries\n"
        "f = analysis.compute_formants(sound, analysis.FormantSettings())\n"
        "for tier in (textgrid.tiers if textgrid else []):\n"
        "    for iv in getattr(tier, 'intervals', []):\n"
        "        if iv.text:\n"
        "            st = queries.formant_stats(f, iv.xmin, iv.xmax)\n"
        "            print(tier.name, iv.text, round(st[0].mean), round(st[1].mean))\n",
    ),
    "Python: louder copy": ("python", "new_sounds = [Sound(sound.samples * 2, sound.sampling_rate, title='louder')]\n"),
}
