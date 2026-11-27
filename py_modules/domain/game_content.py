"""A game's updates and DLC: where each emulator keeps them, what is installed, and how one is added.

Every target answers exactly from facts already read, or is left out with the
reason; nothing here ever touches a base game, and an install that replaces
something takes the backup leg like any mod install.

- **Azahar (3DS):** updates and DLC are installed titles in the emulated SD card,
  ``<user>\\sdmc\\Nintendo 3DS\\<32 zeros>\\<32 zeros>\\title\\<high>\\<low>`` with high
  ``0004000e`` (update) or ``0004008c`` (DLC) and the game's low title ID
  (``Service::AM::GetTitlePath``, ``GetMediaTitlePath``; ``SYSTEM_ID`` /
  ``SDCARD_ID`` in ``fs/archive.h``). They are added by Azahar itself:
  ``azahar.exe -i <file.cia>`` installs one CIA and exits, 0 on success and
  ``InstallStatus + 2`` otherwise (``citra_qt.cpp``).
- **shadPS4 (PS4):** an update is the folder ``<game folder>-UPDATE`` (or
  ``-patch``) beside the game, and mods ``<game folder>-mods``, both laid over the
  game read-only (``MntPoints::Mount``, ``OverlayPath`` in ``core/file_sys/fs.cpp``).
- **RPCS3 (PS3):** an installed update is the game's folder under
  ``dev_hdd0\\game\\<SERIAL>``; its ``PARAM.SFO`` carries the version.
- **Xenia Canary (Xbox 360):** installed content is extracted below
  ``<content>\\<XUID>\\<TitleID>\\<type>`` — title updates under XUID 0, type
  ``000B0000``, DLC under XUID 0, type ``00000002``
  (``ContentManager::ResolvePackageRoot``).

No I/O. Pure functions only.
"""

from __future__ import annotations

from domain.game_mods import (
    KIND_DLC,
    KIND_LAYERED_FS,
    KIND_UPDATE,
    SCOPE_GAME,
    SCOPE_INSTALL,
    SCOPE_READONLY,
    ModTarget,
    OmittedTarget,
    join_path,
    path_dirname,
)

TARGET_CONTENT = "content"
TARGET_UPDATE = "update"
TARGET_DLC = "dlc"
TARGET_OVERLAY_MODS = "overlay_mods"

INSTALLER_AZAHAR_CIA = "azahar_cia"
AZAHAR_INSTALL_ERRORS: dict[int, str] = {
    3: "Azahar could not open the file.",
    4: "Azahar could not find the file.",
    5: "The install was aborted.",
    6: "The CIA is not valid.",
    7: "The CIA is encrypted; Azahar installs decrypted CIAs (or encrypted ones when its AES keys are set up).",
    8: "Azahar could not check the bundle.",
}
"""``azahar.exe -i`` exit codes: ``Service::AM::InstallStatus`` + 2 (``am.h``, ``citra_qt.cpp``)."""

_SD_ID = "0" * 32
_UPDATE_HIGH = "0004000e"
_DLC_HIGH = "0004008c"
_XENIA_COMMON_XUID = "0000000000000000"
_XENIA_TITLE_UPDATE = "000B0000"
_XENIA_MARKETPLACE = "00000002"


def azahar_content_target(user_dir: str, title_id: str) -> ModTarget:
    """Installing a CIA (the game's update or a DLC) through Azahar, watching the two title folders it fills."""
    title_root = join_path(user_dir, "sdmc", "Nintendo 3DS", _SD_ID, _SD_ID, "title")
    low = title_id[8:].lower()
    watch = (("Update", join_path(title_root, _UPDATE_HIGH, low)), ("DLC", join_path(title_root, _DLC_HIGH, low)))
    return ModTarget(
        TARGET_CONTENT,
        "Updates & DLC (.cia)",
        SCOPE_INSTALL,
        title_root,
        kind=KIND_UPDATE,
        installer=INSTALLER_AZAHAR_CIA,
        watch=watch,
        notes=(
            "Installed by Azahar itself (azahar.exe -i), into its emulated SD card; the game file is not touched.",
            "An update or DLC already installed is copied to the backup folder first.",
            "Close Azahar first.",
        ),
    )


def ps4_game_root(rom_path: str, is_dir: bool) -> str | None:
    """The PS4 game folder shadPS4 mounts as ``/app0``: the folder itself, or the folder of an ``eboot.bin``."""
    if is_dir:
        return rom_path.rstrip("\\/")
    if rom_path.replace("\\", "/").lower().endswith("/eboot.bin"):
        return path_dirname(rom_path)
    return None


def shadps4_targets(game_root: str, *, update_version: str | None, game_version: str | None) -> tuple[ModTarget, ...]:
    """The update folder ``<game>-UPDATE`` and the mods folder ``<game>-mods`` beside a PS4 game folder."""
    base = path_dirname(game_root)
    name = game_root.replace("\\", "/").rsplit("/", 1)[-1]
    versions = []
    if game_version:
        versions.append(f"Game version {game_version}.")
    if update_version:
        versions.append(f"Installed update: version {update_version}.")
    update = ModTarget(
        TARGET_UPDATE,
        "Game update (extracted folder)",
        SCOPE_GAME,
        base,
        game_folder=f"{name}-UPDATE",
        kind=KIND_UPDATE,
        replace_whole=True,
        strip_names=(f"{name}-patch", name),
        notes=(
            *versions,
            "Install an update already extracted to a folder (with sce_sys\\param.sfo); shadPS4 lays it over the game.",
            "An update already there is moved to the backup folder first; the game folder is never changed.",
        ),
    )
    mods = ModTarget(
        TARGET_OVERLAY_MODS,
        "Mods (file replacements)",
        SCOPE_GAME,
        base,
        game_folder=f"{name}-mods",
        kind=KIND_LAYERED_FS,
        strip_names=(name,),
        notes=("Files here replace the game's own files of the same path, without changing the game folder.",),
    )
    return (update, mods)


def rpcs3_update_target(dev_hdd0: str, serial: str, *, installed_version: str | None) -> ModTarget:
    """The game's installed PS3 update folder, shown with its version; installing is left to RPCS3."""
    shown = f"Installed update: version {installed_version}." if installed_version else "No update is installed."
    return ModTarget(
        TARGET_UPDATE,
        "Game update",
        SCOPE_READONLY,
        join_path(dev_hdd0, "game", serial),
        kind=KIND_UPDATE,
        notes=(shown,),
    )


RPCS3_UPDATE_NOT_OFFERED = OmittedTarget(
    "Downloading and installing PS3 updates",
    "Sony's update server (a0.ww.np.dl.playstation.net) presents a certificate that cannot be verified, and the"
    " package hashes come from that same unverified answer, so updates are not fetched here. RPCS3 installs packages"
    " only through its desktop window (File > Install Packages/Raps/Edats), which stays open and needs a mouse.",
)


def xenia_content_targets(content_root: str, title_id: str) -> tuple[ModTarget, ...]:
    """The game's installed title updates and DLC, extracted below Xenia's content folder, shown read-only."""
    root = join_path(content_root, _XENIA_COMMON_XUID, title_id)
    note = "Xenia installs these by extracting the package (File > Install Content); they are only listed here."
    return (
        ModTarget(
            TARGET_UPDATE,
            "Title updates",
            SCOPE_READONLY,
            join_path(root, _XENIA_TITLE_UPDATE),
            kind=KIND_UPDATE,
            notes=(note,),
        ),
        ModTarget(TARGET_DLC, "DLC", SCOPE_READONLY, join_path(root, _XENIA_MARKETPLACE), kind=KIND_DLC, notes=(note,)),
    )


XENIA_CONTENT_NOT_OFFERED = OmittedTarget(
    "Installing title updates and DLC",
    "Xenia reads installed content as extracted folders it writes itself; installing a package is done in Xenia"
    " (File > Install Content) or Xenia Manager.",
)
