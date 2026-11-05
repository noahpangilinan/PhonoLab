# PyInstaller spec: `make package` builds dist/PhonoLab.exe on Windows and dist/PhonoLab.app on macOS.
#
# Windows gets one file, which unpacks itself to a temporary folder on each launch; analysis
# workers are child processes of the same exe and reuse that folder. macOS gets a normal
# app bundle. PyInstaller can't cross-compile, so build on the platform you want to ship to.
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

VERSION = re.search(r'__version__ = "([^"]+)"', Path("../src/phonolab/__init__.py").read_text()).group(1)

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

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PhonoLab", console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="PhonoLab", upx=False)
    app = BUNDLE(
        coll,
        name="PhonoLab.app",
        icon="phonolab.icns",  # regenerate with: uv run python make_icon.py
        bundle_identifier="io.github.noahpangilinan.phonolab",
        version=VERSION,
        info_plist={
            "CFBundleName": "PhonoLab",
            "CFBundleDisplayName": "PhonoLab",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            # Without this, macOS refuses the app microphone access and recording fails.
            "NSMicrophoneUsageDescription": "PhonoLab records speech from your microphone when you choose Record.",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Sound file",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                    "CFBundleTypeExtensions": ["wav", "flac", "aiff", "aif", "ogg", "opus", "mp3", "m4a", "aac"],
                },
                {
                    "CFBundleTypeName": "Praat TextGrid",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "CFBundleTypeExtensions": ["TextGrid"],
                },
            ],
        },
    )
else:
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
