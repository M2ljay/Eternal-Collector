"""GameModsService — the Mods panel of a game's page: where this game's mods go, what is there, and changing it.

Owns the callables behind the panel. Every answer starts from a fresh
resolution (``ModTargetResolver``) — a target the frontend names is looked up
by id in it, never taken as a path. Writes happen only through the
``GameModStore`` seam, and nothing is ever deleted: an install moves (or, when
an emulator's installer writes, copies) what it replaces, a removal moves what
it takes away, into a backup folder whose location is reported back, and a
switch of a built-in entry copies the file it edits first.

Offered only when the active launcher backend is EmuDeck and a mod store is
wired (Windows); otherwise every callable answers ``unsupported``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from domain.game_content import AZAHAR_INSTALL_ERRORS, INSTALLER_AZAHAR_CIA
from domain.game_mods import (
    EMULATOR_LABELS,
    SCOPE_FILE,
    SCOPE_INSTALL,
    SCOPE_PATCH,
    SCOPE_READONLY,
    SCOPE_TOGGLE,
    SETTING_ON,
    SETTING_UNKNOWN,
    SOURCE_UNSUPPORTED_ARCHIVE,
    InstallPlan,
    ModEntryInfo,
    ModTarget,
    PlanCheck,
    PlanRefusal,
    backup_dir,
    check_against_disk,
    enable_setting,
    join_path,
    patch_file_names,
    path_dirname,
    plan_dirs,
    plan_fingerprint,
    plan_install,
    read_setting,
    removable_name,
    source_fits,
    source_kind,
)
from lib.list_result import ErrorCode
from services.game_mods.targets import (
    NO_FOLDER,
    ModContext,
    ModTargetResolver,
    ModTargetResolverConfig,
    failure,
)
from services.game_mods.toggles import ToggleEditor, ToggleEditorConfig

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from domain.game_mods import SettingSpec, ToggleSource
    from domain.mod_toggles import ToggleEntry
    from services.protocols import (
        ActiveCoreReader,
        Clock,
        ConsoleIdReader,
        DebugLogger,
        DiscCodeReader,
        GameModStore,
        LaunchCommandRenderer,
        Ps2ElfCrcReader,
        UnitOfWorkFactory,
        UuidGen,
        YamlCodec,
    )

_LIST_LIMIT = 200
_SOURCE_LIMIT = 100
_PREVIEW_ROWS = 200
_INSTALLER_TIMEOUT = 30 * 60.0
_ACCEPTS = {
    SCOPE_PATCH: "patch",
    SCOPE_FILE: "cheat_file",
    SCOPE_TOGGLE: "none",
    SCOPE_INSTALL: "cia_file",
    SCOPE_READONLY: "none",
}


@dataclass(frozen=True)
class GameModsServiceConfig:
    """Frozen wiring bundle handed to ``GameModsService.__init__``.

    Carries the runtime infrastructure (loop, logger, debug logger, clock and
    UUID source for backup-folder names), the Unit-of-Work factory (the ROM and
    its install), the per-ROM active-emulator seam and the active backend's
    renderer (together: the exact command the game launches with), the active
    backend's id, the readers of identifiers in game files (disc codes, a PS2
    image's boot ELF CRC, PS3 and Xbox 360 files), the mod-folder filesystem
    seam — ``None`` where the platform has none — and the YAML codec RPCS3's
    patch files are read and written with.
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
    elf_crcs: Ps2ElfCrcReader
    console_ids: ConsoleIdReader
    yaml: YamlCodec


class GameModsService:
    """Mods panel reads (targets, sources, previews, built-in entries) and writes (install, remove, switch)."""

    def __init__(self, *, config: GameModsServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._log_debug = config.log_debug
        self._clock = config.clock
        self._uuid_gen = config.uuid_gen
        self._resolver = ModTargetResolver(
            config=ModTargetResolverConfig(
                uow_factory=config.uow_factory,
                active_core=config.active_core,
                launch_renderer=config.launch_renderer,
                active_backend_id=config.active_backend_id,
                disc_codes=config.disc_codes,
                elf_crcs=config.elf_crcs,
                console_ids=config.console_ids,
                mod_store=config.mod_store,
            )
        )
        self._toggles = ToggleEditor(config=ToggleEditorConfig(mod_store=config.mod_store, yaml=config.yaml))
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

    async def list_mod_builtins(self, rom_id: int, target_id: str) -> dict[str, Any]:
        """List the entries a built-in-toggle target has (codes, cheats, patches) with whether each is on.

        ``editable`` is false, with ``reason``, when the files are laid out in
        a way a switch could be misread; each entry's ``can_toggle`` says
        whether that one can be switched.
        """
        return await self._loop.run_in_executor(None, self._list_builtins_io, rom_id, target_id)

    async def set_mod_builtin(self, rom_id: int, target_id: str, entry_id: str, enabled: bool) -> dict[str, Any]:
        """Switch one entry of a built-in-toggle target on or off.

        Edits only the lines that carry that entry's state in the one file the
        target names, after copying the file to a backup; refused while the
        emulator is running and when the file changed since it was read.
        """
        async with self._write_lock:
            return await self._loop.run_in_executor(None, self._set_builtin_io, rom_id, target_id, entry_id, enabled)

    async def open_mod_folder(self, rom_id: int, target_id: str) -> dict[str, Any]:
        """Open *target_id*'s folder (or, before anything is installed, the folder it will be made in)."""
        return await self._loop.run_in_executor(None, self._open_folder_io, rom_id, target_id)

    # -- shared -------------------------------------------------------------------

    def _resolve(self, rom_id: int) -> ModContext | dict[str, Any]:
        return self._resolver.resolve(rom_id)

    def _target(self, rom_id: int, target_id: str) -> tuple[ModContext, ModTarget] | dict[str, Any]:
        return self._resolver.target(rom_id, target_id)

    def _require_store(self) -> GameModStore:
        return self._resolver.store

    def _load_text(self, path: str) -> str | None:
        return self._resolver.load_text(path)

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

    def _target_view(self, context: ModContext, target: ModTarget) -> dict[str, Any]:
        store = self._require_store()
        exists = store.is_dir(target.path)
        if target.scope == SCOPE_PATCH and target.patch_stem is not None:
            installed, truncated = store.stat_names(target.path, patch_file_names(target.patch_stem)), False
        elif target.scope == SCOPE_FILE and target.file_name is not None:
            installed, truncated = store.stat_names(target.path, (target.file_name,)), False
        elif target.scope == SCOPE_TOGGLE:
            installed, truncated = [], False
        elif target.scope == SCOPE_INSTALL:
            installed, truncated = self._watched(target), False
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
            "accepts": _ACCEPTS.get(target.scope, "archive_or_folder"),
            "kind": target.kind,
            "file_name": target.file_name,
        }

    def _watched(self, target: ModTarget) -> list[ModEntryInfo]:
        """The folders an installer target fills that exist, each named by its label (``Update``, ``DLC``)."""
        store = self._require_store()
        found = []
        for label, path in target.watch:
            entries = store.stat_names(path_dirname(path), (_base(path),)) if store.is_dir(path) else []
            found.extend(replace(e, name=label) for e in entries)
        return found

    def _setting_view(self, context: ModContext, spec: SettingSpec | None) -> dict[str, Any] | None:
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
            return failure(ErrorCode.NOT_FOUND.value, f"The Downloads folder was not found at {folder}.")
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
            return failure(ErrorCode.NOT_FOUND.value, f"'{source_name}' is not in the Downloads folder.")
        kind = source_kind(source_name, is_dir=store.is_dir(path))
        if kind == SOURCE_UNSUPPORTED_ARCHIVE:
            return failure(ErrorCode.UNSUPPORTED.value, "Only .zip archives can be installed; extract it first.")
        if not source_fits(target, kind):
            return failure(ErrorCode.UNSUPPORTED.value, f"'{source_name}' cannot be installed as {target.label}.")
        stamp = store.source_stamp(path)
        try:
            entries = store.read_source_entries(path)
        except (OSError, ValueError) as exc:
            return failure("unreadable_source", f"'{source_name}' could not be read: {exc}")
        if stamp is None:
            return failure(ErrorCode.NOT_FOUND.value, f"'{source_name}' is gone.")
        plan = plan_install(target, entries)
        if isinstance(plan, PlanRefusal):
            return failure(plan.reason, plan.message)
        if target.scope == SCOPE_INSTALL:
            return (path, plan, PlanCheck(frozenset(), ()), plan_fingerprint(stamp, plan, PlanCheck(frozenset(), ())))
        if target.replace_whole:
            existing = store.source_stamp(target.path) if store.is_dir(target.path) else None
            empty = PlanCheck(frozenset(), ())
            return (path, plan, empty, plan_fingerprint(f"{stamp}|{existing}", plan, empty))
        kinds = store.probe_kinds(target.path, (*plan_dirs(plan), *(w.dest for w in plan.writes)))
        check = check_against_disk(plan, kinds)
        if check.blocked:
            shown = ", ".join(check.blocked[:5])
            return failure("conflict", f"A folder and a file of the same name are in the way: {shown}.")
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
            "replaces_folder": target.replace_whole and self._require_store().is_dir(target.path),
            "installer": target.installer,
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
            return failure("changed", "The file or the mod folder changed since the preview; review it again.")
        if context.home is None or context.home.data_root is None:
            return failure(ErrorCode.UNSUPPORTED.value, NO_FOLDER)
        backup = backup_dir(context.home.data_root, self._stamp(), target.target_id)
        if target.scope == SCOPE_INSTALL:
            return self._run_installer(context, target, path, backup)
        if target.replace_whole and self._require_store().is_dir(target.path):
            moved = self._move_existing(target, backup)
            if moved is not None:
                return moved
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

    def _move_existing(self, target: ModTarget, backup: str) -> dict[str, Any] | None:
        """Move the target's existing folder (an update) to the backup before a whole-folder install."""
        try:
            self._require_store().move_to_backup(target.path, "", join_path(backup, target.game_folder or "folder"))
        except (OSError, ValueError) as exc:
            return failure("io_error", f"Could not move {target.path} to the backup folder: {exc}")
        self._logger.info("mods: moved %s to %s before installing", target.path, backup)
        return None

    def _run_installer(self, context: ModContext, target: ModTarget, source: str, backup: str) -> dict[str, Any]:
        """Install *source* with the emulator's own installer, after copying what it may replace to the backup."""
        if target.installer != INSTALLER_AZAHAR_CIA or context.exe is None:
            return failure(ErrorCode.UNSUPPORTED.value, f"{target.label} has no installer here.")
        running = self._running_refusal(context)
        if running is not None:
            return running
        store = self._require_store()
        backed_up = 0
        for label, folder in target.watch:
            if store.is_dir(folder):
                try:
                    store.copy_to_backup(folder, join_path(backup, label))
                except (OSError, ValueError) as exc:
                    return failure("io_error", f"Could not back up {folder}: {exc}")
                backed_up += 1
        code, output = store.run_installer(context.exe, ("-i", source), _INSTALLER_TIMEOUT)
        backup_folder = backup if backed_up else None
        if code != 0:
            reason = AZAHAR_INSTALL_ERRORS.get(code or -1) or (output.strip()[:200] or "it did not finish")
            self._logger.warning("mods: Azahar install of %s failed (%s): %s", source, code, output.strip()[:500])
            return {
                "success": False,
                "reason": "installer_failed",
                "message": f"Azahar did not install it: {reason}",
                "backup_folder": backup_folder,
            }
        self._log_debug(f"mods: Azahar installed {source}")
        return {
            "success": True,
            "destination": target.path,
            "written": 1,
            "backed_up": backed_up,
            "backup_folder": backup_folder,
        }

    def _remove_io(self, rom_id: int, target_id: str, name: str | None) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        entry = removable_name(target, name)
        if entry is None or context.home is None or context.home.data_root is None:
            return failure(ErrorCode.NOT_FOUND.value, f"'{name}' is not an entry of {target.label}.")
        store = self._require_store()
        whole = name is None
        root = target.path
        exists = store.is_dir(root) if whole else bool(store.stat_names(root, (entry,)))
        if not exists:
            return failure(ErrorCode.NOT_FOUND.value, f"'{entry}' is not in {target.path}.")
        backup = join_path(backup_dir(context.home.data_root, self._stamp(), target.target_id), entry)
        removed = target.path if whole else join_path(target.path, entry)
        try:
            store.move_to_backup(root, "" if whole else entry, backup)
        except (OSError, ValueError) as exc:
            return failure("io_error", f"Could not move {removed} to the backup folder: {exc}")
        self._logger.info("mods: moved %s to %s", removed, backup)
        return {"success": True, "removed": removed, "backup_folder": backup}

    def _enable_setting_io(self, rom_id: int, target_id: str) -> dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        spec = target.setting
        if spec is None or context.home is None or context.home.data_root is None or context.exe is None:
            return failure(ErrorCode.UNSUPPORTED.value, "This mod folder has no setting to turn on.")
        store = self._require_store()
        path = join_path(context.home.data_root, *spec.ini.split("/"))
        text = self._load_text(path)
        new_text = enable_setting(text, spec) if text is not None else None
        if text is None or new_text is None:
            return failure("setting_unavailable", f"{path} could not be edited safely; change it in the emulator.")
        running = self._running_refusal(context)
        if running is not None:
            return running
        name = spec.ini.rsplit("/", 1)[-1]
        backup = join_path(backup_dir(context.home.data_root, self._stamp(), "settings"), name)
        try:
            changed = store.replace_text(path, text, new_text, backup)
        except (OSError, ValueError) as exc:
            return failure("io_error", f"Could not update {path}: {exc}")
        if not changed:
            return failure("changed", f"{path} changed while it was being edited; nothing was written.")
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
            return failure(ErrorCode.NOT_FOUND.value, f"{target.path} does not exist yet.")
        if not store.open_folder(folder):
            return failure("open_failed", f"Could not open {folder}.")
        return {"success": True, "folder": folder}

    # -- built-in toggles ----------------------------------------------------------

    def _toggle_target(
        self, rom_id: int, target_id: str
    ) -> tuple[ModContext, ModTarget, ToggleSource] | dict[str, Any]:
        found = self._target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target = found
        if target.toggle is None:
            return failure(ErrorCode.UNSUPPORTED.value, f"{target.label} has no entries to switch.")
        return (context, target, target.toggle)

    def _list_builtins_io(self, rom_id: int, target_id: str) -> dict[str, Any]:
        found = self._toggle_target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target, source = found
        listing = self._toggles.state(source).listing
        return {
            "success": True,
            "target_id": target.target_id,
            "file": source.write_file,
            "editable": listing.editable,
            "reason": listing.reason,
            "entries": [_toggle_view(e) for e in listing.entries],
            "setting": self._setting_view(context, target.setting),
        }

    def _set_builtin_io(self, rom_id: int, target_id: str, entry_id: str, enabled: bool) -> dict[str, Any]:
        found = self._toggle_target(rom_id, target_id)
        if isinstance(found, dict):
            return found
        context, target, source = found
        state = self._toggles.state(source)
        entry = next((e for e in state.listing.entries if e.entry_id == entry_id), None)
        if entry is None:
            return failure(ErrorCode.NOT_FOUND.value, f"{target.label} has no entry {entry_id!r}.")
        if not state.listing.editable or not entry.can_toggle:
            return failure("not_editable", state.listing.reason or f"{entry.name!r} cannot be switched here.")
        if entry.enabled == enabled:
            return {"success": True, "file": source.write_file, "backup_path": None, "enabled": enabled}
        running = self._running_refusal(context)
        if running is not None:
            return running
        new_text = self._toggles.switched_text(source, state, entry_id, enabled)
        if new_text is None:
            message = f"{source.write_file} could not be edited safely; change it in the emulator."
            return failure("not_editable", message)
        return self._write_toggle(context, source.write_file, state.written, new_text, enabled)

    def _running_refusal(self, context: ModContext) -> dict[str, Any] | None:
        if context.exe is None:
            return None
        exe_name = _base(context.exe).lower()
        running = self._require_store().running_executable_names()
        if running is not None and exe_name in running:
            label = EMULATOR_LABELS.get(context.emulator or "", "The emulator")
            return failure("emulator_running", f"{label} is running. Close it first, then try again.")
        return None

    def _write_toggle(
        self, context: ModContext, path: str, text: str | None, new_text: str, enabled: bool
    ) -> dict[str, Any]:
        store = self._require_store()
        if context.home is None or context.home.data_root is None:
            return failure(ErrorCode.UNSUPPORTED.value, NO_FOLDER)
        try:
            if text is None:
                if not store.create_text(path, new_text):
                    return failure("changed", f"{path} appeared while it was being edited; nothing was written.")
                backup = None
            else:
                backup = join_path(backup_dir(context.home.data_root, self._stamp(), "settings"), _base(path))
                if not store.replace_text(path, text, new_text, backup):
                    return failure("changed", f"{path} changed while it was being edited; nothing was written.")
        except (OSError, ValueError) as exc:
            return failure("io_error", f"Could not update {path}: {exc}")
        self._logger.info("mods: switched an entry %s in %s (backup %s)", "on" if enabled else "off", path, backup)
        return {"success": True, "file": path, "backup_path": backup, "enabled": enabled}


def _emulator_view(context: ModContext) -> dict[str, Any] | None:
    if context.exe is None:
        return None
    label = EMULATOR_LABELS.get(context.emulator or "") or _base(context.exe)
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


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _toggle_view(entry: ToggleEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "name": entry.name,
        "description": entry.description,
        "notes": list(entry.notes),
        "enabled": entry.enabled,
        "can_toggle": entry.can_toggle,
        "origin": entry.origin,
    }
