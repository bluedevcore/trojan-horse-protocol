"""Tiny JSON-on-disk cache keyed by a hash of the request."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def stable_hash(payload: Any) -> str:
    """SHA-256 of a JSON-serialisable payload, independent of dict ordering."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: str | os.PathLike):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # corrupt entry: treat as a miss

    def set(self, key: str, value: dict) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Write atomically so a crash never leaves half a file behind.
            fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(value, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path(key))
        except OSError:
            pass  # a read-only filesystem must never break the demo
