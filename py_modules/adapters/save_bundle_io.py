"""Disk side of save bundles: packing a save into its deterministic zip and unpacking one safely.

The layout rules (what a bundle owns, which names are acceptable) live in
:mod:`domain.save_bundles`; this module walks the disk for them, writes the
archive byte-stably, and extracts a server-supplied archive into a staging
folder only after every entry has passed those rules. ``SaveFileAdapter``
exposes these through the ``SaveFileStore`` Protocol.
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from typing import TYPE_CHECKING

from domain.save_bundles import (
    BUNDLE_ENTRY_EPOCH,
    GCI_MEMBERS,
    bundle_entries,
    bundle_entry_name,
    gci_header_matches,
    member_of_entry,
)
from lib.path_safety import PathTraversalError, safe_join

if TYPE_CHECKING:
    from domain.save_bundles import BundleLayout, MemberSource

# Stored, not deflated: zlib's output is not guaranteed identical across zlib
# builds (CPython on Windows bundles its own), and a bundle must be byte-stable
# for one save on every device. Entry attributes are pinned for the same
# reason — ``ZipInfo.create_system`` otherwise follows the host OS.
_BUNDLE_FILE_ATTR = 0o100644 << 16
_BUNDLE_DIR_ATTR = (0o040755 << 16) | 0x10


def _is_regular(path: str) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def _is_real_dir(path: str) -> bool:
    return os.path.isdir(path) and not os.path.islink(path)


def _collect(folder: str, zip_prefix: str) -> tuple[dict[str, str], list[str], float]:
    """Files (entry → path), empty directories and newest mtime of *folder*, entries under *zip_prefix*.

    Symlinks inside the folder are neither followed nor packed. The folder
    itself counts as an empty directory when it is empty and has a prefix.
    """
    files: dict[str, str] = {}
    empty_dirs: list[str] = []
    newest = os.path.getmtime(folder)
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        rel_root = os.path.relpath(root, folder).replace(os.sep, "/")
        prefix = zip_prefix if rel_root == "." else f"{zip_prefix}{rel_root}/"
        regular = [n for n in names if _is_regular(os.path.join(root, n))]
        for name in [*regular, *dirs]:
            newest = max(newest, os.path.getmtime(os.path.join(root, name)))
        files.update({prefix + n: os.path.join(root, n) for n in regular})
        if prefix and not regular and not dirs:
            empty_dirs.append(prefix)
    return files, empty_dirs, newest


def _write_bundle(files: dict[str, str], empty_dirs: list[str], newest: float, bundle_path: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for entry in bundle_entries(list(files), empty_dirs):
            info = zipfile.ZipInfo(entry, date_time=BUNDLE_ENTRY_EPOCH)
            info.create_system = 3
            if entry.endswith("/"):
                info.external_attr = _BUNDLE_DIR_ATTR
                zf.writestr(info, b"")
            else:
                info.external_attr = _BUNDLE_FILE_ATTR
                with open(files[entry], "rb") as f:
                    zf.writestr(info, f.read())
    data = buffer.getvalue()
    if os.path.isfile(bundle_path):
        with open(bundle_path, "rb") as f:
            if f.read() == data:
                return
    tmp = bundle_path + ".pack"
    with open(tmp, "wb") as f:
        f.write(data)
    os.utime(tmp, (newest, newest))
    os.replace(tmp, bundle_path)


def pack_folder(folder: str, bundle_path: str) -> None:
    """Write *folder* as a deterministic zip at *bundle_path* (see ``SaveFileStore.pack_save_folder``)."""
    files, empty_dirs, newest = _collect(folder, "")
    _write_bundle(files, empty_dirs, newest, bundle_path)


def list_members(root: str, layout: BundleLayout) -> list[tuple[str, str]]:
    """Every local entry *layout* owns under *root*, as ``(path relative to root, zip name)``.

    A ``dirs`` member is a real sub-folder (not a symlink) whose name the
    source's pattern fully matches; a ``gci`` member is a regular ``.gci``
    file whose first four bytes are the source's game code. Nothing else in
    the source directory is ever returned.
    """
    members: list[tuple[str, str]] = []
    for source in layout.sources:
        directory = os.path.join(root, *source.directory.split("/"))
        if not os.path.isdir(directory):
            continue
        members.extend(
            (f"{source.directory}/{name}", source.prefix + name)
            for name in sorted(os.listdir(directory))
            if _owns(source, os.path.join(directory, name), name)
        )
    return members


def _owns(source: MemberSource, path: str, name: str) -> bool:
    if not source.owns_name(name):
        return False
    if source.kind == GCI_MEMBERS:
        if not _is_regular(path):
            return False
        with open(path, "rb") as f:
            return gci_header_matches(source, f.read(4))
    return _is_real_dir(path)


def pack_members(root: str, layout: BundleLayout, bundle_path: str) -> bool:
    """Write the members of a member bundle as a deterministic zip; ``False`` (nothing written) when there are none."""
    members = list_members(root, layout)
    if not members:
        return False
    files: dict[str, str] = {}
    empty_dirs: list[str] = []
    newest = 0.0
    for rel, zip_name in members:
        path = os.path.join(root, *rel.split("/"))
        if os.path.isdir(path):
            more_files, more_empty, member_newest = _collect(path, zip_name + "/")
            files.update(more_files)
            empty_dirs.extend(more_empty)
        else:
            files[zip_name] = path
            member_newest = os.path.getmtime(path)
        newest = max(newest, member_newest)
    _write_bundle(files, empty_dirs, newest, bundle_path)
    return True


def _validated_infos(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    seen: set[str] = set()
    for info in infos:
        name = bundle_entry_name(info.filename)
        if name is None or name.rstrip("/") in seen:
            raise PathTraversalError(f"unsafe or duplicate bundle entry: {info.filename!r}")
        seen.add(name.rstrip("/"))
    return infos


def _extract(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], dest_dir: str) -> None:
    os.makedirs(dest_dir)
    try:
        for info in infos:
            target = safe_join(dest_dir, *info.filename.rstrip("/").split("/"))
            if info.filename.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(zf.read(info))
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise


def unpack_folder(bundle_path: str, dest_dir: str) -> None:
    """Extract a folder bundle into the new directory *dest_dir* (see ``SaveFileStore.unpack_save_bundle``)."""
    if os.path.lexists(dest_dir):
        raise FileExistsError(dest_dir)
    with zipfile.ZipFile(bundle_path, "r") as zf:
        _extract(zf, _validated_infos(zf), dest_dir)


def unpack_members(bundle_path: str, dest_dir: str, layout: BundleLayout) -> None:
    """Extract a member bundle into the new directory *dest_dir*, mirroring its zip layout.

    Beyond the entry-name rules, every entry must belong to a member the
    layout owns (:func:`domain.save_bundles.member_of_entry`) and a GCI
    member's own bytes must name the layout's game — so a bundle can never
    place a file the layout would not have packed, and never one of the
    shared files (an emulator's card superblock, ``SRAM.raw``, a file memory
    card) next to the members. Raises :class:`PathTraversalError` before
    anything is written; a failure leaves no *dest_dir*.
    """
    if os.path.lexists(dest_dir):
        raise FileExistsError(dest_dir)
    with zipfile.ZipFile(bundle_path, "r") as zf:
        infos = _validated_infos(zf)
        for info in infos:
            owner = member_of_entry(layout, info.filename)
            if owner is None:
                raise PathTraversalError(f"bundle entry outside the save's members: {info.filename!r}")
            source, _member = owner
            if source.kind == GCI_MEMBERS and (info.is_dir() or not gci_header_matches(source, zf.read(info)[:4])):
                raise PathTraversalError(f"GCI entry of another game: {info.filename!r}")
        _extract(zf, infos, dest_dir)


def move_entry(src: str, dst: str) -> None:
    """Move the file or folder *src* to the not-yet-existing *dst*, across volumes if need be.

    A same-volume move is a rename; across volumes (an emulator folder linked
    in from another drive) it is a copy followed by removing *src*.
    """
    if os.path.lexists(dst):
        raise FileExistsError(dst)
    shutil.move(src, dst)
