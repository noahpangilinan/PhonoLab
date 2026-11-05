"""Download the pinned Praat program into packaging/praat (run: uv run python packaging/fetch_praat.py).

PhonoLab bundles it for analyses newer than Parselmouth's Praat. Both programs are GPL;
Praat's source for each version is at https://github.com/praat/praat/releases.
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "7.0.02"
BASE = f"https://github.com/praat/praat/releases/download/v{VERSION}"
ASSETS = {
    "win32": ("praat7002_win-x64v3.zip", "9d1a8e3d0e5232275b697cd3c4076b3c964a086eed062271b637c0a84ff1a76e"),
    "darwin": ("praat7002_mac.dmg", "9e4d1d220cff32ccfa4521114d23c11ebbfd792db61884f6019a44bd4aba19d4"),
}
TARGET = Path(__file__).with_name("praat")


def download(name: str, expected: str, folder: Path) -> Path:
    path = folder / name
    print(f"Downloading {name}…")
    urllib.request.urlretrieve(f"{BASE}/{name}", path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Checksum mismatch for {name}: got {actual}")
    return path


def install_windows(archive: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        z.extract("Praat.exe", TARGET)


def install_mac(image: Path) -> None:
    mount = Path(tempfile.mkdtemp())
    subprocess.run(["hdiutil", "attach", str(image), "-nobrowse", "-mountpoint", str(mount)], check=True)
    try:
        shutil.copytree(mount / "Praat.app", TARGET / "Praat.app", symlinks=True)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True)


def main() -> None:
    if sys.platform not in ASSETS:
        raise SystemExit(f"No pinned Praat build for {sys.platform}")
    shutil.rmtree(TARGET, ignore_errors=True)
    TARGET.mkdir()
    name, checksum = ASSETS[sys.platform]
    with tempfile.TemporaryDirectory() as folder:
        archive = download(name, checksum, Path(folder))
        (install_windows if sys.platform == "win32" else install_mac)(archive)
    print(f"Installed Praat {VERSION} in {TARGET}")


if __name__ == "__main__":
    main()
