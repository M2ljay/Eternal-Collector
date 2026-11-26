"""SavestateService — backs RetroArch savestates up to RomM after a game exits.

Upload-only (ADR-0031). The service never downloads a savestate, never writes,
renames or removes a local one, and takes no part in save sync: its one decision is
:func:`domain.savestate_backup.savestate_backup_action`, which never reaches the
gavel core. It runs from the post-exit flow after the save sync has finished and
holds its own per-ROM lock, apart from the save sync's ``rom_lock``, because the two
flows share no state.

RetroArch only: a ROM that launches with a standalone emulator is skipped.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.rom_savestate_sync_state import RomSavestateSyncState
from domain.save_layout import InSaveDir
from domain.save_path import resolve_save_dir
from domain.savestate_backup import (
    ADOPT_BASELINE,
    TOO_LARGE,
    UNCHANGED,
    SavestateBackupOutcome,
    savestate_backup_action,
)
from domain.savestate_names import (
    core_id,
    device_short_id,
    local_savestate_names,
    romm_emulator_for_core,
    screenshot_name,
    server_savestate_name,
    slots_for_scope,
)
from lib.errors import classify_error
from lib.list_result import ErrorCode
from services.savestates._settings import (
    ENABLED_AT_KEY,
    ENABLED_KEY,
    SCOPE_KEY,
    backup_enabled,
    backup_scope,
    enabled_at,
    is_valid_scope,
    settings_view,
)

if TYPE_CHECKING:
    import logging

    from domain.rom import Rom
    from domain.rom_install import RomInstall
    from domain.shortcut_data import EmulatorInvocation
    from services.protocols import (
        ActiveCoreReader,
        Clock,
        CoreNameProviderFn,
        CoreVersionProviderFn,
        DebugLogger,
        DeviceIdProvider,
        DiscResolver,
        LauncherPaths,
        RetroArchSavestateLayoutProvider,
        RommSavestateBackupApi,
        SavestateFileStore,
        SettingsPersister,
        UnitOfWorkFactory,
    )


_UPLOADED = "uploaded"
_FAILED = "failed"
_UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class SavestateServiceConfig:
    """Frozen wiring bundle handed to ``SavestateService.__init__``.

    The RomM upload surface, the Unit-of-Work factory (the ROM, its install and
    the ``rom_savestate_sync_states`` aggregate), the live settings dict and its
    persister, the read-only savestate file seam, the active launcher backend's
    roots, the live RetroArch savestate layout, the per-ROM active-core and
    disc-launch resolvers, the RetroArch ``.info`` readers, the server device-id
    source, the clock, the event loop the blocking work is offloaded to, and the
    two loggers.
    """

    romm_api: RommSavestateBackupApi
    uow_factory: UnitOfWorkFactory
    settings: dict[str, Any]
    settings_persister: SettingsPersister
    savestate_file_store: SavestateFileStore
    launcher_paths: LauncherPaths
    savestate_layout: RetroArchSavestateLayoutProvider
    active_core: ActiveCoreReader
    disc_resolver: DiscResolver
    get_core_name: CoreNameProviderFn
    get_core_version: CoreVersionProviderFn
    device_id_provider: DeviceIdProvider
    clock: Clock
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    log_debug: DebugLogger


@dataclass(frozen=True)
class _Target:
    """Where one ROM's savestates are and what an upload of them carries."""

    states_dir: str
    stem: str
    short_id: str
    device_id: str
    emulator: str
    core: str
    core_version: str | None


class SavestateService:
    """Post-exit savestate backup plus the settings behind it."""

    def __init__(self, *, config: SavestateServiceConfig) -> None:
        self._romm_api = config.romm_api
        self._uow_factory = config.uow_factory
        self._settings = config.settings
        self._settings_persister = config.settings_persister
        self._files = config.savestate_file_store
        self._launcher_paths = config.launcher_paths
        self._savestate_layout = config.savestate_layout
        self._active_core = config.active_core
        self._disc_resolver = config.disc_resolver
        self._get_core_name = config.get_core_name
        self._get_core_version = config.get_core_version
        self._device_id_provider = config.device_id_provider
        self._clock = config.clock
        self._loop = config.loop
        self._logger = config.logger
        self._log_debug = config.log_debug
        self._rom_locks: dict[int, asyncio.Lock] = {}

    def rom_lock(self, rom_id: int) -> asyncio.Lock:
        """The lock every read-mutate-write of *rom_id*'s ``RomSavestateSyncState`` holds."""
        lock = self._rom_locks.get(rom_id)
        if lock is None:
            lock = asyncio.Lock()
            self._rom_locks[rom_id] = lock
        return lock

    # ── Settings ──────────────────────────────────────────────────────

    def get_backup_settings(self) -> dict[str, Any]:
        """The frontend-facing ``{enabled, scope}`` pair."""
        return settings_view(self._settings)

    def update_backup_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply ``enabled`` / ``scope`` from *changes* and persist them.

        Turning the backup on stamps the moment it happened: only savestates
        written from then on are uploaded, older ones are recorded as baselines.
        Turning it off drops the stamp, so turning it on again starts a fresh
        window. A scope other than ``auto`` / ``all`` is refused with the failure
        shape and changes nothing. A failed persist restores the previous values
        and re-raises.
        """
        if "scope" in changes and not is_valid_scope(changes["scope"]):
            return {
                "success": False,
                "reason": "invalid_scope",
                "message": "Choose either the auto-state only or all slots",
            }
        previous = {key: self._settings.get(key) for key in (ENABLED_KEY, SCOPE_KEY, ENABLED_AT_KEY)}
        if "scope" in changes:
            self._settings[SCOPE_KEY] = changes["scope"]
        if "enabled" in changes:
            turning_on = bool(changes["enabled"])
            if turning_on and not bool(previous[ENABLED_KEY]):
                self._settings[ENABLED_AT_KEY] = self._clock.time()
            elif not turning_on:
                self._settings.pop(ENABLED_AT_KEY, None)
            self._settings[ENABLED_KEY] = turning_on
        try:
            self._settings_persister.save_settings()
        except Exception:
            for key, value in previous.items():
                if value is None:
                    self._settings.pop(key, None)
                else:
                    self._settings[key] = value
            raise
        return {"success": True, "settings": settings_view(self._settings)}

    # ── Backup ────────────────────────────────────────────────────────

    async def backup_after_session(self, rom_id: int) -> SavestateBackupOutcome:
        """Upload *rom_id*'s changed savestates, holding the ROM's savestate lock.

        Never raises for an expected condition: a disabled backup, a standalone
        emulator, a missing install, folder or device id each come back as a
        ``skipped`` outcome, and an upload the server refuses is counted in
        ``failed`` with its slot left unrecorded for the next run.
        """
        if not backup_enabled(self._settings):
            return SavestateBackupOutcome(skipped="disabled")
        async with self.rom_lock(rom_id):
            return await self._loop.run_in_executor(None, self._backup_io, rom_id)

    def _backup_io(self, rom_id: int) -> SavestateBackupOutcome:
        rom, install = self._read_rom_and_install(rom_id)
        if rom is None or install is None:
            return SavestateBackupOutcome(skipped="not_installed")
        target_or_reason = self._resolve_target(rom_id, rom, install)
        if isinstance(target_or_reason, str):
            self._log_debug(f"savestates: rom_id={rom_id} skipped ({target_or_reason})")
            return SavestateBackupOutcome(skipped=target_or_reason)
        return self._back_up(rom_id, target_or_reason)

    def _read_rom_and_install(self, rom_id: int) -> tuple[Rom | None, RomInstall | None]:
        with self._uow_factory() as uow:
            return (uow.roms.get(rom_id), uow.rom_installs.get(rom_id))

    def _resolve_target(self, rom_id: int, rom: Rom, install: RomInstall) -> _Target | str:
        """Where this ROM's savestates sit and how they are tagged, or the reason to skip it."""
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        core_so = _libretro_core(emulator)
        if core_so is None:
            return "not_retroarch"
        states_root = self._launcher_paths.states_path()
        if not states_root:
            return "no_states_folder"
        layout = self._savestate_layout()
        if not isinstance(layout, InSaveDir):
            return "content_dir"
        boot_path = self._disc_resolver.resolve_for_install(install, rom.selected_disc)
        if not boot_path:
            return "not_installed"
        device_id = self._device_id_provider.get_device_id()
        if not device_id:
            return "no_device"
        try:
            short_id = device_short_id(device_id)
        except ValueError:
            return "no_device"
        corename = self._get_core_name(core_so)
        states_dir = resolve_save_dir(
            boot_path,
            states_root,
            install.system,
            roms_base=self._launcher_paths.roms_path(),
            sort_by_content=layout.sort_by_content,
            sort_by_core=layout.sort_by_core,
            core_name=corename,
        )
        return _Target(
            states_dir=states_dir,
            stem=os.path.splitext(os.path.basename(boot_path))[0],
            short_id=short_id,
            device_id=device_id,
            emulator=romm_emulator_for_core(core_so, corename),
            core=core_id(core_so),
            core_version=self._get_core_version(core_so),
        )

    def _back_up(self, rom_id: int, target: _Target) -> SavestateBackupOutcome:
        with self._uow_factory() as uow:
            state = uow.rom_savestate_sync_states.get(rom_id) or RomSavestateSyncState()
        stamp = enabled_at(self._settings)
        backed_up = baselined = unchanged = failed = too_large = 0
        for slot, name in local_savestate_names(target.stem, slots_for_scope(backup_scope(self._settings))):
            path = os.path.join(target.states_dir, name)
            if not self._files.is_file(path):
                continue
            local_hash = self._files.checksum_md5(path)
            action = savestate_backup_action(
                local_hash=local_hash,
                recorded_hash=state.recorded_hash(slot),
                local_mtime=self._files.get_mtime(path),
                local_size=self._files.get_size(path),
                enabled_at=stamp,
            )
            now = self._clock.now().isoformat()
            if action == UNCHANGED:
                unchanged += 1
            elif action == ADOPT_BASELINE:
                state.adopt_baseline(slot, local_name=name, content_hash=local_hash, observed_at=now)
                baselined += 1
            elif action == TOO_LARGE:
                self._logger.warning(f"savestates: {name} is larger than RomM accepts by default; not backed up")
                too_large += 1
            else:
                result = self._upload(rom_id, target, state, slot, name, path, local_hash, now)
                if result == _UPLOADED:
                    backed_up += 1
                    continue
                failed += 1
                if result == _UNREACHABLE:
                    break
        if backed_up or baselined:
            with self._uow_factory() as uow:
                uow.rom_savestate_sync_states.save(rom_id, state)
        return SavestateBackupOutcome(
            backed_up=backed_up, baselined=baselined, unchanged=unchanged, failed=failed, too_large=too_large
        )

    def _upload(
        self,
        rom_id: int,
        target: _Target,
        state: RomSavestateSyncState,
        slot: str,
        name: str,
        path: str,
        local_hash: str,
        now: str,
    ) -> str:
        """Upload one savestate and record it.

        Answers ``_UPLOADED``, ``_FAILED`` when the server refused it, or
        ``_UNREACHABLE`` when it could not be reached — the caller then stops, as
        every further upload of the run would wait out the same timeout.
        """
        screenshot = os.path.join(target.states_dir, screenshot_name(name))
        server_name = server_savestate_name(target.stem, target.short_id, slot)
        try:
            response = self._romm_api.upload_state(
                rom_id,
                path,
                file_name=server_name,
                emulator=target.emulator,
                screenshot_path=screenshot if self._files.is_file(screenshot) else None,
                core=target.core,
                core_version=target.core_version,
                device_id=target.device_id,
            )
        except Exception as exc:
            reason, message = classify_error(exc)
            self._logger.warning(f"savestates: upload of {name} for rom_id={rom_id} failed ({reason}): {message}")
            return _UNREACHABLE if reason == ErrorCode.SERVER_UNREACHABLE.value else _FAILED
        server_id = response.get("id")
        if not isinstance(server_id, int) or isinstance(server_id, bool) or server_id <= 0:
            self._logger.warning(f"savestates: RomM answered the upload of {name} without a state id")
            return _FAILED
        stored_name = response.get("file_name")
        state.record_upload(
            slot,
            local_name=name,
            content_hash=local_hash,
            uploaded_at=now,
            server_state_id=server_id,
            server_file_name=stored_name if isinstance(stored_name, str) and stored_name else server_name,
            emulator=target.emulator,
            core=target.core,
            core_version=target.core_version,
        )
        self._log_debug(f"savestates: backed up {name} as {server_name} (state id {server_id})")
        return _UPLOADED


def _libretro_core(emulator: EmulatorInvocation | None) -> str | None:
    """The libretro core the ROM launches with, or ``None`` for a standalone or unresolved emulator."""
    if emulator is None or emulator.kind != "libretro":
        return None
    return emulator.core_so or None
