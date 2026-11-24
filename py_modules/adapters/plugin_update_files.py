"""Filesystem adapter for the plugin self-update's staging folder (``PluginUpdateFileStore``)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile

_SKIPPED_DIRS = {"__pycache__"}
_SKIPPED_SUFFIXES = (".pyc", ".log")
# A fixed timestamp keeps a snapshot of unchanged files byte-identical.
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def _sha256_file(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


class PluginUpdateFileAdapter:
    """Real ``PluginUpdateFileStore`` on the local filesystem."""

    def ensure_dir(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def read_json(self, path: str) -> dict[str, object] | None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def write_json(self, path: str, data: dict[str, object]) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def remove(self, path: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)

    def digest(self, path: str) -> tuple[int, str] | None:
        try:
            return _sha256_file(path)
        except OSError:
            return None

    def archive_folder(self, source_dir: str, top_folder: str, dest_path: str) -> tuple[int, str]:
        tmp = dest_path + ".part"
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(source_dir):
                    dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)
                    rel_root = os.path.relpath(root, source_dir)
                    for name in sorted(files):
                        if name.endswith(_SKIPPED_SUFFIXES):
                            continue
                        rel = name if rel_root == "." else os.path.join(rel_root, name)
                        arcname = "/".join([top_folder, *rel.split(os.sep)])
                        info = zipfile.ZipInfo(arcname, date_time=_ZIP_DATE)
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.external_attr = (os.stat(os.path.join(root, name)).st_mode & 0o777) << 16
                        with open(os.path.join(root, name), "rb") as src, zf.open(info, "w") as dst:
                            for chunk in iter(lambda: src.read(64 * 1024), b""):
                                dst.write(chunk)
            os.replace(tmp, dest_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise
        return _sha256_file(dest_path)
