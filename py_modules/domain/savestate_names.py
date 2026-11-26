"""RetroArch savestate naming — the slot vocabulary, the local file names, the server file name.

Owns every string the savestate backup has to agree on with something outside the
plugin: the names RetroArch writes, the name a backup takes on the RomM server, and
the ``emulator`` id RomM files a RetroArch savestate under. Pure — no I/O.

The slot keys (``auto``, ``0``…``9``) are the keys RomM 5.5 snapshot banks use
(``snapshot_states`` rows keyed ``(snapshot, core, slot)``), so a later move to
channels and snapshots reads the same vocabulary.

Discovery is exact-name probing: a fixed slot list per booted stem, never a glob over
the shared states folder, which holds every game's savestates side by side.
"""

from __future__ import annotations

import re

SLOT_AUTO = "auto"
NUMBERED_SLOTS: tuple[str, ...] = tuple(str(n) for n in range(10))
ALL_SLOTS: tuple[str, ...] = (SLOT_AUTO, *NUMBERED_SLOTS)

SCOPE_AUTO = "auto"
SCOPE_ALL = "all"
SCOPES: tuple[str, ...] = (SCOPE_AUTO, SCOPE_ALL)

_STATE = ".state"
_AUTO_SUFFIX = ".state.auto"
_SCREENSHOT_SUFFIX = ".png"
_CORE_SUFFIX = "_libretro"
_SHORT_ID_LENGTH = 8
_NON_ALNUM = re.compile(r"[^0-9a-z]")

# RomM's RetroArch core-folder table, verbatim from
# backend/handler/sync/retroarch/emulator_names.py at RomM 5.4.1 ("follows
# github.com/Covin90/romm-retroarch-sync"). Keys are the ``emulator`` ids RomM's web
# player and WebDAV sync file RetroArch savestates under; values are RetroArch's
# ``corename`` (the per-core folder name). Re-copy it from upstream rather than
# editing an entry here.
RETROARCH_DIR_BY_ROMM_EMULATOR: dict[str, str] = {
    "snes9x": "Snes9x",
    "bsnes": "bsnes",
    "mesen-s": "Mesen-S",
    "nestopia": "Nestopia",
    "fceumm": "FCEUmm",
    "mesen": "Mesen",
    "mednafen_psx": "Beetle PSX",
    "mednafen_psx_hw": "Beetle PSX HW",
    "beetle_psx": "Beetle PSX",
    "beetle_psx_hw": "Beetle PSX HW",
    "pcsx_rearmed": "PCSX-ReARMed",
    "swanstation": "SwanStation",
    "gambatte": "Gambatte",
    "sameboy": "SameBoy",
    "tgbdual": "TGB Dual",
    "mgba": "mGBA",
    "vba_next": "VBA Next",
    "vbam": "VBA-M",
    "genesis_plus_gx": "Genesis Plus GX",
    "blastem": "BlastEm",
    "picodrive": "PicoDrive",
    "mupen64plus_next": "Mupen64Plus-Next",
    "parallel_n64": "ParaLLEl N64",
    "mednafen_saturn": "Beetle Saturn",
    "beetle_saturn": "Beetle Saturn",
    "kronos": "Kronos",
    "mame": "MAME",
    "fbneo": "FBNeo",
    "fbalpha": "FB Alpha",
    "pcsx2": "PCSX2",
    "play": "Play!",
    "dolphin": "Dolphin",
    "flycast": "Flycast",
    "redream": "Redream",
    "stella": "Stella",
    "mednafen_pce": "Beetle PCE",
    "mednafen_pce_fast": "Beetle PCE Fast",
    "beetle_pce": "Beetle PCE",
    "beetle_pce_fast": "Beetle PCE Fast",
    "dosbox_pure": "DOSBox-Pure",
    "scummvm": "ScummVM",
    "ppsspp": "PPSSPP",
    "desmume": "DeSmuME",
    "melonds": "melonDS",
    "citra": "Citra",
}

# Reversed so the first id listed for a shared folder wins, as RomM's own
# ``ROMM_EMULATOR_BY_RETROARCH_DIR`` does: that is the ``mednafen_*`` id the web
# player stores for the Beetle cores.
ROMM_EMULATOR_BY_RETROARCH_DIR: dict[str, str] = {
    dir_name: emulator for emulator, dir_name in reversed(RETROARCH_DIR_BY_ROMM_EMULATOR.items())
}


def slots_for_scope(scope: str) -> tuple[str, ...]:
    """The slots a backup scope covers: the auto-state alone, or every slot.

    Anything that is not ``"all"`` is the auto-state only, so an unknown or missing
    scope never widens what is uploaded.
    """
    return ALL_SLOTS if scope == SCOPE_ALL else (SLOT_AUTO,)


def slot_suffix(slot: str) -> str:
    """The file suffix RetroArch writes for *slot*: ``.state.auto``, ``.state``, ``.state1``…

    Slot ``0`` has no digit, which is RetroArch's own naming. Raises ``ValueError``
    for a slot outside the vocabulary.
    """
    if slot == SLOT_AUTO:
        return _AUTO_SUFFIX
    if slot not in NUMBERED_SLOTS:
        raise ValueError(f"unknown savestate slot {slot!r}")
    return _STATE if slot == "0" else f"{_STATE}{slot}"


def local_savestate_name(stem: str, slot: str) -> str:
    """The flat-layout file name RetroArch gives *slot* of the content booted as *stem*."""
    if not stem:
        raise ValueError("a savestate name needs the booted content's stem")
    return stem + slot_suffix(slot)


def local_savestate_names(stem: str, slots: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """``(slot, file name)`` for each of *slots*, in the order given — the exact names to probe."""
    return tuple((slot, local_savestate_name(stem, slot)) for slot in slots)


def split_savestate_name(file_name: str) -> tuple[str, str] | None:
    """``(stem, slot)`` for a RetroArch savestate file name, or ``None`` if it is not one.

    ``.state.auto`` is matched as one two-part suffix before anything else: a
    generic last-dot split reads ``Game.state.auto`` as stem ``Game.state`` with
    suffix ``.auto``, and a name rebuilt from that comes back as ``.state.state``
    (the bug Ludo records in ``sync_core.py``). Only the slots in the vocabulary are
    recognised; ``.state10`` and above answer ``None``.
    """
    if file_name.endswith(_AUTO_SUFFIX):
        stem = file_name[: -len(_AUTO_SUFFIX)]
        return (stem, SLOT_AUTO) if stem else None
    base, dot, tail = file_name.rpartition(".")
    if not dot or not base or not tail.startswith("state"):
        return None
    digits = tail[len("state") :]
    if digits == "":
        return (base, "0")
    if digits in NUMBERED_SLOTS and digits != "0":
        return (base, digits)
    return None


def screenshot_name(savestate_name: str) -> str:
    """The thumbnail RetroArch writes beside a savestate: the full savestate name plus ``.png``.

    RomM pairs a savestate with the screenshot whose name without extension equals
    the savestate's file name (``Screenshot.file_name_no_ext == State.file_name``,
    ``handler/database/screenshots_handler.py`` at 5.4.1), so the same rule names
    the screenshot uploaded alongside a backup.
    """
    return savestate_name + _SCREENSHOT_SUFFIX


def device_short_id(device_id: str) -> str:
    """The first eight letters or digits of the server-issued device id, lowercased.

    Short enough to keep the server name readable, long enough that two devices of
    one user do not collide. Raises ``ValueError`` when the id holds no letter or
    digit at all, because an empty tag would let two devices share one server name.
    """
    cleaned = _NON_ALNUM.sub("", device_id.lower())
    if not cleaned:
        raise ValueError("device id has no letters or digits to tag a savestate with")
    return cleaned[:_SHORT_ID_LENGTH]


def server_savestate_name(stem: str, short_id: str, slot: str) -> str:
    """The name a backup takes on the server: ``<booted stem> [<device short-id>].<slot suffix>``.

    RomM upserts a savestate by ``(user, rom, file name)``, so one name per device
    and slot means a device replaces only its own previous backup of that slot and
    never another device's, and the tag keeps the name clear of the plain names a
    RomM 5.5 channel holds.
    """
    if not short_id:
        raise ValueError("a server savestate name needs the device short-id")
    return local_savestate_name(f"{stem} [{short_id}]", slot)


def core_id(core_so: str) -> str:
    """The core's shared-object name without the ``_libretro`` suffix (``snes9x_libretro`` → ``snes9x``)."""
    return core_so[: -len(_CORE_SUFFIX)] if core_so.endswith(_CORE_SUFFIX) else core_so


def romm_emulator_for_core(core_so: str, corename: str | None) -> str:
    """The RomM ``emulator`` id a RetroArch savestate of this core is filed under.

    The core's own id when RomM's table knows it (most libretro ids are RomM's ids
    already: ``snes9x``, ``mupen64plus_next``, ``mednafen_psx_hw``); else RomM's id
    for the RetroArch folder name *corename*; else the core's own id, which keeps an
    unlisted core in a folder of its own rather than in a neighbour's.
    """
    own = core_id(core_so)
    if own in RETROARCH_DIR_BY_ROMM_EMULATOR:
        return own
    if corename and corename in ROMM_EMULATOR_BY_RETROARCH_DIR:
        return ROMM_EMULATOR_BY_RETROARCH_DIR[corename]
    return own
