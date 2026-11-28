"""Reads the user's own icon pack from ``%APPDATA%\\GamingMode\\icons\\colorgrade``.

The pack is personal art that lives only on the user's PC; this adapter reads it
and never writes, copies or caches it. With no ``APPDATA`` (any platform but
Windows) there is no pack, and every read answers ``None``.
"""

from __future__ import annotations

import os

from domain.icon_pack import PACK_ROOT_PARTS
from lib.path_safety import PathTraversalError, safe_join


class IconPackFilesAdapter:
    """``IconPackStore`` over the pack folder under the user's roaming AppData."""

    def __init__(self, *, appdata: str | None) -> None:
        self._root = os.path.join(appdata, *PACK_ROOT_PARTS) if appdata else None

    def read_art(self, parts: tuple[str, ...], limit: int) -> bytes | None:
        """The file at *parts* under the pack, or ``None`` when absent, unreadable or larger than *limit*."""
        if self._root is None or not os.path.isdir(self._root):
            return None
        try:
            path = safe_join(self._root, *parts)
        except PathTraversalError:
            return None
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > limit:
                return None
            with open(path, "rb") as handle:
                data = handle.read(limit + 1)
        except OSError:
            return None
        return data if len(data) <= limit else None
