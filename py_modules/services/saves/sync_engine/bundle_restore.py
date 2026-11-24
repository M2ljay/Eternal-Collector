"""Staging a downloaded bundle, putting it in place, and finding a bundled save's local entries.

A bundle is a save that is a folder, or a set of entries in directories other
games share, travelling as one zip (:mod:`domain.save_bundles`). These are the
steps of the download and quarantine paths that differ for one; when to back
up, where backups go and how many are kept stay with
``MatrixExecutor.quarantine_local_file``, the one backup funnel. Every step
goes through the ``SaveFileStore``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.save_bundles import BundleLayout
    from services.protocols import SaveFileStore


def _join(base: str, relative: str) -> str:
    return os.path.join(base, *[p for p in relative.split("/") if p])


def staging_path(saves_dir: str, layout: BundleLayout) -> str:
    """The hidden folder a downloaded bundle is unpacked into before anything local is touched."""
    return os.path.join(saves_dir, f".{layout.label}.romm-unpack")


def stage(store: SaveFileStore, saves_dir: str, layout: BundleLayout, bundle_path: str) -> str:
    """Unpack *bundle_path* into a fresh staging folder and return it; raises before touching any save."""
    staging = staging_path(saves_dir, layout)
    if store.is_dir(staging):
        store.remove_tree(staging, saves_dir)
    if layout.is_folder:
        store.unpack_save_bundle(bundle_path, staging)
    else:
        store.unpack_member_bundle(bundle_path, staging, layout)
    return staging


def discard(store: SaveFileStore, saves_dir: str, staging: str) -> None:
    """Remove a staging folder left by a download that did not complete."""
    if store.is_dir(staging):
        store.remove_tree(staging, saves_dir)


def install(store: SaveFileStore, saves_dir: str, layout: BundleLayout, staging: str) -> None:
    """Move a staged bundle into place. The save's previous local entries must already be quarantined.

    A folder bundle becomes the layout's folder. A member bundle's members go
    one by one into their source directories, and only names the layout owns
    are moved — the staging folder holds nothing else, because unpacking
    refused any other entry.
    """
    if layout.folder is not None:
        target = _join(saves_dir, layout.folder)
        store.make_dirs(os.path.dirname(target))
        store.move_entry(staging, target)
        return
    for source in layout.sources:
        staged_dir = _join(staging, source.prefix)
        target_dir = _join(saves_dir, source.directory)
        for name in sorted(store.listdir(staged_dir)):
            if not source.owns_name(name):
                continue
            store.make_dirs(target_dir)
            store.move_entry(os.path.join(staged_dir, name), os.path.join(target_dir, name))
    store.remove_tree(staging, saves_dir)


def local_entries(store: SaveFileStore, saves_dir: str, layout: BundleLayout) -> list[tuple[str, str]]:
    """The bundled save's current local entries, as ``(path, path inside its backup)``.

    A folder bundle's one entry is its folder (``""`` inside the backup: the
    folder becomes the backup); a symlinked folder is not treated as the save.
    A member bundle's entries are the members the layout owns, filed in the
    backup under their zip names.
    """
    if layout.folder is not None:
        folder = _join(saves_dir, layout.folder)
        if store.is_dir(folder) and not store.is_symlink(folder):
            return [(folder, "")]
        return []
    return [(_join(saves_dir, rel), zip_name) for rel, zip_name in store.list_bundle_members(saves_dir, layout)]


def move_aside(store: SaveFileStore, entries: list[tuple[str, str]], backup: str) -> None:
    """Move every entry of :func:`local_entries` into the backup folder *backup*."""
    for path, inner in entries:
        target = _join(backup, inner) if inner else backup
        store.make_dirs(os.path.dirname(target))
        store.move_entry(path, target)
