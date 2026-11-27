"""Where a game's mods go under the emulator it launches with, and how an install is planned.

A mod folder is named exactly from facts read off the machine — the emulator
executable the game's launch command runs, that emulator's portable layout, its
own settings file, and the identifier the game image carries
(:mod:`domain.disc_ids`) — never guessed. When any of those cannot be read, the
answer is "no known mod folder", with the reason, rather than a likely path.

This module owns that derivation, the reading and single-key editing of the
switches that make an emulator load what is placed there, and the plan of an
install: which entries of an archive or folder are written where, refused
outright when any entry could land outside the target. Probing the disk,
reading the image and moving files are the adapters' job; everything here is
pure.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import hashlib
import ntpath
import posixpath
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from domain.disc_ids import N3DS, NINTENDO_OPTICAL, PS2, PSP, WII, DiscCode
from domain.standalone_saves import DOLPHIN, PCSX2, PPSSPP

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

AZAHAR = "azahar"
RETROARCH = "retroarch"
CEMU = "cemu"
RPCS3 = "rpcs3"
XENIA = "xenia"
SHADPS4 = "shadps4"
XEMU = "xemu"

SCOPE_GAME = "game"
"""The folder is this game's own (named by its identifier); everything in it belongs to the game."""
SCOPE_SHARED = "shared"
"""The folder is shared by every game of the emulator; what is in it may belong to other games."""
SCOPE_PATCH = "patch"
"""Soft-patch files beside the ROM, named after the ROM's own file stem."""
SCOPE_FILE = "file"
"""One file named for this game (``file_name``) in a folder every game of the emulator shares."""
SCOPE_TOGGLE = "toggle"
"""Entries the emulator already has, switched on or off in its own settings; nothing is installed or removed."""

KIND_FILES = "files"
KIND_CHEAT_FILE = "cheatFile"
KIND_BUILTIN_TOGGLE = "builtinToggle"
KIND_RIIVOLUTION = "riivolution"
KIND_GRAPHICS_MODS = "graphicsMods"
KIND_LAYERED_FS = "layeredFs"

TARGET_TEXTURES = "textures"
TARGET_GRAPHIC_MODS = "graphic_mods"
TARGET_RIIVOLUTION = "riivolution"
TARGET_MODS = "mods"
TARGET_SOFT_PATCH = "soft_patch"
TARGET_CHEATS = "cheats"
TARGET_CHEAT_CODES = "cheat_codes"
TARGET_PATCHES = "patches"
TARGET_GECKO = "gecko_codes"
TARGET_ACTION_REPLAY = "action_replay_codes"
TARGET_GRAPHIC_PACKS = "graphic_packs"

SOURCE_ZIP = "zip"
SOURCE_FOLDER = "folder"
SOURCE_PATCH = "patch"
SOURCE_CHEAT = "cheat"
SOURCE_UNSUPPORTED_ARCHIVE = "unsupported_archive"

CHEAT_EXTENSIONS: tuple[str, ...] = (".txt", ".pnach", ".cht")
"""Single cheat files a Downloads entry can be: Azahar ``.txt``, PCSX2 ``.pnach``, RetroArch ``.cht``."""

PATCH_EXTENSIONS: tuple[str, ...] = (".ips", ".bps", ".ups")
"""Patch formats this plugin installs. RetroArch tries them in this order (atlas ``PATCH_FORMATS``)."""
LISTED_PATCH_EXTENSIONS: tuple[str, ...] = (*PATCH_EXTENSIONS, ".xdelta")
_PATCH_CONTINUATIONS = tuple(range(1, 10))
_UNSUPPORTED_ARCHIVES = (".7z", ".rar")

BACKUP_FOLDER = "romm-mod-backups"
"""Folder under an emulator's data root that holds everything an install replaced or a removal took away."""

MAX_ARCHIVE_ENTRIES = 200_000
MAX_INSTALL_BYTES = 64 * 1024**3

# Lower-cased executable-name prefixes, as EmuDeck for Windows installs them.
_EXE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("retroarch", RETROARCH),
    ("dolphin", DOLPHIN),
    ("ppsspp", PPSSPP),
    ("pcsx2", PCSX2),
    ("azahar", AZAHAR),
    ("citra", AZAHAR),
    ("lime3ds", AZAHAR),
    ("cemu", CEMU),
    ("rpcs3", RPCS3),
    ("xenia", XENIA),
    ("shadps4", SHADPS4),
    ("xemu", XEMU),
)

EMULATOR_LABELS: dict[str, str] = {
    RETROARCH: "RetroArch",
    DOLPHIN: "Dolphin",
    PPSSPP: "PPSSPP",
    PCSX2: "PCSX2",
    AZAHAR: "Azahar",
    CEMU: "Cemu",
    RPCS3: "RPCS3",
    XENIA: "Xenia Canary",
    SHADPS4: "shadPS4",
    XEMU: "xemu",
}

IDENTIFIER_FAMILIES: dict[str, str] = {DOLPHIN: NINTENDO_OPTICAL, PPSSPP: PSP, PCSX2: PS2, AZAHAR: N3DS}
"""The emulators whose mod folder is named by the game image's identifier, and the family each reads."""

# Formats a soft patch can never apply to: RetroArch patches only the content it
# loads into memory (atlas placement ``SoftPatchAnswer``), and these are opened
# from disk by every core that reads them. Content inside an archive is patched
# under the inner file's name, which the ROM's own file name does not tell.
_NOT_SOFT_PATCHABLE = frozenset(
    {
        ".zip", ".7z", ".rar", ".cue", ".bin", ".chd", ".iso", ".img", ".ccd", ".mds", ".m3u", ".pbp",
        ".cso", ".gdi", ".cdi", ".rvz", ".gcm", ".wbfs", ".wia",
    }
)  # fmt: skip

_ID6_RE = re.compile(r"^[0-9A-Z]{6}$")
_PSP_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")
_PS2_SERIAL_RE = re.compile(r"^[A-Z]{4}-\d{5}$")
_TITLE_ID_RE = re.compile(r"^[0-9A-F]{16}$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_WINDOWS_BAD_CHARS = frozenset('<>:"|?*')


def identify_mod_emulator(exe_path: str | None) -> str | None:
    """The emulator an executable path is, by its file name, or ``None`` for one this module does not know."""
    if not exe_path:
        return None
    name = re.split(r"[\\/]", exe_path)[-1].lower()
    for prefix, emulator in _EXE_PREFIXES:
        if name.startswith(prefix):
            return emulator
    return None


def path_dirname(path: str) -> str:
    """The folder of an executable path given in either Windows or POSIX spelling."""
    return ntpath.dirname(path) if "\\" in path else posixpath.dirname(path)


# -- settings switches ---------------------------------------------------------


@dataclass(frozen=True)
class SettingSpec:
    """One ini key that makes an emulator load what a mod folder holds.

    ``ini`` is relative to the emulator's data root, ``/``-separated.
    ``default_on`` is what the emulator does when the key is absent.
    """

    label: str
    ini: str
    section: str
    key: str
    on_value: str
    default_on: bool


DOLPHIN_HIRES_TEXTURES = SettingSpec(
    label="Load Custom Textures",
    ini="Config/GFX.ini",
    section="Settings",
    key="HiresTextures",
    on_value="True",
    default_on=False,
)
"""Dolphin ``Config::GFX_HIRES_TEXTURES`` (``Source/Core/Core/Config/GraphicsSettings.cpp``), off by default."""

PPSSPP_REPLACE_TEXTURES = SettingSpec(
    label="Replace textures",
    ini="PSP/SYSTEM/ppsspp.ini",
    section="Graphics",
    key="ReplaceTextures",
    on_value="True",
    default_on=True,
)
"""PPSSPP ``g_Config.bReplaceTextures`` (``Core/Config.cpp``, graphics section), on by default."""

PCSX2_LOAD_TEXTURE_REPLACEMENTS = SettingSpec(
    label="Load Texture Replacements",
    ini="inis/PCSX2.ini",
    section="EmuCore/GS",
    key="LoadTextureReplacements",
    on_value="true",
    default_on=False,
)
"""PCSX2 ``GSOptions::LoadTextureReplacements`` (``pcsx2/Config.h``), off by default."""

SETTING_ON = "on"
SETTING_OFF = "off"
SETTING_UNKNOWN = "unknown"

_SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_KEY_RE = re.compile(r"^(\s*)([^=;#\[\s][^=]*?)(\s*=\s*)(.*?)(\s*)$")
_COMMENT_RE = re.compile(r"^\s*([;#].*)?$")


@dataclass(frozen=True)
class _IniLine:
    kind: str  # "blank" | "section" | "key"
    section: str
    key: str = ""
    value: str = ""


def _ini_lines(text: str) -> list[_IniLine] | None:
    """Every line classified, or ``None`` when a line is none of blank/comment/section/key."""
    lines: list[_IniLine] = []
    section = ""
    for raw in text.splitlines():
        header = _SECTION_RE.match(raw)
        if header:
            section = header.group(1).strip()
            lines.append(_IniLine("section", section))
            continue
        if _COMMENT_RE.match(raw):
            lines.append(_IniLine("blank", section))
            continue
        pair = _KEY_RE.match(raw)
        if pair is None:
            return None
        lines.append(_IniLine("key", section, pair.group(2).strip(), pair.group(4)))
    return lines


def _ini_well_formed(lines: list[_IniLine]) -> bool:
    """No section header twice, and no key twice within a section (names compared case-insensitively)."""
    sections: set[str] = set()
    keys: set[tuple[str, str]] = set()
    for line in lines:
        if line.kind == "section":
            if line.section.lower() in sections:
                return False
            sections.add(line.section.lower())
        elif line.kind == "key":
            ident = (line.section.lower(), line.key.lower())
            if ident in keys:
                return False
            keys.add(ident)
    return True


def read_setting(text: str | None, spec: SettingSpec) -> tuple[str, bool]:
    """``(state, editable)`` of *spec* in the ini *text*.

    *text* ``None`` means the file does not exist: the emulator's default
    applies, and the file is not edited (it is the emulator's to create).
    ``state`` is :data:`SETTING_ON` / :data:`SETTING_OFF`, or
    :data:`SETTING_UNKNOWN` for a value that is not a boolean word or a file
    that does not parse; ``editable`` is whether :func:`enable_setting` can
    change this file safely.
    """
    default = SETTING_ON if spec.default_on else SETTING_OFF
    if text is None:
        return (default, False)
    lines = _ini_lines(text)
    if lines is None or not _ini_well_formed(lines):
        return (SETTING_UNKNOWN, False)
    for line in lines:
        if line.kind == "key" and line.section.lower() == spec.section.lower() and line.key.lower() == spec.key.lower():
            value = line.value.strip().lower()
            if value == "true":
                return (SETTING_ON, True)
            if value == "false":
                return (SETTING_OFF, True)
            return (SETTING_UNKNOWN, False)
    return (default, True)


def enable_setting(text: str, spec: SettingSpec) -> str | None:
    """*text* with exactly the key *spec* names set to its on value, or ``None`` when that is not safe.

    Only that one line changes: an existing key keeps its spelling and spacing
    and gets the new value; an absent key is added as the last line of its
    section, or in a new section appended at the end. Line endings follow the
    file's own. ``None`` for a file :func:`read_setting` would not call
    editable.
    """
    lines = _ini_lines(text)
    if lines is None or not _ini_well_formed(lines):
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    raw_lines = text.splitlines()
    target_section = spec.section.lower()
    section_end: int | None = None
    in_section = False
    for index, line in enumerate(lines):
        if line.kind == "section":
            in_section = line.section.lower() == target_section
            if in_section:
                section_end = index
            continue
        if not in_section:
            continue
        if line.kind == "key" and line.key.lower() == spec.key.lower():
            match = _KEY_RE.match(raw_lines[index])
            if match is None:
                return None
            raw_lines[index] = f"{match.group(1)}{match.group(2)}{match.group(3)}{spec.on_value}{match.group(5)}"
            return _join_ini(raw_lines, newline, text)
        if line.kind == "key":
            section_end = index
    new_line = f"{spec.key} = {spec.on_value}"
    if section_end is None:
        if raw_lines and raw_lines[-1].strip():
            raw_lines.append("")
        raw_lines.extend([f"[{spec.section}]", new_line])
    else:
        raw_lines.insert(section_end + 1, new_line)
    return _join_ini(raw_lines, newline, text)


def _join_ini(lines: list[str], newline: str, original: str) -> str:
    joined = newline.join(lines)
    return joined + newline if original.endswith(("\n", "\r")) or not original else joined


def ini_value(text: str | None, section: str, key: str) -> str | None:
    """The raw value of ``[section] key`` in *text* (case-insensitive names), or ``None`` when absent."""
    if text is None:
        return None
    lines = _ini_lines(text) or []
    for line in lines:
        if line.kind == "key" and line.section.lower() == section.lower() and line.key.lower() == key.lower():
            return line.value.strip()
    return None


# -- emulator homes --------------------------------------------------------------


@dataclass(frozen=True)
class EmulatorHome:
    """Where one emulator keeps its data on this machine, or why that is not known.

    ``data_root`` is the folder its settings files are relative to (Dolphin's
    ``User``, PPSSPP's ``memstick``, PCSX2's portable folder, Azahar's
    ``user``, RetroArch's own folder); ``None`` with ``reason`` when the
    layout could not be read exactly. ``folders`` carries the mod roots read
    from its settings (Dolphin's load folder, PCSX2's textures folder).
    """

    emulator: str
    exe: str
    data_root: str | None
    reason: str | None = None
    folders: Mapping[str, str] = field(default_factory=dict)


def dolphin_home(exe: str, *, portable: bool, user_dir_exists: bool, dolphin_ini: str | None) -> EmulatorHome:
    """Dolphin's ``User`` folder and load folder.

    Dolphin on Windows uses ``<exe folder>\\User`` exactly when ``portable.txt``
    sits beside the executable (``UICommon::SetUserDirectory``); otherwise the
    folder comes from the registry or Documents, which is not read here. The
    load folder is ``[General] LoadPath`` of ``Config\\Dolphin.ini`` when set
    to an absolute path, else ``User\\Load``.
    """
    exe_dir = path_dirname(exe)
    if not portable:
        return EmulatorHome(DOLPHIN, exe, None, "Dolphin is not a portable install (no portable.txt beside its exe)")
    user = join_path(exe_dir, "User")
    if not user_dir_exists:
        return EmulatorHome(DOLPHIN, exe, None, f"Dolphin's User folder was not found at {user}")
    load_path = ini_value(dolphin_ini, "General", "LoadPath")
    if load_path:
        if not is_absolute_path(load_path):
            return EmulatorHome(DOLPHIN, exe, None, f"Dolphin's custom load path {load_path!r} is not absolute")
        load = load_path.rstrip("\\/")
    else:
        load = join_path(user, "Load")
    return EmulatorHome(DOLPHIN, exe, user, folders={"load": load})


def ppsspp_home(exe: str, *, installed_marker: bool, memstick_exists: bool) -> EmulatorHome:
    """PPSSPP's memory stick folder: ``<exe folder>\\memstick`` unless ``installed.txt`` moves it.

    PPSSPP on Windows reads ``installed.txt`` beside the executable to switch to
    a Documents (or named) folder (``InitMemstickDirectory``), which is not read here.
    """
    exe_dir = path_dirname(exe)
    if installed_marker:
        return EmulatorHome(PPSSPP, exe, None, "PPSSPP keeps its memory stick elsewhere (installed.txt beside the exe)")
    memstick = join_path(exe_dir, "memstick")
    if not memstick_exists:
        return EmulatorHome(PPSSPP, exe, None, f"PPSSPP's memstick folder was not found at {memstick}")
    return EmulatorHome(PPSSPP, exe, memstick)


def pcsx2_home(exe: str, *, portable_marker: bool, portable_txt: str | None, pcsx2_ini: str | None) -> EmulatorHome:
    """PCSX2's portable data folder and textures folder.

    Portable when ``portable.ini`` or an empty ``portable.txt`` sits beside the
    executable (``EmuFolders::SetDataDirectory``); a ``portable.txt`` naming
    another folder is not followed. The textures folder is ``[Folders]
    Textures`` of ``inis\\PCSX2.ini``: absolute as written, relative to the
    data folder otherwise, ``textures`` when unset.
    """
    exe_dir = path_dirname(exe)
    if not portable_marker:
        return EmulatorHome(PCSX2, exe, None, "PCSX2 is not a portable install (no portable.ini/portable.txt)")
    if portable_txt is not None and portable_txt.strip():
        return EmulatorHome(PCSX2, exe, None, "PCSX2's portable.txt names another data folder")
    if pcsx2_ini is None:
        return EmulatorHome(PCSX2, exe, None, "PCSX2's inis\\PCSX2.ini was not found")
    textures = ini_value(pcsx2_ini, "Folders", "Textures") or "textures"
    textures_dir = (
        textures.rstrip("\\/") if is_absolute_path(textures) else join_path(exe_dir, *re.split(r"[\\/]", textures))
    )
    return EmulatorHome(PCSX2, exe, exe_dir, folders={"textures": textures_dir})


def azahar_home(exe: str, *, user_dir_exists: bool) -> EmulatorHome:
    """Azahar's (or Citra's / Lime3DS's) ``user`` folder: portable when it sits beside the executable."""
    user = join_path(path_dirname(exe), "user")
    if not user_dir_exists:
        return EmulatorHome(AZAHAR, exe, None, f"no portable user folder beside the emulator ({user})")
    return EmulatorHome(AZAHAR, exe, user)


def retroarch_home(exe: str) -> EmulatorHome:
    """RetroArch's own folder, where its ``info`` files and this plugin's mod backups live."""
    return EmulatorHome(RETROARCH, exe, path_dirname(exe))


def is_absolute_path(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith(("\\\\", "/"))


def join_path(base: str, *parts: str) -> str:
    """Join with the separator *base* is written in, so Windows paths stay Windows paths on any host."""
    sep = "\\" if "\\" in base or re.match(r"^[A-Za-z]:", base) else "/"
    return sep.join([base.rstrip("\\/"), *parts])


# -- targets ---------------------------------------------------------------------


@dataclass(frozen=True)
class ModTarget:
    """One place mods for this game go.

    For :data:`SCOPE_GAME`, ``path`` is ``base_dir`` plus the game's own
    folder ``game_folder``; for :data:`SCOPE_SHARED` it is ``base_dir``; for
    :data:`SCOPE_PATCH` it is the ROM's folder, and ``patch_stem`` is the
    ROM's file stem every patch is named after; for :data:`SCOPE_FILE` it is
    the shared folder ``file_name`` is written into, from a source holding one
    file ending in ``file_ext``; for :data:`SCOPE_TOGGLE` it is the folder of
    the file a switch edits, described by ``toggle``. ``required_prefix`` is
    the sub-folder inside the game folder the emulator actually reads from.
    ``kind`` is what the target offers, for a caller choosing how to show it.
    """

    target_id: str
    label: str
    scope: str
    base_dir: str
    game_folder: str | None = None
    required_prefix: str | None = None
    patch_stem: str | None = None
    setting: SettingSpec | None = None
    notes: tuple[str, ...] = ()
    kind: str = KIND_FILES
    file_name: str | None = None
    file_ext: str | None = None
    toggle: ToggleSource | None = None

    @property
    def path(self) -> str:
        """The folder this target writes into."""
        return join_path(self.base_dir, self.game_folder) if self.game_folder else self.base_dir


@dataclass(frozen=True)
class ToggleSource:
    """Where a :data:`SCOPE_TOGGLE` target's entries are read from and the one file a switch writes.

    ``format`` names the reader in :mod:`domain.mod_toggles`. ``read_files``
    are read in order for the entries (shipped files first); ``user_files``
    are the user's own files of the same format (Dolphin merges them);
    ``scan_dir`` with ``scan_prefixes`` lists files whose names start with a
    prefix and end in ``.pnach`` (PCSX2); ``zip_file`` / ``zip_members`` are a
    shipped archive and the members tried in order. ``write_file`` is the only
    file a switch changes.
    """

    format: str
    write_file: str
    read_files: tuple[str, ...] = ()
    user_files: tuple[str, ...] = ()
    scan_dir: str | None = None
    scan_prefixes: tuple[str, ...] = ()
    zip_file: str | None = None
    zip_members: tuple[str, ...] = ()


@dataclass(frozen=True)
class OmittedTarget:
    """A kind of mod the emulator supports that is not offered here, and why."""

    label: str
    reason: str


def valid_identifier(emulator: str, code: DiscCode | None) -> str | None:
    """The identifier that names *emulator*'s per-game folder for *code*, validated, or ``None``."""
    if code is None:
        return None
    patterns = {DOLPHIN: _ID6_RE, PPSSPP: _PSP_ID_RE, PCSX2: _PS2_SERIAL_RE, AZAHAR: _TITLE_ID_RE}
    pattern = patterns.get(emulator)
    return code.code if pattern is not None and pattern.match(code.code) else None


def standalone_targets(
    home: EmulatorHome, code: DiscCode | None
) -> tuple[tuple[ModTarget, ...], tuple[OmittedTarget, ...]]:
    """The mod targets of a disc/cartridge game under a standalone emulator whose home was found.

    - Dolphin: texture packs in ``<load>\\Textures\\<ID6>``; graphics mods in
      ``<load>\\GraphicMods`` (shared); Wii only, Riivolution in
      ``<load>\\Riivolution`` (shared).
    - PPSSPP: texture packs in ``<memstick>\\PSP\\TEXTURES\\<GAME ID>``.
    - PCSX2: texture replacements in ``<textures>\\<SERIAL>\\replacements``
      (cheats and patches, named by the boot ELF's CRC, are in
      :mod:`domain.mod_targets`).
    - Azahar: LayeredFS/code mods in ``<user>\\load\\mods\\<TITLE ID>`` and
      custom textures in ``<user>\\load\\textures\\<TITLE ID>``.
    """
    identifier = valid_identifier(home.emulator, code)
    root = home.data_root
    if root is None or identifier is None or code is None:
        return ((), ())
    if home.emulator == DOLPHIN:
        load = home.folders["load"]
        targets = [
            ModTarget(
                TARGET_TEXTURES,
                "Texture pack",
                SCOPE_GAME,
                join_path(load, "Textures"),
                game_folder=identifier,
                setting=DOLPHIN_HIRES_TEXTURES,
            ),
            ModTarget(
                TARGET_GRAPHIC_MODS,
                "Graphics mods",
                SCOPE_SHARED,
                join_path(load, "GraphicMods"),
                kind=KIND_GRAPHICS_MODS,
                notes=(
                    "Shared by every Dolphin game: each mod's own metadata names the games it applies to.",
                    "Dolphin also needs Graphics > Advanced > Enable Graphics Mods, which is not checked here.",
                ),
            ),
        ]
        if code.platform == WII:
            targets.append(
                ModTarget(
                    TARGET_RIIVOLUTION,
                    "Riivolution patches",
                    SCOPE_SHARED,
                    join_path(load, "Riivolution"),
                    kind=KIND_RIIVOLUTION,
                    notes=(
                        "Shared by every Wii game. Pick the patch in Dolphin with right-click > Start with Riivolution"
                        " Patches.",
                    ),
                )
            )
        return (tuple(targets), ())
    if home.emulator == PPSSPP:
        target = ModTarget(
            TARGET_TEXTURES,
            "Texture pack",
            SCOPE_GAME,
            join_path(root, "PSP", "TEXTURES"),
            game_folder=identifier,
            setting=PPSSPP_REPLACE_TEXTURES,
        )
        return ((target,), ())
    if home.emulator == PCSX2:
        target = ModTarget(
            TARGET_TEXTURES,
            "Texture replacements",
            SCOPE_GAME,
            home.folders["textures"],
            game_folder=identifier,
            required_prefix="replacements",
            setting=PCSX2_LOAD_TEXTURE_REPLACEMENTS,
            notes=("PCSX2 reads replacement textures from the game folder's 'replacements' sub-folder.",),
        )
        return ((target,), ())
    if home.emulator == AZAHAR:
        load = join_path(root, "load")
        targets = (
            ModTarget(
                TARGET_MODS,
                "Mods (romfs / exefs)",
                SCOPE_GAME,
                join_path(load, "mods"),
                game_folder=identifier,
                kind=KIND_LAYERED_FS,
                notes=("A mod keeps its own 'romfs' and/or 'exefs' folders inside the game folder.",),
            ),
            ModTarget(
                TARGET_TEXTURES,
                "Custom textures",
                SCOPE_GAME,
                join_path(load, "textures"),
                game_folder=identifier,
                notes=("The emulator's 'Use custom textures' setting is not checked here.",),
            ),
        )
        return (targets, ())
    return ((), ())


def core_needs_fullpath(info_text: str | None) -> bool | None:
    """A RetroArch core ``.info`` file's ``needs_fullpath``, or ``None`` when it does not state one."""
    value = ini_value(info_text, "", "needs_fullpath")
    if value is None:
        return None
    value = value.strip().strip('"').lower()
    if value in ("true", "false"):
        return value == "true"
    return None


def soft_patch_target(
    home: EmulatorHome, rom_path: str, *, single_file: bool, needs_fullpath: bool | None
) -> tuple[ModTarget | None, OmittedTarget | None]:
    """The soft-patch target beside a RetroArch-launched ROM, or why there is none.

    RetroArch looks for ``<content basename>.ips`` / ``.bps`` / ``.ups``
    beside the content and patches it in memory (atlas placement
    ``build_soft_patch_candidates``), which only happens for a core that does
    not need the file's full path.
    """
    label = "Soft patch (.ips / .bps / .ups)"
    ext = posixpath.splitext(rom_path.replace("\\", "/"))[1].lower()
    if not single_file or ext in _NOT_SOFT_PATCHABLE:
        return (None, OmittedTarget(label, "RetroArch only soft-patches a single cartridge file loaded into memory."))
    if needs_fullpath is True:
        return (None, OmittedTarget(label, "This core reads the game from disk, so RetroArch does not patch it."))
    rom_dir = path_dirname(rom_path)
    name = re.split(r"[\\/]", rom_path)[-1]
    stem = name[: -len(ext)] if ext else name
    if not stem or home.data_root is None:
        return (None, None)
    notes = [
        "RetroArch applies the patch in memory at launch; the ROM file is not changed.",
        "Which patch formats EmuDeck's RetroArch build attempts is unverified (atlas records only RetroDECK's).",
    ]
    if needs_fullpath is None:
        notes.append("Whether this core loads the game into memory (needed for patching) is unverified.")
    return (
        ModTarget(TARGET_SOFT_PATCH, label, SCOPE_PATCH, rom_dir, patch_stem=stem, notes=tuple(notes)),
        None,
    )


def patch_file_names(stem: str) -> tuple[str, ...]:
    """Every patch file RetroArch looks for beside a ROM of file stem *stem*, with each chain's continuations."""
    names: list[str] = []
    for ext in LISTED_PATCH_EXTENSIONS:
        names.append(f"{stem}{ext}")
        names.extend(f"{stem}{ext}{index}" for index in _PATCH_CONTINUATIONS)
    return tuple(names)


# -- sources ---------------------------------------------------------------------


def source_kind(name: str, *, is_dir: bool) -> str | None:
    """How a Downloads entry can be installed: zip, folder, patch, an archive needing extraction, or ``None``."""
    if is_dir:
        return SOURCE_FOLDER
    lower = name.lower()
    if lower.endswith(".zip"):
        return SOURCE_ZIP
    if lower.endswith(PATCH_EXTENSIONS):
        return SOURCE_PATCH
    if lower.endswith(CHEAT_EXTENSIONS):
        return SOURCE_CHEAT
    if lower.endswith(_UNSUPPORTED_ARCHIVES):
        return SOURCE_UNSUPPORTED_ARCHIVE
    return None


def source_fits(target: ModTarget, kind: str | None) -> bool:
    """Whether a source of *kind* is worth listing for *target*."""
    if kind is None or target.scope == SCOPE_TOGGLE:
        return False
    if target.scope == SCOPE_FILE:
        return kind in (SOURCE_CHEAT, SOURCE_ZIP, SOURCE_UNSUPPORTED_ARCHIVE)
    if target.scope == SCOPE_PATCH:
        return kind in (SOURCE_PATCH, SOURCE_ZIP, SOURCE_UNSUPPORTED_ARCHIVE)
    return kind in (SOURCE_ZIP, SOURCE_FOLDER, SOURCE_UNSUPPORTED_ARCHIVE)


# -- install plan ----------------------------------------------------------------


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
class InstallPlan:
    """Everything an install writes, and the archive wrapper folder it dropped, if any."""

    writes: tuple[PlannedWrite, ...]
    stripped_folder: str | None = None

    @property
    def total_bytes(self) -> int:
        return sum(w.size for w in self.writes)


@dataclass(frozen=True)
class PlanRefusal:
    """Why a source cannot be installed into a target. Nothing is written for a refused plan."""

    reason: str
    message: str


def mod_entry_name(name: str) -> str | None:
    """A source entry name made safe to place below a Windows folder, or ``None``.

    Backslashes count as separators (Windows tools write them into zips). Every
    component must be a plain Windows file name: no drive, colon, ``.`` or
    ``..``, no character Windows forbids, no trailing dot or space, no reserved
    device name. A leading separator is an absolute path and is refused.
    """
    if not name or "\x00" in name:
        return None
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return None
    parts = normalized.rstrip("/").split("/")
    for part in parts:
        if part in ("", ".", ".."):
            return None
        if any(c in _WINDOWS_BAD_CHARS or ord(c) < 32 for c in part):
            return None
        if part.endswith((".", " ")):
            return None
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            return None
    return "/".join(parts)


def plan_install(target: ModTarget, entries: Sequence[SourceEntry]) -> InstallPlan | PlanRefusal:
    """Plan writing *entries* into *target*, refusing the whole source if any entry is unsafe.

    - Every name must pass :func:`mod_entry_name`; links, duplicate names
      (case-insensitive, as on Windows) and a name that is both a file and a
      folder refuse the source.
    - Game folder: a source whose every entry sits under one top-level folder
      named like the game folder (``GALE01/...``) has that folder dropped, so
      it is not nested twice; a ``required_prefix`` the emulator reads from is
      added to files not already under it.
    - Soft patch: exactly one ``.ips``/``.bps``/``.ups`` file must be in the
      source; it is written as ``<ROM stem><ext>``.
    """
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        return PlanRefusal("too_large", f"The source has more than {MAX_ARCHIVE_ENTRIES} entries.")
    files: list[tuple[str, SourceEntry]] = []
    seen: dict[str, bool] = {}
    for entry in entries:
        if entry.link:
            return PlanRefusal("unsafe_source", f"{entry.name!r} is a link; links are never installed.")
        name = mod_entry_name(entry.name)
        if name is None:
            return PlanRefusal("unsafe_source", f"{entry.name!r} is not a safe relative path.")
        key = name.lower()
        if key in seen and (seen[key] != entry.is_dir or not entry.is_dir):
            return PlanRefusal("unsafe_source", f"{entry.name!r} appears more than once.")
        seen[key] = entry.is_dir
        if not entry.is_dir:
            files.append((name, entry))
    for name, _entry in files:
        parts = name.lower().split("/")
        for depth in range(1, len(parts)):
            if seen.get("/".join(parts[:depth])) is False:
                return PlanRefusal("unsafe_source", f"{name!r} sits below a file of the same name.")
    if not files:
        return PlanRefusal("empty_source", "There are no files to install.")
    if target.scope == SCOPE_PATCH:
        return _plan_patch(target, files)
    if target.scope == SCOPE_FILE:
        return _plan_single_file(target, files)
    if target.scope == SCOPE_TOGGLE:
        return PlanRefusal("not_installable", f"{target.label} are switched on or off, not installed.")
    stripped = None
    names = [name for name, _ in files]
    if target.game_folder is not None:
        tops = {name.split("/", 1)[0].lower() for name in names}
        if tops == {target.game_folder.lower()} and all("/" in name for name in names):
            stripped = names[0].split("/", 1)[0]
            names = [name.split("/", 1)[1] for name in names]
    if target.required_prefix is not None:
        prefix = target.required_prefix
        names = [name if name.lower().startswith(prefix.lower() + "/") else f"{prefix}/{name}" for name in names]
    if len({name.lower() for name in names}) != len(names):
        return PlanRefusal("unsafe_source", "Two files of the source would land on the same name.")
    writes = tuple(PlannedWrite(entry.name, dest, entry.size) for dest, (_n, entry) in zip(names, files, strict=True))
    plan = InstallPlan(writes, stripped)
    if plan.total_bytes > MAX_INSTALL_BYTES:
        return PlanRefusal("too_large", "The source is larger than this plugin installs in one go.")
    return plan


def _plan_patch(target: ModTarget, files: list[tuple[str, SourceEntry]]) -> InstallPlan | PlanRefusal:
    patches = [(name, entry) for name, entry in files if name.lower().endswith(PATCH_EXTENSIONS)]
    if len(patches) != 1:
        found = f"{len(patches)} patch files" if patches else "no .ips/.bps/.ups file"
        return PlanRefusal("not_one_patch", f"A soft patch needs exactly one .ips/.bps/.ups file; found {found}.")
    name, entry = patches[0]
    ext = posixpath.splitext(name)[1].lower()
    return InstallPlan((PlannedWrite(entry.name, f"{target.patch_stem}{ext}", entry.size),))


def _plan_single_file(target: ModTarget, files: list[tuple[str, SourceEntry]]) -> InstallPlan | PlanRefusal:
    ext = (target.file_ext or "").lower()
    found = [(name, entry) for name, entry in files if ext and name.lower().endswith(ext)]
    if len(found) != 1 or target.file_name is None:
        what = f"{len(found)} {ext} files" if found else f"no {ext} file"
        return PlanRefusal("not_one_file", f"{target.label} needs exactly one {ext} file; found {what}.")
    _name, entry = found[0]
    return InstallPlan((PlannedWrite(entry.name, target.file_name, entry.size),))


def plan_dirs(plan: InstallPlan) -> tuple[str, ...]:
    """Every folder (``/``-relative) the plan's files need, parents first, without repeats."""
    dirs: dict[str, None] = {}
    for write in plan.writes:
        parts = write.dest.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            dirs.setdefault("/".join(parts[:depth]))
    return tuple(dirs)


@dataclass(frozen=True)
class PlanCheck:
    """How a plan meets what is already in the target: files it replaces, and what blocks it."""

    replaces: frozenset[str]
    blocked: tuple[str, ...]


def check_against_disk(plan: InstallPlan, kinds: Mapping[str, str]) -> PlanCheck:
    """Classify a plan against *kinds* — ``/``-relative path → ``"file"`` / ``"dir"`` / ``"other"`` / ``"missing"``.

    A destination that is a file is replaced (backed up first); one that is a
    folder or anything else, or a needed folder that is a file, blocks the
    install. Paths absent from *kinds* count as missing.
    """
    replaces: set[str] = set()
    blocked = [d for d in plan_dirs(plan) if kinds.get(d, "missing") not in ("dir", "missing")]
    for write in plan.writes:
        kind = kinds.get(write.dest, "missing")
        if kind == "file":
            replaces.add(write.dest)
        elif kind != "missing":
            blocked.append(write.dest)
    return PlanCheck(frozenset(replaces), tuple(blocked))


def plan_fingerprint(source_stamp: str, plan: InstallPlan, check: PlanCheck) -> str:
    """A digest of what an install would do, so the install can refuse if anything moved since the preview."""
    digest = hashlib.sha256(source_stamp.encode("utf-8"))
    for write in plan.writes:
        digest.update(f"\x00{write.source}\x01{write.dest}\x01{write.size}".encode())
    for dest in sorted(check.replaces):
        digest.update(f"\x02{dest}".encode())
    return digest.hexdigest()[:32]


def backup_dir(data_root: str, stamp: str, target_id: str) -> str:
    """The folder one install's or removal's backups go into: ``<data root>\\romm-mod-backups\\<stamp>\\<target>``."""
    return join_path(data_root, BACKUP_FOLDER, stamp, target_id)


def removable_name(target: ModTarget, name: str | None) -> str | None:
    """The entry of *target* a removal may take away, or ``None`` when *name* cannot be one.

    ``None`` as *name* means the whole game folder, allowed only for a game
    target. A soft-patch removal may take only one of the ROM's own patch
    file names; any other removal one plain entry name of the target folder.
    Whether the entry exists is for the caller to check.
    """
    if name is None:
        return target.game_folder if target.scope == SCOPE_GAME else None
    if target.scope == SCOPE_TOGGLE:
        return None
    if target.scope == SCOPE_FILE:
        return name if name == target.file_name else None
    if target.scope == SCOPE_PATCH:
        return name if target.patch_stem is not None and name in patch_file_names(target.patch_stem) else None
    return name if "/" not in name and mod_entry_name(name) == name else None


# -- shapes the filesystem seam answers in ---------------------------------------


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
