"""Reads the installed plugin folder for the install-integrity check. Implements ``InstallFileScanner``.

Standard library only (``os``, ``hashlib``): the check runs before, and
independently of, every other plugin module, so it must load in a folder
where those are missing or stale.
"""

from __future__ import annotations

import hashlib
import os

_SKIPPED_DIRS = frozenset({"__pycache__"})


class InstallFileAdapter:
    """Real ``InstallFileScanner`` over one plugin folder."""

    def __init__(self, plugin_dir: str) -> None:
        self._root = plugin_dir

    def read_file(self, rel_path: str) -> bytes | None:
        try:
            with open(self._abs(rel_path), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def sizes(self, rel_paths: list[str]) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        for rel in rel_paths:
            try:
                st = os.stat(self._abs(rel))
            except OSError:
                out[rel] = None
                continue
            out[rel] = st.st_size if os.path.isfile(self._abs(rel)) else None
        return out

    def python_tree(self, rel_root: str) -> tuple[frozenset[str], frozenset[str]]:
        files: set[str] = set()
        dirs: set[str] = set()
        top = self._abs(rel_root)
        for root, subdirs, names in os.walk(top):
            subdirs[:] = [d for d in subdirs if d not in _SKIPPED_DIRS]
            rel_dir = os.path.relpath(root, self._root).replace(os.sep, "/")
            for d in subdirs:
                dirs.add(f"{rel_dir}/{d}")
            for name in names:
                if name.endswith(".py"):
                    files.add(f"{rel_dir}/{name}")
        return frozenset(files), frozenset(dirs)

    def sha256(self, rel_path: str) -> str | None:
        digest = hashlib.sha256()
        try:
            with open(self._abs(rel_path), "rb") as f:
                for chunk in iter(lambda: f.read(256 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def _abs(self, rel_path: str) -> str:
        return os.path.join(self._root, *rel_path.split("/"))
