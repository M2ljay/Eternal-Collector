"""Cheat-file, built-in-toggle and graphic-pack targets, and what the emulators without one offer instead.

The companion of :mod:`domain.game_mods` for the kinds beyond plain files:
each builder answers exact targets from facts already read (the emulator's
home, the game's identifier, PCSX2's boot ELF CRC, an emulator's own settings
text) or nothing, with the reason in an :class:`OmittedTarget`. The files a
toggle target reads and writes are described by a ``ToggleSource``; reading
them is the adapters' job and interpreting them :mod:`domain.mod_toggles`'.

No I/O. Pure functions only.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from domain.game_mods import (
    CEMU,
    KIND_BUILTIN_TOGGLE,
    KIND_CHEAT_FILE,
    KIND_GRAPHICS_MODS,
    RPCS3,
    SCOPE_FILE,
    SCOPE_SHARED,
    SCOPE_TOGGLE,
    SHADPS4,
    TARGET_ACTION_REPLAY,
    TARGET_CHEAT_CODES,
    TARGET_CHEATS,
    TARGET_GECKO,
    TARGET_GRAPHIC_PACKS,
    TARGET_PATCHES,
    XEMU,
    XENIA,
    EmulatorHome,
    ModTarget,
    OmittedTarget,
    SettingSpec,
    ToggleSource,
    ini_value,
    is_absolute_path,
    join_path,
    path_dirname,
)
from domain.mod_toggles import dolphin_game_ini_names

if TYPE_CHECKING:
    from domain.disc_ids import DiscCode

TOGGLE_DOLPHIN_GECKO = "dolphin_gecko"
TOGGLE_DOLPHIN_ACTION_REPLAY = "dolphin_action_replay"
TOGGLE_PCSX2_PATCHES = "pcsx2_patches"
TOGGLE_PCSX2_CHEATS = "pcsx2_cheats"
TOGGLE_AZAHAR_CHEATS = "azahar_cheats"

DOLPHIN_ENABLE_CHEATS = SettingSpec(
    label="Enable Cheats",
    ini="Config/Dolphin.ini",
    section="Core",
    key="EnableCheats",
    on_value="True",
    default_on=False,
)
"""Dolphin ``Config::MAIN_ENABLE_CHEATS`` (``Source/Core/Core/Config/MainSettings.cpp``), off by default."""

PCSX2_ENABLE_CHEATS = SettingSpec(
    label="Enable Cheats",
    ini="inis/PCSX2.ini",
    section="EmuCore",
    key="EnableCheats",
    on_value="true",
    default_on=False,
)
"""PCSX2 ``Pcsx2Config::EnableCheats`` (``pcsx2/Pcsx2Config.cpp``, ``[EmuCore]``), off by default."""

_PER_GAME_OVERRIDE = "A per-game setting in the emulator can override this global switch; it is not read here."


def cemu_home(exe: str, *, portable_dir_exists: bool, settings_beside_exe: bool) -> EmulatorHome:
    """Cemu's user data folder on Windows (``CemuApp::DeterminePaths``, Cemu 2.x).

    ``<exe folder>\\portable`` when that folder exists; else the exe folder when
    ``settings.xml`` sits beside it (installs from before 2.0-89); otherwise
    ``%APPDATA%\\Cemu``, which is not read here.
    """
    exe_dir = path_dirname(exe)
    if portable_dir_exists:
        return EmulatorHome(CEMU, exe, join_path(exe_dir, "portable"))
    if settings_beside_exe:
        return EmulatorHome(CEMU, exe, exe_dir)
    return EmulatorHome(CEMU, exe, None, "Cemu is not portable (no 'portable' folder or settings.xml beside its exe)")


# -- Azahar ----------------------------------------------------------------------


def azahar_cheat_targets(home: EmulatorHome, title_id: str) -> tuple[ModTarget, ...]:
    """The cheat file ``<user>\\cheats\\<TitleID>.txt`` (``CheatEngine::LoadCheatFile``) and switching its cheats."""
    if home.data_root is None:
        return ()
    folder = join_path(home.data_root, "cheats")
    name = f"{title_id}.txt"
    return (
        ModTarget(
            TARGET_CHEATS,
            "Cheat file (.txt)",
            SCOPE_FILE,
            folder,
            kind=KIND_CHEAT_FILE,
            file_name=name,
            file_ext=".txt",
            notes=("Installed as the game's own cheat file; it replaces one already there (kept in the backup).",),
        ),
        ModTarget(
            TARGET_CHEAT_CODES,
            "Cheats",
            SCOPE_TOGGLE,
            folder,
            kind=KIND_BUILTIN_TOGGLE,
            toggle=ToggleSource(TOGGLE_AZAHAR_CHEATS, join_path(folder, name), read_files=(join_path(folder, name),)),
            notes=("The cheats in the game's cheat file; Azahar marks an enabled one with *citra_enabled.",),
        ),
    )


# -- Dolphin ---------------------------------------------------------------------


def dolphin_code_targets(home: EmulatorHome, code: DiscCode) -> tuple[ModTarget, ...]:
    """Gecko and Action Replay codes from Dolphin's shipped ``Sys\\GameSettings`` and the user's ``GameSettings``.

    A switch writes only ``User\\GameSettings\\<ID6>.ini``. ``Sys`` sits beside
    the executable in a portable install (``File::GetSysDirectory``).
    """
    if home.data_root is None:
        return ()
    names = dolphin_game_ini_names(code.code, code.revision)
    sys_dir = join_path(path_dirname(home.exe), "Sys", "GameSettings")
    user_dir = join_path(home.data_root, "GameSettings")
    shipped = tuple(join_path(sys_dir, n) for n in names)
    user = tuple(join_path(user_dir, n) for n in names)
    write = join_path(user_dir, f"{code.code}.ini")
    notes = (
        "Dolphin's own code list for this game, plus codes added in Dolphin; switching writes GameSettings only.",
        _PER_GAME_OVERRIDE,
    )
    return tuple(
        ModTarget(
            target_id,
            label,
            SCOPE_TOGGLE,
            user_dir,
            kind=KIND_BUILTIN_TOGGLE,
            setting=DOLPHIN_ENABLE_CHEATS,
            toggle=ToggleSource(fmt, write, read_files=shipped, user_files=user),
            notes=notes,
        )
        for target_id, label, fmt in (
            (TARGET_GECKO, "Gecko codes", TOGGLE_DOLPHIN_GECKO),
            (TARGET_ACTION_REPLAY, "Action Replay codes", TOGGLE_DOLPHIN_ACTION_REPLAY),
        )
    )


# -- PCSX2 -----------------------------------------------------------------------


def _pcsx2_folder(exe_dir: str, pcsx2_ini: str | None, key: str, default: str) -> str:
    """``EmuFolders::LoadPathFromSettings``: ``[Folders] <key>``, absolute as written, else below the data folder."""
    value = ini_value(pcsx2_ini, "Folders", key) or default
    return value.rstrip("\\/") if is_absolute_path(value) else join_path(exe_dir, *re.split(r"[\\/]", value))


def pcsx2_patch_targets(home: EmulatorHome, pcsx2_ini: str | None, serial: str, crc: str) -> tuple[ModTarget, ...]:
    """PCSX2's cheat file, its cheats and the game's patches, all named ``<SERIAL>_<CRC>``.

    - Cheat file: ``<cheats>\\<SERIAL>_<CRC>.pnach`` (``Patch::GetPnachFilename``).
    - Patches: ``<patches>\\<SERIAL>_<CRC>*.pnach`` and ``<CRC>*.pnach``, else the
      shipped ``resources\\patches.zip`` member (``EnumeratePnachFiles``).
    - Cheats: the same names in the cheats folder.
    Switches are ``Enable`` lines in ``<gamesettings>\\<SERIAL>_<CRC>.ini``
    (``VMManager::GetGameSettingsPath``).
    """
    if home.data_root is None:
        return ()
    exe_dir = home.data_root
    cheats = _pcsx2_folder(exe_dir, pcsx2_ini, "Cheats", "cheats")
    patches = _pcsx2_folder(exe_dir, pcsx2_ini, "Patches", "patches")
    settings = _pcsx2_folder(exe_dir, pcsx2_ini, "GameSettings", "gamesettings")
    stem = f"{serial}_{crc}"
    game_ini = join_path(settings, f"{stem}.ini")
    prefixes = (stem, crc)
    return (
        ModTarget(
            TARGET_CHEATS,
            "Cheat file (.pnach)",
            SCOPE_FILE,
            cheats,
            kind=KIND_CHEAT_FILE,
            file_name=f"{stem}.pnach",
            file_ext=".pnach",
            setting=PCSX2_ENABLE_CHEATS,
            notes=(
                f"Named by the game's serial and boot executable CRC ({crc}).",
                "PCSX2 applies a labelled cheat only once it is switched on under Cheats.",
            ),
        ),
        ModTarget(
            TARGET_PATCHES,
            "Patches (widescreen, 60 FPS, fixes)",
            SCOPE_TOGGLE,
            settings,
            kind=KIND_BUILTIN_TOGGLE,
            toggle=ToggleSource(
                TOGGLE_PCSX2_PATCHES,
                game_ini,
                scan_dir=patches,
                scan_prefixes=prefixes,
                zip_file=join_path(exe_dir, "resources", "patches.zip"),
                zip_members=(f"{stem}.pnach", f"{crc}.pnach"),
            ),
            notes=("PCSX2's shipped patches for this game, and any in its patches folder.",),
        ),
        ModTarget(
            TARGET_CHEAT_CODES,
            "Cheats",
            SCOPE_TOGGLE,
            settings,
            kind=KIND_BUILTIN_TOGGLE,
            setting=PCSX2_ENABLE_CHEATS,
            toggle=ToggleSource(TOGGLE_PCSX2_CHEATS, game_ini, scan_dir=cheats, scan_prefixes=prefixes),
            notes=("The labelled cheats in this game's .pnach files in the cheats folder.", _PER_GAME_OVERRIDE),
        ),
    )


def pcsx2_pnach_matches(names: list[str], prefixes: tuple[str, ...]) -> list[str]:
    """The ``.pnach`` names PCSX2's patterns ``<prefix>*.pnach`` match, serial-named first, each group sorted.

    Matched case-insensitively, as Windows' ``FindFiles`` does.
    """
    out: list[str] = []
    for prefix in prefixes:
        group = sorted(
            n for n in names if n.lower().startswith(prefix.lower()) and n.lower().endswith(".pnach") and n not in out
        )
        out.extend(group)
    return out


# -- RetroArch -------------------------------------------------------------------


def retroarch_cheat_dir(exe_dir: str, cfg_text: str | None) -> tuple[str | None, str | None]:
    """``cheat_database_path`` of ``retroarch.cfg`` as a folder, or ``(None, reason)``.

    ``:\\`` at the start is RetroArch's application folder
    (``fill_pathname_expand_special``); an absent or empty value is its
    Windows default ``<RetroArch>\\cheats``.
    """
    raw = ini_value(cfg_text, "", "cheat_database_path")
    value = raw.strip().strip('"') if raw is not None else ""
    if not value or value == "default":
        return (join_path(exe_dir, "cheats"), None)
    if value.startswith((":\\", ":/")):
        return (join_path(exe_dir, *[p for p in re.split(r"[\\/]", value[2:]) if p]), None)
    if is_absolute_path(value):
        return (value.rstrip("\\/"), None)
    return (None, f"retroarch.cfg's cheat_database_path {value!r} is not a folder this plugin can resolve")


def retroarch_cheat_target(
    cheat_dir: str, core_name: str | None, rom_path: str, *, single_file: bool
) -> tuple[ModTarget | None, OmittedTarget | None]:
    """RetroArch's game-specific cheat file ``<cheats>\\<core>\\<content stem>.cht``.

    ``cheat_manager_get_game_specific_filename`` joins the core's library name
    and the content's base name with ``.cht``; RetroArch loads it when the game
    starts. The library name is taken from the core's ``.info`` ``corename``.
    """
    label = "Cheat file (.cht)"
    name = re.split(r"[\\/]", rom_path)[-1]
    stem, dot, ext = name.rpartition(".")
    if not single_file or not dot or ext.lower() in ("zip", "7z", "rar"):
        return (None, OmittedTarget(label, "RetroArch names the cheat file after one content file outside an archive."))
    if not core_name:
        return (None, OmittedTarget(label, "The core's info file names no core, which the cheat folder is named by."))
    target = ModTarget(
        TARGET_CHEATS,
        label,
        SCOPE_FILE,
        join_path(cheat_dir, core_name),
        kind=KIND_CHEAT_FILE,
        file_name=f"{stem}.cht",
        file_ext=".cht",
        notes=(
            "RetroArch loads this file when the game starts; cheats marked enabled in it are applied only with"
            " Settings > Cheats > Auto-Apply Cheats During Game Load on (not checked here).",
            "The folder is named by the core info's corename, which RetroArch's core reports as its library name.",
        ),
    )
    return (target, None)


# -- emulators with nothing offered ----------------------------------------------

_NOT_OFFERED: dict[str, tuple[OmittedTarget, ...]] = {
    RPCS3: (
        OmittedTarget(
            "Game patches",
            "RPCS3 keeps its patch list and the enabled patches in YAML (patches\\patch.yml,"
            " patch_config.yml), keyed by the executable's PPU hash; this plugin has no YAML reader it can trust to"
            " edit them. Switch patches in RPCS3 (Manage > Game Patches).",
        ),
    ),
    XENIA: (
        OmittedTarget(
            "Patches",
            "Xenia names patch files by the Xbox 360 title ID inside default.xex, which this plugin does not read"
            " from disc images. Configure patches in Xenia Manager.",
        ),
    ),
    SHADPS4: (
        OmittedTarget(
            "Cheats and patches",
            "shadPS4 keeps them per download source (XML patches indexed by files.json, cheat files) under its user"
            " folder, keyed by the game's serial; neither format is edited here. Use shadPS4's Cheats/Patches window.",
        ),
    ),
    XEMU: (OmittedTarget("Mods", "xemu has no mod, cheat or patch folder."),),
    CEMU: (
        OmittedTarget(
            "Turning graphic packs on",
            "Cemu enables a pack per game in its Graphic packs window (settings.xml); which packs belong to this"
            " game is in each pack's rules.txt by Wii U title ID, which is not read from Wii U images here.",
        ),
    ),
}


def not_offered(emulator: str) -> tuple[OmittedTarget, ...]:
    """The kinds of mod *emulator* supports that are not offered here, with the reason."""
    return _NOT_OFFERED.get(emulator, ())


def cemu_targets(home: EmulatorHome) -> tuple[ModTarget, ...]:
    """Cemu's graphic packs folder ``<user data>\\graphicPacks`` (``GraphicPack2::LoadAll``), shared by every game."""
    if home.data_root is None:
        return ()
    target = ModTarget(
        TARGET_GRAPHIC_PACKS,
        "Graphic packs",
        SCOPE_SHARED,
        join_path(home.data_root, "graphicPacks"),
        kind=KIND_GRAPHICS_MODS,
        notes=(
            "Shared by every Cemu game: each pack's rules.txt names the games it applies to.",
            "Turn a pack on in Cemu: right-click the game > Edit graphic packs.",
        ),
    )
    return (target,)
