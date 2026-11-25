"""Exact per-game save sets of standalone emulators, and how server saves map onto them.

A standalone emulator's save for one game is a small, fixed set of names
derived exactly from the game — from the ROM's file stem, or from the
identifier its disc carries (:mod:`domain.disc_ids`) — never guessed from what
happens to be on disk. This module owns that derivation, the mapping of a
RomM save record back onto one of those names, and each emulator's bundle
layout (:mod:`domain.save_bundles`) for saves that are not one file. Which
emulator a ROM launches with, where that emulator keeps its saves, and what a
disc image says are answered elsewhere (the active-core seam, the launcher
backend, the disc-code reader); everything here is pure.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.disc_ids import (
    GAMECUBE,
    NINTENDO_OPTICAL,
    PS2,
    PSP,
    WII,
    DiscCode,
    gamecube_region_folder,
    wii_title_folder,
)
from domain.save_bundles import DIR_MEMBERS, GCI_MEMBERS, BundleLayout, MemberSource, safe_component
from domain.vita_app import is_title_id

if TYPE_CHECKING:
    from collections.abc import Mapping

MELONDS = "melonds"
DUCKSTATION = "duckstation"
VITA3K = "vita3k"
DOLPHIN = "dolphin"
PPSSPP = "ppsspp"
PCSX2 = "pcsx2"

STANDALONE_EMULATOR_TAGS: frozenset[str] = frozenset({MELONDS, DUCKSTATION, VITA3K, DOLPHIN, PPSSPP, PCSX2})
"""RomM ``emulator`` tags written by standalone save sync — each emulator's own id.

A RetroArch save set never claims a save carrying one of these tags, and a
standalone save set claims only its own, so saves from two emulators never
resolve onto the same local file.
"""

# Lower-cased executable-name prefixes, as EmuDeck for Windows installs them:
# ``melonDS.exe``, ``duckstation-qt-x64-ReleaseLTCG.exe``, ``Vita3K.exe``,
# ``Dolphin.exe``, ``PPSSPPWindows64.exe``, ``pcsx2-qt.exe``.
_EXE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("melonds", MELONDS),
    ("duckstation", DUCKSTATION),
    ("vita3k", VITA3K),
    ("dolphin", DOLPHIN),
    ("ppsspp", PPSSPP),
    ("pcsx2", PCSX2),
)

DISC_FAMILIES: dict[str, str] = {DOLPHIN: NINTENDO_OPTICAL, PPSSPP: PSP, PCSX2: PS2}
"""The emulators whose save set is named by the disc, and the disc family each reads."""

DOLPHIN_GC_SUFFIX = ".dolphin-gc.zip"
DOLPHIN_WII_SUFFIX = ".dolphin-wii.zip"
PPSSPP_SUFFIX = ".ppsspp.zip"
PCSX2_SUFFIX = ".pcsx2.zip"
_GC_CARDS = ("Card A", "Card B")

_QUOTED_RE = re.compile(r'"([^"]+)"')

BUNDLE_SUFFIX = ".vita3k.zip"
_BUNDLE_RE = re.compile(r"^([A-Z]{4}\d{5})\.vita3k\.zip$")
_BUNDLE_SUFFIXES = (BUNDLE_SUFFIX, DOLPHIN_GC_SUFFIX, DOLPHIN_WII_SUFFIX, PPSSPP_SUFFIX, PCSX2_SUFFIX)

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
    and ``filename`` is the zip that folder travels as; when ``bundle`` is set
    the save is whatever that layout selects, and ``filename`` is its zip.
    """

    filename: str
    bundle_dir: str | None = None
    bundle: BundleLayout | None = None

    @property
    def layout(self) -> BundleLayout | None:
        """The entry's bundle layout, or ``None`` for a plain file."""
        if self.bundle is not None:
            return self.bundle
        if self.bundle_dir is not None:
            return BundleLayout(label=self.bundle_dir, folder=self.bundle_dir)
        return None


@dataclass(frozen=True)
class StandaloneSaveSet:
    """A ROM's complete save set under one standalone emulator."""

    emulator_tag: str
    entries: tuple[SaveSetEntry, ...]

    @property
    def filenames(self) -> tuple[str, ...]:
        """Every tracked filename of the set, in set order."""
        return tuple(entry.filename for entry in self.entries)

    def layout_for(self, filename: str) -> BundleLayout | None:
        """The bundle layout of the set's entry *filename*, or ``None`` (a plain file, or not in the set)."""
        for entry in self.entries:
            if entry.filename == filename:
                return entry.layout
        return None


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


def is_bundle_filename(filename: str) -> bool:
    """Whether *filename* names a bundle of any standalone emulator (a zip standing for a folder or set)."""
    return filename.endswith(_BUNDLE_SUFFIXES)


def emulator_executable(command: str | None) -> str | None:
    """The first double-quoted path in a baked launch command — the emulator executable — or ``None``."""
    if not command:
        return None
    match = _QUOTED_RE.search(command)
    return match.group(1) if match else None


def disc_save_set(emulator_id: str, disc: DiscCode, pcsx2_card: str | None = None) -> StandaloneSaveSet | None:
    """The save set of the game whose disc carries *disc*, under *emulator_id*, or ``None``.

    Paths are relative to the emulator's EmuDeck saves folder (``$savesPath\\<emulator>``):

    - Dolphin, GameCube: every GCI file in ``GC/<region>/Card A`` and ``Card B``
      whose header carries the disc's 4-character game code, as
      ``<ID6>.dolphin-gc.zip``. Shared card files (``SRAM.raw``,
      ``MemoryCard*.raw``) are never selected: only ``.gci`` files are.
    - Dolphin, Wii: the ``Wii/title/00010000/<ID4 hex>/data`` folder, as
      ``<ID4>.dolphin-wii.zip``.
    - PPSSPP: every ``saves/<GAME ID>*`` save-data folder, as ``<GAME ID>.ppsspp.zip``.
    - PCSX2: every ``saves/<card>/B?<SERIAL>*`` folder of the folder memory
      card *pcsx2_card* (required), as ``<SERIAL>.pcsx2.zip``. The card's own
      ``_pcsx2_*`` files never match.
    """
    code = disc.code
    if emulator_id == DOLPHIN and disc.platform == GAMECUBE:
        region = gamecube_region_folder(code, disc.revision)
        if region is None:
            return None
        sources = tuple(MemberSource(f"GC/{region}/{card}", f"{card}/", GCI_MEMBERS, code[:4]) for card in _GC_CARDS)
        return _member_set(DOLPHIN, f"{code}{DOLPHIN_GC_SUFFIX}", sources)
    if emulator_id == DOLPHIN and disc.platform == WII:
        title = wii_title_folder(code)
        if title is None:
            return None
        filename = f"{code[:4]}{DOLPHIN_WII_SUFFIX}"
        layout = BundleLayout(label=filename[: -len(".zip")], folder=f"Wii/title/00010000/{title}/data")
        return StandaloneSaveSet(DOLPHIN, (SaveSetEntry(filename, bundle=layout),))
    if emulator_id == PPSSPP and disc.platform == PSP:
        source = MemberSource("saves", "", DIR_MEMBERS, re.escape(code) + ".*")
        return _member_set(PPSSPP, f"{code}{PPSSPP_SUFFIX}", (source,))
    if emulator_id == PCSX2 and disc.platform == PS2 and pcsx2_card and safe_component(pcsx2_card):
        source = MemberSource(f"saves/{pcsx2_card}", "", DIR_MEMBERS, "B[A-Z]" + re.escape(code) + ".*")
        return _member_set(PCSX2, f"{code}{PCSX2_SUFFIX}", (source,))
    return None


def _member_set(emulator_id: str, filename: str, sources: tuple[MemberSource, ...]) -> StandaloneSaveSet:
    layout = BundleLayout(label=filename[: -len(".zip")], sources=sources)
    return StandaloneSaveSet(emulator_id, (SaveSetEntry(filename, bundle=layout),))


_INI_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_INI_VALUE_RE = re.compile(r"^\s*([^=;#]+?)\s*=\s*(.*?)\s*$")


PCSX2_SLOT_EMPTY = "slot_empty"
PCSX2_CARDS_ELSEWHERE = "cards_elsewhere"
"""Why :func:`pcsx2_slot1` found no usable card name."""


def pcsx2_slot1(ini_text: str) -> tuple[str | None, str | None]:
    """``(card, problem)`` for the memory card PCSX2 puts in slot 1, by its ``PCSX2.ini``.

    The card is set only when ``[MemoryCards] Slot1_Enable`` is ``true``,
    ``Slot1_Filename`` is one plain name, and ``[Folders] MemoryCards`` is the
    default ``memcards`` folder (the one EmuDeck links to
    ``$savesPath\\pcsx2\\saves``); otherwise *problem* is
    :data:`PCSX2_SLOT_EMPTY` (no card, or a name that is not one plain
    component) or :data:`PCSX2_CARDS_ELSEWHERE`. Whether that name is a folder
    card is for the caller to check on disk.
    """
    values: dict[tuple[str, str], str] = {}
    section = ""
    for line in ini_text.splitlines():
        header = _INI_SECTION_RE.match(line)
        if header:
            section = header.group(1).strip().lower()
            continue
        pair = _INI_VALUE_RE.match(line)
        if pair:
            values[(section, pair.group(1).lower())] = pair.group(2)
    if values.get(("memorycards", "slot1_enable"), "").lower() != "true":
        return None, PCSX2_SLOT_EMPTY
    if values.get(("folders", "memorycards"), "memcards").strip().lower() != "memcards":
        return None, PCSX2_CARDS_ELSEWHERE
    card = safe_component(values.get(("memorycards", "slot1_filename"), "").strip())
    return (card, None) if card else (None, PCSX2_SLOT_EMPTY)


def bundle_layout(filename: str, save_set: StandaloneSaveSet | None) -> BundleLayout | None:
    """The bundle layout *filename* stands for, or ``None`` when it is a plain file.

    Taken from *save_set* when the set holds *filename*; otherwise a Vita3K
    bundle name still answers its folder (its layout follows from the name
    alone). Any other bundle name without its save set raises ``ValueError``:
    its members cannot be known, and treating the zip as a plain file would
    leave the real save untouched while recording it as synced.
    """
    if save_set is not None:
        layout = save_set.layout_for(filename)
        if layout is not None:
            return layout
    folder = bundle_dir_for(filename)
    if folder is not None:
        return BundleLayout(label=folder, folder=folder)
    if is_bundle_filename(filename):
        raise ValueError(f"no save set describes the bundle {filename!r}")
    return None
