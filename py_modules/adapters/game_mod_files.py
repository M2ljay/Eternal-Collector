"""Disk side of game mods: listing, installing a planned source, backing up. Implements ``GameModStore``.

Where a mod goes and which entries an install writes are decided in
:mod:`domain.game_mods`; this module only executes those decisions. Every path
it writes or moves is joined below the folder it was handed through
``lib.path_safety.safe_join``, so a name can never reach outside it; nothing is
deleted — what an install replaces and what a removal takes away is moved to
the backup path the caller names.
"""

from __future__ import annotations

import os
import shutil
import stat
import zipfile
from typing import TYPE_CHECKING

from domain.game_mods import InstallOutcome, ModEntryInfo, SourceEntry
from lib.path_safety import PathTraversalError, safe_join, safe_path_component

if TYPE_CHECKING:
    from collections.abc import Callable

    from domain.game_mods import PlannedWrite

_MAX_TEXT_BYTES = 4 * 1024 * 1024
_WALK_LIMIT = 50_000
_COPY_CHUNK = 1024 * 1024
_PART_PREFIX = ".romm-part-"


class GameModFilesAdapter:
    """Real ``GameModStore`` over the local filesystem."""

    def __init__(
        self,
        *,
        downloads_dir: str,
        running_executable_names: Callable[[], frozenset[str] | None],
        open_folder: Callable[[str], None] | None = None,
    ) -> None:
        self._downloads = downloads_dir
        self._running = running_executable_names
        self._open = open_folder if open_folder is not None else getattr(os, "startfile", None)

    # -- reads -------------------------------------------------------------------

    def downloads_folder(self) -> str:
        return self._downloads

    def is_file(self, path: str) -> bool:
        return os.path.isfile(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def load_text(self, path: str) -> str | None:
        try:
            if os.path.getsize(path) > _MAX_TEXT_BYTES:
                return None
            with open(path, "rb") as f:
                return f.read().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None

    def list_folder(self, folder: str, limit: int) -> tuple[list[ModEntryInfo], bool]:
        try:
            names = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            return ([], False)
        entries = [info for name in names[:limit] if (info := _entry_info(folder, name, count=True)) is not None]
        return (entries, len(names) > limit)

    def stat_names(self, folder: str, names: tuple[str, ...]) -> list[ModEntryInfo]:
        return [info for name in names if (info := _entry_info(folder, name, count=False)) is not None]

    def list_sources(self, folder: str, limit: int) -> tuple[list[ModEntryInfo], bool]:
        try:
            names = os.listdir(folder)
        except OSError:
            return ([], False)
        entries = [info for name in names if (info := _entry_info(folder, name, count=False)) is not None]
        entries.sort(key=lambda e: e.modified, reverse=True)
        return (entries[:limit], len(entries) > limit)

    def source_path(self, name: str) -> str | None:
        path = _child(self._downloads, name)
        if path is None or os.path.islink(path) or not os.path.lexists(path):
            return None
        return path

    def source_stamp(self, path: str) -> str | None:
        try:
            st = os.stat(path)
        except OSError:
            return None
        if not stat.S_ISDIR(st.st_mode):
            return f"{path}|{st.st_size}|{st.st_mtime_ns}"
        newest, count, total = st.st_mtime_ns, 0, 0
        for root, dirs, files in os.walk(path):
            for name in [*dirs, *files]:
                try:
                    child = os.lstat(os.path.join(root, name))
                except OSError:
                    continue
                newest = max(newest, child.st_mtime_ns)
                count += 1
                total += child.st_size if stat.S_ISREG(child.st_mode) else 0
        return f"{path}|dir|{count}|{total}|{newest}"

    def read_source_entries(self, path: str) -> list[SourceEntry]:
        if os.path.isdir(path):
            return _folder_entries(path)
        if path.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as zf:
                    return [_zip_entry(info) for info in zf.infolist()]
            except zipfile.BadZipFile as exc:
                raise ValueError(f"not a readable zip archive: {exc}") from exc
        return [SourceEntry(os.path.basename(path), False, os.path.getsize(path))]

    def probe_kinds(self, root: str, rel_paths: tuple[str, ...]) -> dict[str, str]:
        kinds: dict[str, str] = {}
        for rel in rel_paths:
            try:
                path = safe_join(root, *rel.split("/"))
                st = os.lstat(path)
            except PathTraversalError:
                kinds[rel] = "other"
                continue
            except OSError:
                kinds[rel] = "missing"
                continue
            if stat.S_ISREG(st.st_mode):
                kinds[rel] = "file"
            elif stat.S_ISDIR(st.st_mode):
                kinds[rel] = "dir"
            else:
                kinds[rel] = "other"
        return kinds

    def running_executable_names(self) -> frozenset[str] | None:
        return self._running()

    # -- writes ------------------------------------------------------------------

    def install(
        self, source: str, root: str, writes: tuple[PlannedWrite, ...], replaces: frozenset[str], backup: str
    ) -> InstallOutcome:
        written = backed_up = 0
        try:
            os.makedirs(root, exist_ok=True)
            for rel in sorted(replaces):
                self._move(safe_join(root, *rel.split("/")), os.path.join(backup, *rel.split("/")))
                backed_up += 1
            if os.path.isdir(source):
                for write in writes:
                    src = safe_join(os.path.dirname(source), *write.source.split("/"))
                    if os.path.islink(src) or not os.path.isfile(src):
                        raise OSError(f"{write.source} is no longer a plain file")
                    with open(src, "rb") as f:
                        _write_file(f, root, write)
                    written += 1
            elif source.lower().endswith(".zip"):
                with zipfile.ZipFile(source) as zf:
                    for write in writes:
                        with zf.open(write.source) as f:
                            _write_file(f, root, write)
                        written += 1
            else:
                for write in writes:
                    with open(source, "rb") as f:
                        _write_file(f, root, write)
                    written += 1
        except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
            return InstallOutcome(written, backed_up, str(exc))
        return InstallOutcome(written, backed_up)

    def move_to_backup(self, root: str, name: str, backup: str) -> None:
        path = _child(root, name) if name else root
        if path is None:
            raise PathTraversalError(f"not a plain entry name: {name!r}")
        self._move(path, backup)

    def replace_text(self, path: str, expected: str, new_text: str, backup: str) -> bool:
        with open(path, "rb") as f:
            raw = f.read()
        bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
        if raw[len(bom) :].decode("utf-8") != expected:
            return False
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        if os.path.lexists(backup):
            raise FileExistsError(backup)
        shutil.copy2(path, backup)
        tmp = os.path.join(os.path.dirname(path), _PART_PREFIX + os.path.basename(path))
        with open(tmp, "wb") as f:
            f.write(bom + new_text.encode("utf-8"))
        os.replace(tmp, path)
        return True

    def open_folder(self, path: str) -> bool:
        if self._open is None or not os.path.isdir(path):
            return False
        try:
            self._open(path)
        except OSError:
            return False
        return True

    @staticmethod
    def _move(src: str, dst: str) -> None:
        if os.path.lexists(dst):
            raise FileExistsError(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)


def _child(folder: str, name: str) -> str | None:
    """*folder*'s direct child *name* (not resolved through links), or ``None`` for anything but a plain name."""
    try:
        safe_path_component(name)
    except PathTraversalError:
        return None
    if ":" in name or "/" in name or "\\" in name:
        return None
    return os.path.join(folder, name)


def _entry_info(folder: str, name: str, *, count: bool) -> ModEntryInfo | None:
    path = os.path.join(folder, name)
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
        return ModEntryInfo(name, os.path.isdir(path), None, st.st_mtime)
    if not stat.S_ISDIR(st.st_mode):
        return ModEntryInfo(name, False, st.st_size, st.st_mtime, files=1)
    if not count:
        return ModEntryInfo(name, True, None, st.st_mtime)
    size, files, newest, partial = _folder_totals(path, st.st_mtime)
    return ModEntryInfo(name, True, size, newest, files=files, partial=partial)


def _folder_totals(path: str, mtime: float) -> tuple[int, int, float, bool]:
    size = files = 0
    newest = mtime
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in names:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                size += st.st_size
                files += 1
                newest = max(newest, st.st_mtime)
            if files >= _WALK_LIMIT:
                return (size, files, newest, True)
    return (size, files, newest, False)


def _folder_entries(path: str) -> list[SourceEntry]:
    """Every file and folder below *path*, named ``<folder>/<relative path>``; links are reported, never entered."""
    top = os.path.basename(os.path.normpath(path))
    entries = [SourceEntry(top + "/", True, 0)]
    for root, dirs, names in os.walk(path):
        rel_root = os.path.relpath(root, path).replace(os.sep, "/")
        prefix = top if rel_root == "." else f"{top}/{rel_root}"
        for name in list(dirs):
            if os.path.islink(os.path.join(root, name)):
                dirs.remove(name)
                entries.append(SourceEntry(f"{prefix}/{name}", False, 0, link=True))
            else:
                entries.append(SourceEntry(f"{prefix}/{name}/", True, 0))
        for name in names:
            full = os.path.join(root, name)
            st = os.lstat(full)
            entries.append(SourceEntry(f"{prefix}/{name}", False, st.st_size, link=not stat.S_ISREG(st.st_mode)))
    return entries


def _zip_entry(info: zipfile.ZipInfo) -> SourceEntry:
    mode = info.external_attr >> 16
    return SourceEntry(info.filename, info.is_dir(), info.file_size, link=stat.S_ISLNK(mode))


def _write_file(f, root: str, write: PlannedWrite) -> None:
    """Copy at most the planned size from *f* to the planned destination below *root*, via a part file."""
    dest = safe_join(root, *write.dest.split("/"))
    if os.path.lexists(dest):
        raise FileExistsError(f"{dest} appeared after it was backed up")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = os.path.join(os.path.dirname(dest), _PART_PREFIX + os.path.basename(dest))
    remaining = write.size
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = f.read(min(_COPY_CHUNK, remaining + 1))
                if not chunk:
                    break
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError(f"{write.source} is larger than it claims")
                out.write(chunk)
        if remaining != 0:
            raise ValueError(f"{write.source} is shorter than it claims")
        os.replace(tmp, dest)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise
