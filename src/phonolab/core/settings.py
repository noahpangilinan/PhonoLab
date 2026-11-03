"""User preferences: analysis settings, visible panes and recent files.

The backing store only needs ``value(key, default)`` and ``setValue(key, value)``,
so the UI passes a ``QSettings`` while tests can pass a :class:`MemoryStore`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from phonolab.core.analysis import settings_from_dict, settings_to_dict
from phonolab.core.registry import ANALYSES

MAX_RECENT = 10


class Store(Protocol):
    def value(self, key: str, default=None): ...
    def setValue(self, key: str, value) -> None: ...  # noqa: N802 - Qt naming


class MemoryStore:
    def __init__(self):
        self.data = {}

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self.data[key] = value


class Preferences:
    def __init__(self, store: Store):
        self.store = store

    def _json(self, key: str, default):
        raw = self.store.value(key, None)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    def analysis_settings(self, name: str, cls=None):
        """Saved settings for ``name``; ``cls`` is needed for settings outside the analysis registry."""
        cls = cls or ANALYSES[name][0]
        return settings_from_dict(cls, self._json(f"analysis/{name}", {}))

    def set_analysis_settings(self, name: str, settings) -> None:
        self.store.setValue(f"analysis/{name}", json.dumps(settings_to_dict(settings)))

    def pane_visible(self, name: str, default: bool = True) -> bool:
        return bool(self._json(f"view/{name}", default))

    def set_pane_visible(self, name: str, visible: bool) -> None:
        self.store.setValue(f"view/{name}", json.dumps(bool(visible)))

    def theme(self) -> str:
        """'system', 'light' or 'dark'."""
        value = self._json("view/theme", "system")
        return value if value in ("system", "light", "dark") else "system"

    def set_theme(self, theme: str) -> None:
        self.store.setValue("view/theme", json.dumps(theme))

    def recent_files(self) -> list[str]:
        return [p for p in self._json("recent", []) if isinstance(p, str)]

    def add_recent_file(self, path: str | Path) -> None:
        path = str(Path(path).resolve())
        recent = [p for p in self.recent_files() if p != path]
        recent.insert(0, path)
        self.store.setValue("recent", json.dumps(recent[:MAX_RECENT]))

    def clear_recent_files(self) -> None:
        self.store.setValue("recent", json.dumps([]))
