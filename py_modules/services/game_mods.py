"""GameModsService — the Mods panel of a game's page: where this game's mods go, what is there, and changing it.

Owns the callables behind the panel. Every answer starts from the emulator
the game launches with right now (the same bake seam the shortcut is written
from) and the identifier its image carries, and is resolved again on every
call — a target the frontend names is looked up by id in that fresh
resolution, never taken as a path. Writes happen only through the
``GameModStore`` seam, and nothing is ever deleted: an install moves what it
replaces, and a removal moves what it takes away, into a backup folder whose
location is reported back.

Offered only when the active launcher backend is EmuDeck and a mod store is
wired (Windows); otherwise every callable answers ``unsupported``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.game_mods import (
    AZAHAR,
    DOLPHIN,
    EMULATOR_LABELS,
    IDENTIFIER_FAMILIES,
    PCSX2,
    PPSSPP,
    RETROARCH,
    SCOPE_PATCH,
    SETTING_ON,
    SETTING_UNKNOWN,
    SOURCE_UNSUPPORTED_ARCHIVE,
    EmulatorHome,
    InstallPlan,
    ModEntryInfo,
    ModTarget,
    OmittedTarget,
    PlanCheck,
    PlanRefusal,
    azahar_home,
    backup_dir,
    check_against_disk,
    core_needs_fullpath,
    dolphin_home,
    enable_setting,
    identify_mod_emulator,
    join_path,
    patch_file_names,
    path_dirname,
    pcsx2_home,
    plan_dirs,
    plan_fingerprint,
    plan_install,
    ppsspp_home,
    read_setting,
    removable_name,
    retroarch_home,
    soft_patch_target,
    source_fits,
    source_kind,
    standalone_targets,
)
from domain.launcher_backend import EMUDECK_BACKEND_ID
from domain.standalone_saves import emulator_executable
from lib.list_result import ErrorCode

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from domain.disc_ids import DiscCode
    from domain.game_mods import SettingSpec
    from services.protocols import (
        ActiveCoreReader,
        Clock,
        DebugLogger,
        DiscCodeReader,
        GameModStore,
        LaunchCommandRenderer,
        UnitOfWorkFactory,
        UuidGen,
    )

_LIST_LIMIT = 200
_SOURCE_LIMIT = 100
_PREVIEW_ROWS = 200
_NO_FOLDER = "No known mod folder for this emulator."


@dataclass(frozen=True)
class GameModsServiceConfig:
    """Frozen wiring bundle handed to ``GameModsService.__init__``.

    Carries the runtime infrastructure (loop, logger, debug logger, clock and
    UUID source for backup-folder names), the Unit-of-Work factory (the ROM and
    its install), the per-ROM active-emulator seam and the active backend's
    renderer (together: the exact command the game launches with), the active
    backend's id, the disc/cartridge identifier reader, and the mod-folder
    filesystem seam — ``None`` where the platform has none.
    """

    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    log_debug: DebugLogger
    clock: Clock
    uuid_gen: UuidGen
    uow_factory: UnitOfWorkFactory
    active_core: ActiveCoreReader
    launch_renderer: LaunchCommandRenderer
    active_backend_id: Callable[[], str]
    disc_codes: DiscCodeReader
    mod_store: GameModStore | None


@dataclass(frozen=True)
class _Context:
    """One fresh resolution of a game's mod targets."""

    emulator: str | None
    exe: str | None
    home: EmulatorHome | None
    identifier: str | None
    targets: tuple[ModTarget, ...]
    omitted: tuple[OmittedTarget, ...]
    note: str | None


def _failure(reason: str, message: str) -> dict[str, Any]:
    return {"success": False, "reason": reason, "message": message}


class GameModsService:
    """Mods panel reads (targets, sources, install preview) and writes (install, remove, enable a setting)."""

    def __init__(self, *, config: GameModsServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._log_debug = config.log_debug
        self._clock = config.clock
        self._uuid_gen = config.uuid_gen
        self._uow_factory = config.uow_factory
        self._active_core = config.active_core
        self._launch_renderer = config.launch_renderer
        self._active_backend_id = config.active_backend_id
        self._disc_codes = config.disc_codes
        self._store = config.mod_store
        self._write_lock = asyncio.Lock()

    # -- callables ---------------------------------------------------------------

    async def get_game_mods(self, rom_id: int) -> dict[str, Any]:
        """Report the game's emulator, its mod targets with what each holds, and the kinds of mod left out.

        Failure shape for an unsupported setup or a ROM that is not installed.
        An emulator with no known mod folder answers ``success`` with no
        targets and a ``note`` saying why.
        """
        return await self._loop.run_in_executor(None, self._get_game_mods_io, rom_id)

    async def list_mod_sources(self, rom_id: int, target_id: str) -> dict[str, Any]:
        """List the Downloads entries that could be installed into *target_id*, newest first."""
        return await self._loop.run_in_executor(None, self._list_mod_sources_io, rom_id, target_id)

    async def preview_mod_install(self, rom_id: int, target_id: str, source_name: str) -> dict[str, Any]:
        """Plan installing the Downloads entry *source_name* into *target_id* without writing anything.

        Answers what would be written where, which existing files would be
        backed up first, and a ``fingerprint`` the install must echo back.
        """
        return await self._loop.run_in_executor(None, self._preview_io, rom_id, target_id, source_name)

    async def install_mod(self, rom_id: int, target_id: str, source_name: str, fingerprint: str) -> dict[str, Any]:
        """Install *source_name* into *target_id* exactly as previewed.

        Plans again and refuses with ``changed`` when the plan's fingerprint
        differs from the preview's — the source, the target, or what it would
        replace moved in between. Files it replaces are moved to a backup
        folder first; a failure part-way reports how far it got.
        """
        async with self._write_lock:
            return await self._loop.run_in_executor(None, self._install_io, rom_id, target_id, source_name, fingerprint)

    async def remove_mod(self, rom_id: int, target_id: str, name: str | None) -> dict[str, Any]:
        """Move the entry *name* of *target_id* (``None``: the whole game folder) to a backup folder."""
        async with self._write_lock:
            return await self._loop.run_in_executor(None, self._remove_io, rom_id, target_id, name)

    async def enable_mod_setting(self, rom_id: int, target_id: str) -> dict[str, Any]:
        """Turn on the emulator setting that makes it load *target_id*'s content.

        Edits one key of the emulator's ini after copying the ini to a backup,
        and only while the emulator's executable is not running.
        """
        async with self._write_lock:
            return await self._loop.run_in_executor(None, self._enable_setting_io, rom_id, target_id)

    async def open_mod_folder(self, rom_id: int, target_id: str) -> dict[str, Any]:
        """Open *target_id*'s folder (or, before anything is installed, the folder it will be made in)."""
        return await self._loop.run_in_executor(None, self._open_folder_io, rom_id, target_id)

    # -- resolution ----------------------------------------------------------------

    def _resolve(self, rom_id: int) -> _Context | dict[str, Any]:
        if self._store is None or self._active_backend_id() != EMUDECK_BACKEND_ID:
            return _failure(ErrorCode.UNSUPPORTED.value, "Mods are available for EmuDeck games on Windows.")
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
        if rom is None or install is None:
            return _failure("not_installed", f"ROM {rom_id} is not installed.")
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        command = (
            self._launch_renderer.resolve_invocation({"id": rom_id, "platform_slug": rom.platform_slug}, emulator)
            if emulator is not None
            else ""
        )
        exe = emulator_executable(command)
        emulator_id = identify_mod_emulator(exe)
        if exe is None or emulator_id is None:
            return _Context(None, exe, None, None, (), (), _NO_FOLDER)
        home = self._home(emulator_id, exe)
        if home.data_root is None:
            return _Context(emulator_id, exe, home, None, (), (), f"{_NO_FOLDER} {home.reason}.")
        if emulator_id == RETROARCH:
            core_so = emulator.core_so if emulator is not None else None
            info = join_path(home.data_root, "info", f"{core_so}.info") if core_so else None
            fullpath = core_needs_fullpath(self._load_text(info)) if info else None
            target, omitted = soft_patch_target(
                home, install.file_path, single_file=install.rom_dir is None, needs_fullpath=fullpath
            )
            note = None if target is not None else _NO_FOLDER
            targets = (target,) if target is not None else ()
            return _Context(emulator_id, exe, home, None, targets, (omitted,) if omitted else (), note)
        code = self._disc_codes.read_disc_code(install.file_path, IDENTIFIER_FAMILIES[emulator_id])
        targets, omitted = standalone_targets(home, code)
        if not targets:
            note = f"{_NO_FOLDER} The game's ID could not be read from its file, and mod folders are named by it."
            return _Context(emulator_id, exe, home, None, (), omitted, note)
        return _Context(emulator_id, exe, home, _code_text(code), targets, omitted, None)

    def _home(self, emulator_id: str, exe: str) -> EmulatorHome:
        store = self._require_store()
        exe_dir = path_dirname(exe)
        if emulator_id == DOLPHIN:
            user = join_path(exe_dir, "User")
            return dolphin_home(
                exe,
                portable=store.is_file(join_path(exe_dir, "portable.txt")),
                user_dir_exists=store.is_dir(user),
                dolphin_ini=self._load_text(join_path(user, "Config", "Dolphin.ini")),
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
                portable_txt=self._load_text(portable_txt),
                pcsx2_ini=self._load_text(join_path(exe_dir, "inis", "PCSX2.ini")),
            )
        if emulator_id == AZAHAR:
            return azahar_home(exe, user_dir_exists=store.is_dir(join_path(exe_dir, "user")))
        return retroarch_home(exe)

    def _load_text(self, path: str) -> str | None:
        store = self._require_store()
        return store.load_text(path) if store.is_file(path) else None

    def _require_store(self) -> GameModStore:
        if self._store is None:
            raise RuntimeError("GameModsService used without a mod store")
        return self._store

    def _target(self, rom_id: int, target_id: str) -> tuple[_Context, ModTarget] | dict[str, Any]:
        context = self._resolve(rom_id)
        if isinstance(context, dict):
            return context
        target = next((t for t in context.targets if t.target_id == target_id), None)
        if target is None:
            return _failure(ErrorCode.NOT_FOUND.value, f"This game has no '{target_id}' mod folder.")
        return (context, target)

    def _stamp(self) -> str:
        return f"{self._clock.now().strftime('%Y%m%d-%H%M%S')}-{self._uuid_gen.uuid4()[:8]}"

    # -- reads ---------------------------------------------------------------------

    def _get_game_mods_io(self, rom_id: int) -> dict[str, Any]:
        context = self._resolve(rom_id)
        if isinstance(context, dict):
            return context
        return {
            "success": True,
            "emulator": _emulator_view(context),
            "game_id": context.identifier,
            "targets": [self._target_view(context, t) for t in context.targets],
            "omitted": [{"label": o.label, "reason": o.reason} for o in context.omitted],
            "note": context.note,
        }

    def _target_view(self, context: _Context, target: ModTarget) -> dict[str, Any]:
        store = self._require_store()
        exists = store.is_dir(target.path)
        if target.scope == SCOPE_PATCH and target.patch_stem is not None:
            installed, truncated = store.stat_names(target.path, patch_file_names(target.patch_stem)), False
        elif exists:
            installed, truncated = store.list_folder(target.path, _LIST_LIMIT)
        else:
            installed, truncated = [], False
        return {
            "target_id": target.target_id,
            "label": target.label,
            "scope": target.scope,
            "path": target.path,
            "exists": exists,
            "game_folder": target.game_folder,
            "notes": list(target.notes),
            "installed": [_entry_view(e) for e in installed],
            "installed_truncated": truncated,
            "setting": self._setting_view(context, target.setting),
            "accepts": "patch" if target.scope == SCOPE_PATCH else "archive_or_folder",
        }

    def _setting_view(self, context: _Context, spec: SettingSpec | None) -> dict[str, Any] | None:
        if spec is None or context.home is None or context.home.data_root is None:
            return None
        path = join_path(context.home.data_root, *spec.ini.split("/"))
        store = self._require_store()
        present = store.is_file(path)
        text = store.load_text(path) if present else None
        if present and text is None:
            state, editable = SETTING_UNKNOWN, False
        else:
            state, editable = read_setting(text, spec)
        return {
            "label": spec.label,
            "file": path,
            "section": spec.section,
            "key": spec.key,
            "state": state,
            "can_enable": editable and state != SETTING_ON,
        }

    def _list_mod_sources_io(self, rom_id: int, target_id: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        _context, target = found
        store = self._require_store()
        folder = store.downloads_folder()
        if not store.is_dir(folder):
            return _failure(ErrorCode.NOT_FOUND.value, f"The Downloads folder was not found at {folder}.")
        entries, truncated = store.list_sources(folder, _SOURCE_LIMIT)
        listed = []
        for entry in entries:
            kind = source_kind(entry.name, is_dir=entry.is_dir)
            if source_fits(target, kind):
                listed.append({**_entry_view(entry), "kind": kind, "supported": kind != SOURCE_UNSUPPORTED_ARCHIVE})
        return {"success": True, "folder": folder, "entries": listed, "truncated": truncated}

    def _plan(self, target: ModTarget, source_name: str) -> tuple[str, InstallPlan, PlanCheck, str] | dict[str, Any]:
        store = self._require_store()
        path = store.source_path(source_name)
        if path is None:
            return _failure(ErrorCode.NOT_FOUND.value, f"'{source_name}' is not in the Downloads folder.")
        kind = source_kind(source_name, is_dir=store.is_dir(path))
        if kind == SOURCE_UNSUPPORTED_ARCHIVE:
            return _failure(ErrorCode.UNSUPPORTED.value, "Only .zip archives can be installed; extract it first.")
        if not source_fits(target, kind):
            return _failure(ErrorCode.UNSUPPORTED.value, f"'{source_name}' cannot be installed as {target.label}.")
        stamp = store.source_stamp(path)
        try:
            entries = store.read_source_entries(path)
        except (OSError, ValueError) as exc:
            return _failure("unreadable_source", f"'{source_name}' could not be read: {exc}")
        if stamp is None:
            return _failure(ErrorCode.NOT_FOUND.value, f"'{source_name}' is gone.")
        plan = plan_install(target, entries)
        if isinstance(plan, PlanRefusal):
            return _failure(plan.reason, plan.message)
        kinds = store.probe_kinds(target.path, (*plan_dirs(plan), *(w.dest for w in plan.writes)))
        check = check_against_disk(plan, kinds)
        if check.blocked:
            shown = ", ".join(check.blocked[:5])
            return _failure("conflict", f"A folder and a file of the same name are in the way: {shown}.")
        return (path, plan, check, plan_fingerprint(stamp, plan, check))

    def _preview_io(self, rom_id: int, target_id: str, source_name: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        planned = self._plan(target, source_name)
        if isinstance(planned, dict):
            return planned
        _path, plan, check, fingerprint = planned
        data_root = context.home.data_root if context.home else None
        return {
            "success": True,
            "destination": target.path,
            "source": source_name,
            "writes": [
                {"path": w.dest, "size": w.size, "replaces": w.dest in check.replaces}
                for w in plan.writes[:_PREVIEW_ROWS]
            ],
            "write_count": len(plan.writes),
            "total_bytes": plan.total_bytes,
            "replace_count": len(check.replaces),
            "stripped_folder": plan.stripped_folder,
            "backup_root": join_path(data_root, "romm-mod-backups") if data_root else None,
            "fingerprint": fingerprint,
        }

    # -- writes --------------------------------------------------------------------

    def _install_io(self, rom_id: int, target_id: str, source_name: str, fingerprint: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        planned = self._plan(target, source_name)
        if isinstance(planned, dict):
            return planned
        path, plan, check, current = planned
        if current != fingerprint:
            return _failure("changed", "The file or the mod folder changed since the preview; review it again.")
        if context.home is None or context.home.data_root is None:
            return _failure(ErrorCode.UNSUPPORTED.value, _NO_FOLDER)
        backup = backup_dir(context.home.data_root, self._stamp(), target.target_id)
        outcome = self._require_store().install(path, target.path, plan.writes, check.replaces, backup)
        backup_folder = backup if outcome.backed_up else None
        if outcome.error is not None:
            self._logger.warning("mods: install of %r into %s stopped: %s", source_name, target.path, outcome.error)
            where = f" Replaced files are in {backup}." if outcome.backed_up else ""
            return {
                "success": False,
                "reason": "partial",
                "message": f"Stopped after {outcome.written} of {len(plan.writes)} files: {outcome.error}.{where}",
                "written": outcome.written,
                "backup_folder": backup_folder,
            }
        self._log_debug(f"mods: installed {outcome.written} files of {source_name!r} into {target.path}")
        return {
            "success": True,
            "destination": target.path,
            "written": outcome.written,
            "backed_up": outcome.backed_up,
            "backup_folder": backup_folder,
        }

    def _remove_io(self, rom_id: int, target_id: str, name: str | None) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        entry = removable_name(target, name)
        if entry is None or context.home is None or context.home.data_root is None:
            return _failure(ErrorCode.NOT_FOUND.value, f"'{name}' is not an entry of {target.label}.")
        store = self._require_store()
        whole = name is None
        root = target.path
        exists = store.is_dir(root) if whole else bool(store.stat_names(root, (entry,)))
        if not exists:
            return _failure(ErrorCode.NOT_FOUND.value, f"'{entry}' is not in {target.path}.")
        backup = join_path(backup_dir(context.home.data_root, self._stamp(), target.target_id), entry)
        removed = target.path if whole else join_path(target.path, entry)
        try:
            store.move_to_backup(root, "" if whole else entry, backup)
        except (OSError, ValueError) as exc:
            return _failure("io_error", f"Could not move {removed} to the backup folder: {exc}")
        self._logger.info("mods: moved %s to %s", removed, backup)
        return {"success": True, "removed": removed, "backup_folder": backup}

    def _enable_setting_io(self, rom_id: int, target_id: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        spec = target.setting
        if spec is None or context.home is None or context.home.data_root is None or context.exe is None:
            return _failure(ErrorCode.UNSUPPORTED.value, "This mod folder has no setting to turn on.")
        store = self._require_store()
        path = join_path(context.home.data_root, *spec.ini.split("/"))
        text = self._load_text(path)
        new_text = enable_setting(text, spec) if text is not None else None
        if text is None or new_text is None:
            return _failure("setting_unavailable", f"{path} could not be edited safely; change it in the emulator.")
        exe_name = context.exe.replace("\\", "/").rsplit("/", 1)[-1].lower()
        running = store.running_executable_names()
        if running is not None and exe_name in running:
            label = EMULATOR_LABELS.get(context.emulator or "", "The emulator")
            return _failure("emulator_running", f"{label} is running. Close it first, then try again.")
        name = spec.ini.rsplit("/", 1)[-1]
        backup = join_path(backup_dir(context.home.data_root, self._stamp(), "settings"), name)
        try:
            changed = store.replace_text(path, text, new_text, backup)
        except (OSError, ValueError) as exc:
            return _failure("io_error", f"Could not update {path}: {exc}")
        if not changed:
            return _failure("changed", f"{path} changed while it was being edited; nothing was written.")
        self._logger.info("mods: set [%s] %s in %s (backup %s)", spec.section, spec.key, path, backup)
        return {"success": True, "file": path, "backup_path": backup}

    def _open_folder_io(self, rom_id: int, target_id: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        _context, target = found
        store = self._require_store()
        folder = next((p for p in (target.path, target.base_dir) if store.is_dir(p)), None)
        if folder is None:
            return _failure(ErrorCode.NOT_FOUND.value, f"{target.path} does not exist yet.")
        if not store.open_folder(folder):
            return _failure("open_failed", f"Could not open {folder}.")
        return {"success": True, "folder": folder}


def _code_text(code: DiscCode | None) -> str | None:
    return code.code if code is not None else None


def _emulator_view(context: _Context) -> dict[str, Any] | None:
    if context.exe is None:
        return None
    label = EMULATOR_LABELS.get(context.emulator or "") or context.exe.replace("\\", "/").rsplit("/", 1)[-1]
    return {"id": context.emulator, "label": label, "exe": context.exe}


def _entry_view(entry: ModEntryInfo) -> dict[str, Any]:
    return {
        "name": entry.name,
        "is_dir": entry.is_dir,
        "size": entry.size,
        "files": entry.files,
        "modified": entry.modified,
        "partial": entry.partial,
    }
