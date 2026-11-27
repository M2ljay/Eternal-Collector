"""Filesystem adapter for the shared "now playing" file.

Implements ``services.protocols.NowPlayingStore``. The file lives outside this
plugin's folders so another plugin's backend, a separate process, can read it;
the path is chosen by the composition root.
"""

from __future__ import annotations

import contextlib
import json
import os

# Another plugin may read the file at any moment: it must never see half a
# document, so every write goes to a temporary sibling and is renamed over it.
_TMP_SUFFIX = ".tmp"
_MAX_BYTES = 64 * 1024


class NowPlayingFileAdapter:
    """Synchronous reads and atomic writes of one JSON document."""

    def __init__(self, *, path: str) -> None:
        self._path = path

    def read(self) -> object | None:
        """The decoded document, or ``None`` when absent, oversized or not JSON."""
        try:
            if os.path.getsize(self._path) > _MAX_BYTES:
                return None
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def write(self, document: dict[str, object]) -> None:
        """Replace the file with *document*; the folder is created when missing."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + _TMP_SUFFIX
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(document, f, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise

    def remove(self) -> None:
        """Delete the file (and a leftover temporary one). Idempotent."""
        for path in (self._path, self._path + _TMP_SUFFIX):
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
