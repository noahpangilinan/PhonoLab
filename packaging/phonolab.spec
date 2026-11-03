# PyInstaller spec: `make package` builds dist/PhonoLab/ (a folder app; faster start-up than one-file).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("pyqtgraph") + collect_data_files("matplotlib")
binaries = collect_dynamic_libs("parselmouth") + collect_dynamic_libs("av")

a = Analysis(
    ["phonolab_entry.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["parselmouth", "av", "soundfile", "sounddevice", "scipy.signal"],
    excludes=["tkinter", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhonoLab",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PhonoLab")
