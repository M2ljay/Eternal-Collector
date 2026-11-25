"""Why a game's saves cannot be synced, worded for the person holding the controller.

A ROM that launches with a standalone emulator syncs only the exact save set
:mod:`domain.standalone_saves` derives for it. When that set cannot be derived —
the emulator is unknown, its save folder is not where the launcher says, the
disc carries no readable ID, PCSX2 writes to a single-file memory card — the
plugin used to fall back to RetroArch's layout and upload nothing, silently.
Each such case is a :class:`SaveSyncBlocker` here instead: a stable ``reason``
slug for code and tests, and one plain sentence that says what is wrong and,
where the user can fix it, how. A blocker never stops a game from launching.

Pure: no I/O, no service/adapter/lib imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# What each standalone emulator's saves are called in a message: the console the
# user thinks of, not the emulator's name.
_PLATFORM_LABEL = {
    "melonds": "DS",
    "duckstation": "PS1",
    "vita3k": "Vita",
    "dolphin": "GameCube and Wii",
    "ppsspp": "PSP",
    "pcsx2": "PS2",
}
_EMULATOR_LABEL = {
    "melonds": "melonDS",
    "duckstation": "DuckStation",
    "vita3k": "Vita3K",
    "dolphin": "Dolphin",
    "ppsspp": "PPSSPP",
    "pcsx2": "PCSX2",
}

UNKNOWN_EMULATOR = "unknown_emulator"
EMULATOR_FOLDER_UNKNOWN = "emulator_folder_unknown"
DISC_UNREADABLE = "disc_unreadable"
DISC_FORMAT_UNSUPPORTED = "disc_format_unsupported"
DISC_IMAGE_UNSUPPORTED = "disc_image_unsupported"
DISC_ID_MISSING = "disc_id_missing"
DISC_REGION_UNKNOWN = "disc_region_unknown"
PCSX2_SETTINGS_UNREADABLE = "pcsx2_settings_unreadable"
PCSX2_SLOT_EMPTY = "pcsx2_slot_empty"
PCSX2_CARDS_ELSEWHERE = "pcsx2_cards_elsewhere"
PCSX2_FILE_CARD = "pcsx2_file_card"
PCSX2_CARD_MISSING = "pcsx2_card_missing"
VITA_NO_TITLE_ID = "vita_no_title_id"


@dataclass(frozen=True)
class SaveSyncBlocker:
    """One reason a ROM's saves are not synced: a stable slug and the sentence the UI shows."""

    reason: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason, "message": self.message}


def _saves(emulator_id: str) -> str:
    label = _PLATFORM_LABEL.get(emulator_id)
    return f"{label} saves aren't syncing" if label else "Saves aren't syncing"


def unknown_emulator(executable_name: str | None) -> SaveSyncBlocker:
    what = executable_name or "this emulator"
    return SaveSyncBlocker(
        UNKNOWN_EMULATOR, f"Saves aren't syncing: The Collector doesn't know where {what} keeps its saves."
    )


def emulator_folder_unknown(emulator_id: str) -> SaveSyncBlocker:
    name = _EMULATOR_LABEL.get(emulator_id, emulator_id)
    return SaveSyncBlocker(
        EMULATOR_FOLDER_UNKNOWN, f"{_saves(emulator_id)}: couldn't find {name}'s save folder in EmuDeck's settings."
    )


def disc_problem(emulator_id: str, kind: str | None, detail: str | None, extension: str) -> SaveSyncBlocker:
    """A disc-named save set whose disc ID could not be read; *kind* comes from ``DiscCodeReader.disc_code_problem``."""
    saves = _saves(emulator_id)
    if kind == "unsupported_format":
        ext = extension or "these"
        return SaveSyncBlocker(
            DISC_FORMAT_UNSUPPORTED, f"{saves}: The Collector can't read the game ID from {ext} files."
        )
    if kind == "unsupported_image":
        why = f" ({detail})" if detail else ""
        return SaveSyncBlocker(
            DISC_IMAGE_UNSUPPORTED,
            f"{saves}: The Collector can't read this disc image{why}, so it can't find the game ID.",
        )
    if kind == "no_disc_id":
        return SaveSyncBlocker(DISC_ID_MISSING, f"{saves}: the disc image has no game ID The Collector can read.")
    return SaveSyncBlocker(DISC_UNREADABLE, f"{saves}: couldn't open the game file to read its game ID.")


def disc_region_unknown(emulator_id: str) -> SaveSyncBlocker:
    return SaveSyncBlocker(
        DISC_REGION_UNKNOWN, f"{_saves(emulator_id)}: couldn't tell which save folder this disc's region uses."
    )


def pcsx2_settings_unreadable() -> SaveSyncBlocker:
    return SaveSyncBlocker(
        PCSX2_SETTINGS_UNREADABLE,
        "PS2 saves aren't syncing: couldn't read PCSX2's settings (inis\\PCSX2.ini next to pcsx2-qt.exe).",
    )


def pcsx2_slot_empty() -> SaveSyncBlocker:
    return SaveSyncBlocker(
        PCSX2_SLOT_EMPTY,
        "PS2 saves aren't syncing: PCSX2 has no memory card in slot 1. Insert a folder card in slot 1.",
    )


def pcsx2_cards_elsewhere() -> SaveSyncBlocker:
    return SaveSyncBlocker(
        PCSX2_CARDS_ELSEWHERE,
        "PS2 saves aren't syncing: PCSX2 keeps its memory cards outside EmuDeck's saves folder. "
        "Set PCSX2's memory card folder back to the default.",
    )


def pcsx2_file_card() -> SaveSyncBlocker:
    return SaveSyncBlocker(
        PCSX2_FILE_CARD,
        "PS2 saves aren't syncing: PCSX2 is using a single-file memory card. Switch slot 1 to a folder card.",
    )


def pcsx2_card_missing(card: str) -> SaveSyncBlocker:
    return SaveSyncBlocker(
        PCSX2_CARD_MISSING,
        f"PS2 saves aren't syncing: PCSX2's slot 1 card {card} wasn't found in EmuDeck's saves folder.",
    )


def vita_no_title_id() -> SaveSyncBlocker:
    return SaveSyncBlocker(
        VITA_NO_TITLE_ID,
        "Vita saves aren't syncing: the game file isn't named after its title ID (for example PCSE01274.psvita).",
    )
