"""Exact per-game save sets of standalone emulators, and how server saves map onto them.

A standalone emulator's save for one game is a small, fixed set of names
derived from the ROM alone — never a directory scan, never a pattern match.
This module owns that derivation, the mapping of a RomM save record back onto
one of those names, and the naming and entry rules of a folder save travelling
as one zip (a *bundle*). Which emulator a ROM launches with, and where that
emulator keeps its saves on disk, are answered elsewhere (the active-core seam
and the launcher backend); everything here is pure.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.vita_app import is_title_id

if TYPE_CHECKING:
    from collections.abc import Mapping

MELONDS = "melonds"
DUCKSTATION = "duckstation"
VITA3K = "vita3k"

STANDALONE_EMULATOR_TAGS: frozenset[str] = frozenset({MELONDS, DUCKSTATION, VITA3K})
"""RomM ``emulator`` tags written by standalone save sync — each emulator's own id.

A RetroArch save set never claims a save carrying one of these tags, and a
standalone save set claims only its own, so saves from two emulators never
resolve onto the same local file.
"""

# Lower-cased executable-name prefixes, as EmuDeck for Windows installs them:
# ``melonDS.exe``, ``duckstation-qt-x64-ReleaseLTCG.exe``, ``Vita3K.exe``.
_EXE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("melonds", MELONDS),
    ("duckstation", DUCKSTATION),
    ("vita3k", VITA3K),
)

_QUOTED_RE = re.compile(r'"([^"]+)"')

BUNDLE_SUFFIX = ".vita3k.zip"
_BUNDLE_RE = re.compile(r"^([A-Z]{4}\d{5})\.vita3k\.zip$")

BUNDLE_ENTRY_EPOCH = (1980, 1, 1, 0, 0, 0)
"""The timestamp every bundle entry carries — the earliest a zip can record —
so the archive's bytes depend on the folder's names and contents alone."""

# RomM stamps a save uploaded into a slot with the upload time, e.g.
# ``Game [2026-03-24_15-18-50].srm`` (docs/architecture/save-file-sync-architecture.md,
# "RomM Save API"). Stripped wherever it sits, because where RomM splits a
# multi-dot name such as ``PCSE01274.vita3k.zip`` is not pinned down.
_ROMM_TIMESTAMP_TAG_RE = re.compile(r" \[\d{4}-\d{2}-\d{2}[ _T][\d\-:.]+\]")


@dataclass(frozen=True)
class SaveSetEntry:
    """One file of a standalone save set.

    ``filename`` is the name the sync tracks, uploads and downloads. When
    ``bundle_dir`` is set the real save is the folder of that name beside it,
    and ``filename`` is the zip that folder travels as.
    """

    filename: str
    bundle_dir: str | None = None


@dataclass(frozen=True)
class StandaloneSaveSet:
    """A ROM's complete save set under one standalone emulator."""

    emulator_tag: str
    entries: tuple[SaveSetEntry, ...]

    @property
    def filenames(self) -> tuple[str, ...]:
        """Every tracked filename of the set, in set order."""
        return tuple(entry.filename for entry in self.entries)


def identify_standalone_emulator(command: str | None) -> str | None:
    """The standalone emulator a baked launch command runs, or ``None``.

    Reads the first double-quoted path in *command* — the emulator executable
    in EmuDeck for Windows' baked form (``"C:\\...\\melonDS.exe" ...``, or
    ``--title-id-file "C:\\...\\Vita3K.exe" -F -r``) — and matches its file
    name against the emulators this module knows. A command with no quoted
    executable (RetroDECK's ``%EMULATOR_MELONDS% %ROM%`` form) answers ``None``.
    """
    if not command:
        return None
    match = _QUOTED_RE.search(command)
    if match is None:
        return None
    exe = re.split(r"[\\/]", match.group(1))[-1].lower()
    for prefix, emulator_id in _EXE_PREFIXES:
        if exe.startswith(prefix):
            return emulator_id
    return None


def standalone_save_set(emulator_id: str, rom_name: str) -> StandaloneSaveSet | None:
    """The exact save set for the ROM whose file stem is *rom_name*, or ``None``.

    - melonDS: ``<rom_name>.sav``.
    - DuckStation: the per-game cards ``<rom_name>_1.mcd`` and ``<rom_name>_2.mcd``.
      DuckStation names them after its game-database title, which is not always
      the ROM stem; a card under any other name is simply not in the set.
    - Vita3K: the ``<TITLE_ID>`` save folder, bundled as ``<TITLE_ID>.vita3k.zip``.
      *rom_name* must itself be a title ID (the ``<TITLE_ID>.psvita`` launch
      file); anything else has no identifiable save and answers ``None``.
    """
    if not rom_name:
        return None
    if emulator_id == MELONDS:
        return StandaloneSaveSet(MELONDS, (SaveSetEntry(f"{rom_name}.sav"),))
    if emulator_id == DUCKSTATION:
        return StandaloneSaveSet(DUCKSTATION, (SaveSetEntry(f"{rom_name}_1.mcd"), SaveSetEntry(f"{rom_name}_2.mcd")))
    if emulator_id == VITA3K and is_title_id(rom_name):
        return StandaloneSaveSet(VITA3K, (SaveSetEntry(f"{rom_name}{BUNDLE_SUFFIX}", bundle_dir=rom_name),))
    return None


def bundle_dir_for(filename: str) -> str | None:
    """The save folder a bundle filename stands for (``PCSE01274.vita3k.zip`` → ``PCSE01274``)."""
    match = _BUNDLE_RE.match(filename)
    return match.group(1) if match else None


def strip_romm_timestamp_tag(file_name: str) -> str:
    """*file_name* without the ``[YYYY-MM-DD_HH-MM-SS]`` tag RomM adds on a slotted upload."""
    return _ROMM_TIMESTAMP_TAG_RE.sub("", file_name, count=1)


def standalone_target_for(
    server_save: Mapping[str, Any],
    save_set: StandaloneSaveSet,
    tracked: Mapping[int, str] | None = None,
) -> str | None:
    """The save-set filename a RomM save record belongs to, or ``None``.

    A record belongs only when its ``emulator`` tag is the set's own, and then
    only by an exact name: its ``file_name`` with RomM's timestamp tag removed,
    or ``file_name_no_tags`` plus ``file_extension``, must equal one of the
    set's filenames. *tracked* (save id → filename, from the ROM's sync
    baselines) is the fallback for a record this device uploaded itself: it
    keeps the record mapped even if RomM's renaming ever stops matching the
    rule above. Server-supplied names only ever select among the set's own
    names, so no path a server sends can reach the filesystem.
    """
    if server_save.get("emulator") != save_set.emulator_tag:
        return None
    names = set(save_set.filenames)
    candidates: list[str] = []
    file_name = server_save.get("file_name")
    if isinstance(file_name, str):
        candidates.append(strip_romm_timestamp_tag(file_name))
    no_tags, ext = server_save.get("file_name_no_tags"), server_save.get("file_extension")
    if isinstance(no_tags, str) and isinstance(ext, str) and ext:
        candidates.append(f"{no_tags}.{ext}")
    for candidate in candidates:
        if candidate in names:
            return candidate
    save_id = server_save.get("id")
    if tracked and isinstance(save_id, int):
        name = tracked.get(save_id)
        if name in names:
            return name
    return None


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

    *files* and *empty_dirs* are paths relative to the save folder, ``/``-
    separated. Only an empty directory gets an entry of its own (with a
    trailing ``/``); every other directory is implied by the files inside it.
    Sorted, so the same folder always yields the same archive.
    """
    return sorted([*files, *(d.rstrip("/") + "/" for d in empty_dirs)])
