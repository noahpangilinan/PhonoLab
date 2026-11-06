"""Download the real recordings the tests use into tests/recordings (not kept in git).

    python tests/fetch_recordings.py

Each file is checked against its SHA-256 in recordings.json. The recordings are kept out of the repository
because not all of them may be redistributed: CMU ARCTIC can, but the terms of LDC's TIMIT sample aren't
published, so it's only ever fetched from LDC. See tests/recordings.json for where each one comes from.

``--update`` writes hashes for new entries, for use when adding a recording.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
FOLDER = HERE / "recordings"
MANIFEST = HERE / "recordings.json"
HEADERS = {"User-Agent": "phonolab-tests"}


def _get(url: str, byte_range: tuple[int, int] | None = None) -> bytes:
    headers = dict(HEADERS)
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return response.read()


class _RemoteFile(io.RawIOBase):
    """A file on a web server, read with range requests, so one entry can come out of a large zip."""

    def __init__(self, url: str):
        self.url, self.position = url, 0
        request = urllib.request.Request(url, headers=HEADERS, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            self.size = int(response.headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = base + offset
        return self.position

    def readinto(self, buffer):
        n = min(len(buffer), self.size - self.position)
        if n <= 0:
            return 0
        data = _get(self.url, (self.position, self.position + n - 1))
        buffer[: len(data)] = data
        self.position += len(data)
        return len(data)


def _download(entry: dict) -> bytes:
    if "member" not in entry:
        return _get(entry["url"])
    buffered = io.BufferedReader(_RemoteFile(entry["url"]), buffer_size=1 << 20)
    with zipfile.ZipFile(buffered) as archive:
        name = next(n for n in archive.namelist() if n.endswith(entry["member"]))
        return archive.read(name)


def fetch(update: bool = False) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    FOLDER.mkdir(exist_ok=True)
    problems = 0
    for name, entry in manifest["files"].items():
        path = FOLDER / name
        path.parent.mkdir(parents=True, exist_ok=True)
        wanted = entry.get("sha256")
        if path.exists() and wanted and hashlib.sha256(path.read_bytes()).hexdigest() == wanted:
            continue
        try:
            data = _download(entry)
        except Exception as e:  # any network failure: carry on, and the tests needing this file skip
            print(f"could not fetch {name}: {e}")
            problems += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        if wanted and digest != wanted:
            print(f"{name} doesn't match its checksum, so it was not kept")
            problems += 1
            continue
        path.write_bytes(data)
        entry["sha256"] = digest
        print(f"fetched {name} ({len(data) / 1024:.0f} kB)")
    if update:
        MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return problems


if __name__ == "__main__":
    sys.exit(1 if fetch("--update" in sys.argv) else 0)
