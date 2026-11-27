"""Restores files into the installed plugin folder from a kept release zip. Implements ``InstallRepairStore``.

Standard library only (``os``, ``zipfile``): the repair runs before, and
independently of, every other plugin module, because it exists for a folder
in which those are missing or stale.
"""

from __future__ import annotations

import contextlib
import os
import zipfile

from domain.install_manifest import release_zip_name

# The release channel refuses an artifact over 64 MiB (domain/plugin_release.py), so no member can be larger.
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


class InstallRepairFileAdapter:
    """Real ``InstallRepairStore`` over one plugin folder and the self-update's download folder."""

    def __init__(self, plugin_dir: str, download_dir: str) -> None:
        self._root = plugin_dir
        self._download_dir = download_dir

    def cached_release(self, version: str) -> str | None:
        path = os.path.join(self._download_dir, release_zip_name(version))
        return path if os.path.isfile(path) else None

    def read_members(self, archive_path: str, rel_paths: list[str]) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        try:
            with zipfile.ZipFile(archive_path) as zf:
                tops = {name.split("/", 1)[0] for name in zf.namelist()}
                if len(tops) != 1:
                    return {}
                top = tops.pop()
                for rel in rel_paths:
                    try:
                        info = zf.getinfo(f"{top}/{rel}")
                    except KeyError:
                        continue
                    if info.file_size > _MAX_MEMBER_BYTES:
                        continue
                    out[rel] = zf.read(info)
        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
            return {}
        return out

    def write_file(self, rel_path: str, data: bytes) -> None:
        dest = os.path.join(self._root, *rel_path.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".repair-tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
