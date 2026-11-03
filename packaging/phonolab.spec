# PyInstaller spec: `make package` builds a single dist/PhonoLab.exe (no Python needed).
#
# One-file builds unpack themselves to a temporary folder on each launch, so the first
# window takes a few seconds longer than running from source. Analysis workers are
# child processes of the same exe and reuse that unpacked folder.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("pyqtgraph") + collect_data_files("matplotlib")
binaries = collect_dynamic_libs("parselmouth") + collect_dynamic_libs("av")

a = Analysis(
    ["phonolab_entry.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["parselmouth", "av", "soundfile", "sounddevice"],
    # scipy is only used by the tests; the rest are never imported by the app.
    excludes=["tkinter", "pytest", "IPython", "scipy", "PyInstaller"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PhonoLab",
    console=False,
    icon="phonolab.ico",  # regenerate with: uv run python make_icon.py
    upx=False,
    runtime_tmpdir=None,
)
