# SPDX-License-Identifier: AGPL-3.0-only
"""Per-user settings (last folders, window size) kept only on this PC.

Stored in %APPDATA%\\PDF-Moa\\settings.json. PDF_MOA_SETTINGS overrides the
path (tests use it so they never touch the real file). No document content
is stored, and a missing or broken file simply means default settings.
"""
import json
import os
from pathlib import Path


def default_path():
    override = os.environ.get('PDF_MOA_SETTINGS')
    if override:
        return Path(override)
    base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
    return Path(base) / 'PDF-Moa' / 'settings.json'


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def folder(self, key):
        """The remembered folder if it still exists, else None."""
        value = self.data.get(key)
        return value if isinstance(value, str) and os.path.isdir(value) else None

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, self.path)
        except OSError:
            pass
