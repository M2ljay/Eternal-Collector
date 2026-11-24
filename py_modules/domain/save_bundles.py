"""Saves that are not one file, carried as one zip (a *bundle*), and which local entries a bundle owns.

A bundle has one of two shapes. A **folder bundle** is a single folder that is
the save (Vita3K's title folder, a Wii title's ``data`` folder): its entries
are that folder's contents, and a restore replaces the folder. A **member
bundle** is a game's share of directories other games use too (PPSSPP's
``SAVEDATA``, a PCSX2 folder memory card, Dolphin's GCI folders): it owns only
the entries its :class:`MemberSource` rules select, carries each under the
source's prefix, and a restore touches those entries and nothing else.

This module owns the layout description, the entry-name rules every
extraction is checked against first, and the deterministic entry order. All
paths are relative and ``/``-separated; the adapter maps them onto the disk.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

DIR_MEMBERS = "dirs"
"""A member is a sub-folder whose name fully matches the source's pattern."""
GCI_MEMBERS = "gci"
"""A member is a ``.gci`` file whose header names the source's game code."""

BUNDLE_ENTRY_EPOCH = (1980, 1, 1, 0, 0, 0)
"""The timestamp every bundle entry carries — the earliest a zip can record —
so the archive's bytes depend on the save's names and contents alone."""


@dataclass(frozen=True)
class MemberSource:
    """One directory a member bundle draws entries from.

    ``directory`` is relative to the save set's root; ``prefix`` is what the
    source's members are filed under inside the zip (``""`` or ``"Card A/"``);
    ``pattern`` is a regular expression a member folder's name must fully
    match (``dirs``) or the 4-character game code a GCI header must carry
    (``gci``).
    """

    directory: str
    prefix: str
    kind: str
    pattern: str

    def owns_name(self, name: str) -> bool:
        """Whether a top-level entry called *name* can be a member (name rules only)."""
        if safe_component(name) is None:
            return False
        if self.kind == DIR_MEMBERS:
            return re.fullmatch(self.pattern, name) is not None
        return name.lower().endswith(".gci") and len(name) > 4


@dataclass(frozen=True)
class BundleLayout:
    """Where a bundle's entries live, relative to the save set's root.

    Exactly one of ``folder`` (a folder bundle) or ``sources`` (a member
    bundle) is set. ``label`` names the bundle's backups in ``.romm-backup``.
    """

    label: str
    folder: str | None = None
    sources: tuple[MemberSource, ...] = ()

    @property
    def is_folder(self) -> bool:
        return self.folder is not None


def safe_component(name: str) -> str | None:
    """*name* when it is one plain path component (no separator, colon, NUL, ``.`` or ``..``), else ``None``."""
    if not name or name in (".", "..") or any(c in name for c in "/\\:\x00"):
        return None
    return name


def bundle_entry_name(name: str) -> str | None:
    """A zip entry name, validated for extraction under a save folder, or ``None``.

    Accepts only a relative ``/``-separated path whose every component is a
    plain name: no absolute path, no drive letter or colon, no backslash, no
    ``.`` / ``..`` component, no NUL. A directory entry keeps its trailing
    ``/``. The adapter additionally confines every extracted path with
    ``lib.path_safety.safe_join``; this is the lexical first line.
    """
    if not name or "\x00" in name or "\\" in name or ":" in name or name.startswith("/"):
        return None
    is_dir = name.endswith("/")
    parts = name.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    normalized = posixpath.normpath(name.rstrip("/"))
    if normalized != name.rstrip("/"):
        return None
    return normalized + "/" if is_dir else normalized


def bundle_entries(files: list[str], empty_dirs: list[str]) -> list[str]:
    """The entry names of a bundle, in the one order every device writes them.

    *files* and *empty_dirs* are paths relative to the bundle root, ``/``-
    separated. Only an empty directory gets an entry of its own (with a
    trailing ``/``); every other directory is implied by the files inside it.
    Sorted, so the same save always yields the same archive.
    """
    return sorted([*files, *(d.rstrip("/") + "/" for d in empty_dirs)])


def member_of_entry(layout: BundleLayout, entry: str) -> tuple[MemberSource, str] | None:
    """The source and member a member bundle's zip *entry* belongs to, or ``None``.

    *entry* must already be a valid :func:`bundle_entry_name`. A ``gci``
    member is a file directly under its prefix; a ``dirs`` member is the
    folder an entry sits in (or the folder's own directory entry) — a loose
    file next to the member folders belongs to nothing. Anything that belongs
    to nothing must make the whole bundle unusable: it would otherwise land
    in a directory other games share.
    """
    for source in layout.sources:
        if not entry.startswith(source.prefix):
            continue
        rest = entry[len(source.prefix) :]
        member, sep, _ = rest.partition("/")
        if not source.owns_name(member):
            continue
        if source.kind == GCI_MEMBERS and not sep:
            return source, member
        if source.kind == DIR_MEMBERS and sep:
            return source, member
    return None


def gci_header_matches(source: MemberSource, header: bytes) -> bool:
    """Whether a GCI file starting with *header* is a save of *source*'s game."""
    return source.kind == GCI_MEMBERS and header[:4] == source.pattern.encode("ascii")
