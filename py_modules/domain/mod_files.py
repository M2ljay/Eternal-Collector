"""The plain shapes game-mod installs are described in: source entries, planned writes, listings, outcomes.

Shared by :mod:`domain.game_mods` (which re-exports them), the ``GameModStore``
adapter and the services; nothing here decides anything.

No I/O. Pure data only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceEntry:
    """One entry of an install source: an archive member, or a file/folder below a picked folder.

    ``name`` is ``/``-separated and relative; a folder source's entries start
    with the folder's own name. ``link`` marks a symbolic link, which is never
    installed.
    """

    name: str
    is_dir: bool
    size: int
    link: bool = False


@dataclass(frozen=True)
class PlannedWrite:
    """One file an install writes: from source entry ``source`` to ``dest`` (``/``-relative to the target)."""

    source: str
    dest: str
    size: int


@dataclass(frozen=True)
class ModEntryInfo:
    """One file or folder found in a mod folder or a Downloads folder.

    ``size`` and ``files`` are totals over a folder's contents (``None`` when
    not counted); ``partial`` marks a folder whose count stopped at the walk
    limit. ``modified`` is seconds since the epoch.
    """

    name: str
    is_dir: bool
    size: int | None
    modified: float
    files: int | None = None
    partial: bool = False


@dataclass(frozen=True)
class InstallOutcome:
    """What an install did: files written, files moved to the backup, and the error that stopped it, if any."""

    written: int
    backed_up: int
    error: str | None = None
