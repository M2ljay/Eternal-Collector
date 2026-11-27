"""ModTargetResolver — one fresh, exact resolution of a game's mod, cheat, patch and content targets.

Resolves from the emulator the game launches with right now (the same bake
seam the shortcut is written from), that emulator's own layout and settings,
and the identifiers the game's files carry. Every fact is read through the
injected seams; anything that cannot be read exactly leaves its target out
with the reason. Nothing here writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.console_ids import parse_param_sfo as parse_sfo
from domain.console_ids import ps3_game, ps4_game, wiiu_title_id
from domain.game_content import (
    RPCS3_UPDATE_NOT_OFFERED,
    XENIA_CONTENT_NOT_OFFERED,
    azahar_content_target,
    ps4_game_root,
    rpcs3_update_target,
    shadps4_targets,
    xenia_content_targets,
)
from domain.game_mods import (
    AZAHAR,
    CEMU,
    DOLPHIN,
    EMULATOR_LABELS,
    IDENTIFIER_FAMILIES,
    PCSX2,
    PPSSPP,
    RETROARCH,
    RPCS3,
    SHADPS4,
    XENIA,
    EmulatorHome,
    ModTarget,
    OmittedTarget,
    azahar_home,
    core_needs_fullpath,
    dolphin_home,
    identify_mod_emulator,
    ini_value,
    is_absolute_path,
    join_path,
    path_dirname,
    pcsx2_home,
    ppsspp_home,
    retroarch_home,
    soft_patch_target,
    standalone_targets,
)
from domain.launcher_backend import EMUDECK_BACKEND_ID
from domain.mod_targets import (
    azahar_cheat_targets,
    cemu_home,
    cemu_pack_target,
    cemu_targets,
    dolphin_code_targets,
    not_offered,
    pcsx2_patch_targets,
    retroarch_cheat_dir,
    retroarch_cheat_target,
    rpcs3_config_root,
    rpcs3_patch_target,
    xenia_patch_target,
)
from domain.standalone_saves import emulator_executable
from domain.xenia_patches import PATCH_FILE_RE, patch_file_title_id
from lib.list_result import ErrorCode

if TYPE_CHECKING:
    from collections.abc import Callable

    from domain.disc_ids import DiscCode
    from domain.shortcut_data import EmulatorInvocation
    from services.protocols import (
        ActiveCoreReader,
        ConsoleIdReader,
        DiscCodeReader,
        GameModStore,
        LaunchCommandRenderer,
        Ps2ElfCrcReader,
        UnitOfWorkFactory,
    )

NO_FOLDER = "No known mod folder for this emulator."
_SFO_LIMIT = 64 * 1024
_SCAN_LIMIT = 2000
_DEV_HDD0_DEFAULT = "$(EmulatorDir)dev_hdd0/"
_VFS_DEV_HDD0_RE = re.compile(r"""^\s*["']?/dev_hdd0/["']?\s*:\s*["']?(.*?)["']?\s*$""")
_XENIA_CONTENT_ROOT_RE = re.compile(r"""^\s*content_root\s*=\s*"((?:[^"\\]|\\.)*)"\s*(#.*)?$""")


def failure(reason: str, message: str) -> dict[str, Any]:
    """The canonical failure answer."""
    return {"success": False, "reason": reason, "message": message}


@dataclass(frozen=True)
class ModContext:
    """One fresh resolution of a game's targets: the emulator, its home, the game's identifier, and the targets."""

    emulator: str | None
    exe: str | None
    home: EmulatorHome | None
    identifier: str | None
    targets: tuple[ModTarget, ...]
    omitted: tuple[OmittedTarget, ...]
    note: str | None


@dataclass(frozen=True)
class ModTargetResolverConfig:
    """Frozen wiring for ``ModTargetResolver``.

    The Unit-of-Work factory (the ROM and its install), the per-ROM
    active-emulator seam and the active backend's renderer (together: the exact
    command the game launches with) and its id, the readers of identifiers in
    game files (disc codes, PS2 boot ELF CRC, PS3/Xbox 360 files), and the
    mod-folder filesystem seam — ``None`` where the platform has none.
    """

    uow_factory: UnitOfWorkFactory
    active_core: ActiveCoreReader
    launch_renderer: LaunchCommandRenderer
    active_backend_id: Callable[[], str]
    disc_codes: DiscCodeReader
    elf_crcs: Ps2ElfCrcReader
    console_ids: ConsoleIdReader
    mod_store: GameModStore | None


class ModTargetResolver:
    """Answers a game's ``ModContext`` afresh on every call, or the failure that stops it."""

    def __init__(self, *, config: ModTargetResolverConfig) -> None:
        self._uow_factory = config.uow_factory
        self._active_core = config.active_core
        self._launch_renderer = config.launch_renderer
        self._active_backend_id = config.active_backend_id
        self._disc_codes = config.disc_codes
        self._elf_crcs = config.elf_crcs
        self._console_ids = config.console_ids
        self._store = config.mod_store

    @property
    def store(self) -> GameModStore:
        """The mod-folder filesystem seam; only valid after a successful ``resolve``."""
        if self._store is None:
            raise RuntimeError("ModTargetResolver used without a mod store")
        return self._store

    def load_text(self, path: str) -> str | None:
        """The text of *path* when it is a file, else ``None``."""
        return self.store.load_text(path) if self.store.is_file(path) else None

    def target(self, rom_id: int, target_id: str) -> tuple[ModContext, ModTarget] | dict[str, Any]:
        """The game's context and its target *target_id*, or the failure."""
        context = self.resolve(rom_id)
        if isinstance(context, dict):
            return context
        found = next((t for t in context.targets if t.target_id == target_id), None)
        if found is None:
            return failure(ErrorCode.NOT_FOUND.value, f"This game has no '{target_id}' mod folder.")
        return (context, found)

    def resolve(self, rom_id: int) -> ModContext | dict[str, Any]:
        """The game's ``ModContext``; a failure for an unsupported setup or a ROM that is not installed."""
        if self._store is None or self._active_backend_id() != EMUDECK_BACKEND_ID:
            return failure(ErrorCode.UNSUPPORTED.value, "Mods are available for EmuDeck games on Windows.")
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
        if rom is None or install is None:
            return failure("not_installed", f"ROM {rom_id} is not installed.")
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        command = (
            self._launch_renderer.resolve_invocation({"id": rom_id, "platform_slug": rom.platform_slug}, emulator)
            if emulator is not None
            else ""
        )
        exe = emulator_executable(command)
        emulator_id = identify_mod_emulator(exe)
        if exe is None or emulator_id is None:
            return ModContext(None, exe, None, None, (), (), NO_FOLDER)
        rom_path = install.file_path
        if emulator_id == RPCS3:
            return self._rpcs3_context(exe, rom_path)
        if emulator_id == XENIA:
            return self._xenia_context(exe, rom_path)
        if emulator_id == SHADPS4:
            return self._shadps4_context(exe, rom_path)
        if emulator_id not in IDENTIFIER_FAMILIES and emulator_id not in (RETROARCH, CEMU):
            note = f"Nothing is offered for {EMULATOR_LABELS[emulator_id]}."
            return ModContext(emulator_id, exe, None, None, (), not_offered(emulator_id), note)
        home = self._home(emulator_id, exe)
        if home.data_root is None:
            return ModContext(emulator_id, exe, home, None, (), not_offered(emulator_id), f"{NO_FOLDER} {home.reason}.")
        if emulator_id == CEMU:
            return self._cemu_context(home, rom_path)
        if emulator_id == RETROARCH:
            return self._retroarch_context(home, emulator, rom_path, install.rom_dir is None)
        code = self._disc_codes.read_disc_code(rom_path, IDENTIFIER_FAMILIES[emulator_id])
        targets, omitted = standalone_targets(home, code)
        if not targets or code is None:
            note = f"{NO_FOLDER} The game's ID could not be read from its file, and mod folders are named by it."
            return ModContext(emulator_id, exe, home, None, (), omitted, note)
        extra, extra_omitted = self._extra_targets(home, code, rom_path)
        return ModContext(emulator_id, exe, home, code.code, targets + extra, omitted + extra_omitted, None)

    # -- per emulator -----------------------------------------------------------------

    def _retroarch_context(
        self, home: EmulatorHome, emulator: EmulatorInvocation | None, rom_path: str, single_file: bool
    ) -> ModContext:
        data_root = home.data_root or ""
        core_so = emulator.core_so if emulator is not None else None
        info_text = self.load_text(join_path(data_root, "info", f"{core_so}.info")) if core_so else None
        fullpath = core_needs_fullpath(info_text) if core_so else None
        patch, patch_omitted = soft_patch_target(home, rom_path, single_file=single_file, needs_fullpath=fullpath)
        cheat_dir, reason = retroarch_cheat_dir(data_root, self.load_text(join_path(data_root, "retroarch.cfg")))
        if cheat_dir is None:
            cheat, cheat_omitted = None, OmittedTarget("Cheat file (.cht)", reason or NO_FOLDER)
        else:
            core_name = ini_value(info_text, "", "corename")
            core_name = core_name.strip().strip('"') if core_name else None
            cheat, cheat_omitted = retroarch_cheat_target(cheat_dir, core_name, rom_path, single_file=single_file)
        targets = tuple(t for t in (patch, cheat) if t is not None)
        omitted = tuple(o for o in (patch_omitted, cheat_omitted) if o is not None)
        return ModContext(RETROARCH, home.exe, home, None, targets, omitted, None if targets else NO_FOLDER)

    def _extra_targets(
        self, home: EmulatorHome, code: DiscCode, rom_path: str
    ) -> tuple[tuple[ModTarget, ...], tuple[OmittedTarget, ...]]:
        if home.emulator == DOLPHIN:
            return (dolphin_code_targets(home, code), ())
        if home.emulator == AZAHAR:
            return (
                (*azahar_cheat_targets(home, code.code), azahar_content_target(home.data_root or "", code.code)),
                (),
            )
        if home.emulator == PCSX2:
            crc = self._elf_crcs.read_ps2_elf_crc(rom_path)
            if crc.text is None:
                reason = f"PCSX2 names these by the boot executable's CRC, which could not be read: {crc.reason}."
                return ((), (OmittedTarget("Cheats and patches (.pnach)", reason),))
            ini = self.load_text(join_path(home.data_root or "", "inis", "PCSX2.ini"))
            return (pcsx2_patch_targets(home, ini, code.code, crc.text), ())
        return ((), ())

    def _cemu_context(self, home: EmulatorHome, rom_path: str) -> ModContext:
        title_id = self._wiiu_title_id(rom_path)
        targets = cemu_targets(home)
        omitted: tuple[OmittedTarget, ...] = not_offered(CEMU)
        if title_id is None:
            omitted += (
                OmittedTarget(
                    "Switching graphic packs",
                    "The game's Wii U title ID could not be read: it is read from meta\\meta.xml of a game stored as a"
                    " folder; .wua, .wud and .wux images are not read here. Switch packs in Cemu.",
                ),
            )
        elif (packs := cemu_pack_target(home, title_id)) is not None:
            targets += (packs,)
        return ModContext(CEMU, home.exe, home, title_id, targets, omitted, None)

    def _wiiu_title_id(self, rom_path: str) -> str | None:
        folder = rom_path if self.store.is_dir(rom_path) else path_dirname(rom_path)
        for _ in range(3):
            title_id = wiiu_title_id(self.load_text(join_path(folder, "meta", "meta.xml")))
            if title_id is not None:
                return title_id
            folder = path_dirname(folder)
        return None

    def _rpcs3_context(self, exe: str, rom_path: str) -> ModContext:
        root = rpcs3_config_root(exe, portable_dir_exists=self.store.is_dir(join_path(path_dirname(exe), "portable")))
        game = ps3_game(self._ps3_sfo(rom_path))
        home = EmulatorHome(RPCS3, exe, root)
        if game is None:
            note = "The game's serial could not be read (from PS3_GAME\\PARAM.SFO), and RPCS3 names patches by it."
            return ModContext(RPCS3, exe, home, None, (), (RPCS3_UPDATE_NOT_OFFERED,), note)
        omitted: list[OmittedTarget] = [RPCS3_UPDATE_NOT_OFFERED]
        targets: list[ModTarget] = []
        dev_hdd0, reason = self._rpcs3_dev_hdd0(root)
        update_version = None
        if dev_hdd0 is None:
            omitted.append(OmittedTarget("Installed update", reason or "dev_hdd0 could not be found"))
        else:
            installed = ps3_game(self._sfo_file(join_path(dev_hdd0, "game", game.serial, "PARAM.SFO")))
            update_version = installed.app_version if installed is not None else None
            targets.append(rpcs3_update_target(dev_hdd0, game.serial, installed_version=update_version))
        targets.insert(0, rpcs3_patch_target(root, game.serial, update_version or game.app_version))
        return ModContext(RPCS3, exe, home, game.serial, tuple(targets), tuple(omitted), None)

    def _ps3_sfo(self, rom_path: str) -> dict[str, str] | None:
        if rom_path.lower().endswith(".iso"):
            data = self._console_ids.read_iso_member(rom_path, ("PS3_GAME", "PARAM.SFO"), _SFO_LIMIT)
            return parse_sfo(data) if data is not None else None
        folder = rom_path if self.store.is_dir(rom_path) else path_dirname(rom_path)
        for _ in range(4):
            for candidate in (join_path(folder, "PS3_GAME", "PARAM.SFO"), join_path(folder, "PARAM.SFO")):
                sfo = self._sfo_file(candidate)
                if sfo is not None:
                    return sfo
            folder = path_dirname(folder)
        return None

    def _sfo_file(self, path: str) -> dict[str, str] | None:
        data = self.store.read_bytes(path, _SFO_LIMIT) if self.store.is_file(path) else None
        return parse_sfo(data) if data is not None else None

    def _rpcs3_dev_hdd0(self, root: str) -> tuple[str | None, str | None]:
        """``dev_hdd0`` under the config root, unless ``config\\vfs.yml`` moves it (then the reason)."""
        vfs = self.load_text(join_path(root, "config", "vfs.yml"))
        for line in (vfs or "").splitlines():
            match = _VFS_DEV_HDD0_RE.match(line)
            if match and match.group(1) not in ("", _DEV_HDD0_DEFAULT):
                return (None, f"RPCS3's vfs.yml moves dev_hdd0 to {match.group(1)!r}, which is not followed here")
        return (join_path(root, "dev_hdd0"), None)

    def _xenia_context(self, exe: str, rom_path: str) -> ModContext:
        root = path_dirname(exe)
        home = EmulatorHome(XENIA, exe, root)
        path = join_path(rom_path, "default.xex") if self.store.is_dir(rom_path) else rom_path
        answer = self._console_ids.read_xbox360_title_id(path)
        if answer.title_id is None:
            note = (
                f"The game's title ID could not be read ({answer.reason}), and Xenia names patches and content by it."
            )
            return ModContext(XENIA, exe, home, None, (), (XENIA_CONTENT_NOT_OFFERED,), note)
        title_id = answer.title_id
        targets: list[ModTarget] = []
        omitted: list[OmittedTarget] = [XENIA_CONTENT_NOT_OFFERED]
        files = self._xenia_patch_files(root, title_id)
        if files:
            targets.append(xenia_patch_target(root, title_id, files))
        else:
            omitted.append(OmittedTarget("Game patches", f"No patch file for {title_id} is in {root}\\patches."))
        content_root, reason = self._xenia_content_root(root)
        if content_root is None:
            omitted.append(OmittedTarget("Installed title updates and DLC", reason or "not found"))
        else:
            targets.extend(xenia_content_targets(content_root, title_id))
        return ModContext(XENIA, exe, home, title_id, tuple(targets), tuple(omitted), None)

    def _xenia_patch_files(self, root: str, title_id: str) -> tuple[str, ...]:
        folder = join_path(root, "patches")
        names = [
            n
            for n in self.store.list_file_names(folder, _SCAN_LIMIT)
            if PATCH_FILE_RE.match(n) and n[:8].upper() == title_id
        ]
        paths = (join_path(folder, n) for n in sorted(names, key=str.lower))
        return tuple(p for p in paths if patch_file_title_id(self.load_text(p) or "") == title_id)

    def _xenia_content_root(self, root: str) -> tuple[str | None, str | None]:
        """``content_root`` of ``xenia-canary.config.toml`` when set and absolute, else ``<root>\\content``."""
        config = self.load_text(join_path(root, "xenia-canary.config.toml"))
        for line in (config or "").splitlines():
            match = _XENIA_CONTENT_ROOT_RE.match(line)
            if match and match.group(1):
                value = match.group(1).replace("\\\\", "\\")
                if not is_absolute_path(value):
                    return (None, f"Xenia's content_root {value!r} is not an absolute folder")
                return (value.rstrip("\\/"), None)
        return (join_path(root, "content"), None)

    def _shadps4_context(self, exe: str, rom_path: str) -> ModContext:
        root = ps4_game_root(rom_path, self.store.is_dir(rom_path))
        home = EmulatorHome(SHADPS4, exe, path_dirname(exe))
        if root is None:
            note = "shadPS4's update and mod folders sit beside a game folder; this game is not a folder or eboot.bin."
            return ModContext(SHADPS4, exe, home, None, (), not_offered(SHADPS4), note)
        game = ps4_game(self._sfo_file(join_path(root, "sce_sys", "param.sfo")))
        update = ps4_game(self._sfo_file(join_path(f"{root}-UPDATE", "sce_sys", "param.sfo")))
        if update is None:
            update = ps4_game(self._sfo_file(join_path(f"{root}-patch", "sce_sys", "param.sfo")))
        targets = shadps4_targets(
            root,
            update_version=update.app_version if update else None,
            game_version=game.app_version if game else None,
        )
        return ModContext(SHADPS4, exe, home, game.serial if game else None, targets, not_offered(SHADPS4), None)

    def _home(self, emulator_id: str, exe: str) -> EmulatorHome:
        store = self.store
        exe_dir = path_dirname(exe)
        if emulator_id == DOLPHIN:
            user = join_path(exe_dir, "User")
            return dolphin_home(
                exe,
                portable=store.is_file(join_path(exe_dir, "portable.txt")),
                user_dir_exists=store.is_dir(user),
                dolphin_ini=self.load_text(join_path(user, "Config", "Dolphin.ini")),
            )
        if emulator_id == PPSSPP:
            return ppsspp_home(
                exe,
                installed_marker=store.is_file(join_path(exe_dir, "installed.txt")),
                memstick_exists=store.is_dir(join_path(exe_dir, "memstick")),
            )
        if emulator_id == PCSX2:
            portable_txt = join_path(exe_dir, "portable.txt")
            return pcsx2_home(
                exe,
                portable_marker=store.is_file(join_path(exe_dir, "portable.ini")) or store.is_file(portable_txt),
                portable_txt=self.load_text(portable_txt),
                pcsx2_ini=self.load_text(join_path(exe_dir, "inis", "PCSX2.ini")),
            )
        if emulator_id == AZAHAR:
            return azahar_home(exe, user_dir_exists=store.is_dir(join_path(exe_dir, "user")))
        if emulator_id == CEMU:
            return cemu_home(
                exe,
                portable_dir_exists=store.is_dir(join_path(exe_dir, "portable")),
                settings_beside_exe=store.is_file(join_path(exe_dir, "settings.xml")),
            )
        return retroarch_home(exe)
