"""Tests for ``SavestateService`` — the upload-only savestate backup and its settings."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fakes.fake_active_core_resolver import FakeActiveCoreResolver
from fakes.fake_disc_resolver import FakeDiscResolver
from fakes.fake_romm_api import FakeRommApi
from fakes.fake_save_file_store import FakeSaveFileStore
from fakes.fake_settings_persister import FakeSettingsPersister
from fakes.fake_unit_of_work import FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from domain.disc_selection import Disc
from domain.rom import Rom
from domain.rom_install import RomInstall
from domain.save_layout import ContentDir, InSaveDir
from domain.savestate_backup import SavestateBackupOutcome
from domain.shortcut_data import EmulatorInvocation
from lib.errors import RommConnectionError, RommNotFoundError
from services.savestates import SavestateService, SavestateServiceConfig

if TYPE_CHECKING:
    from domain.rom_savestate_sync_state import RomSavestateSyncState

ROM_ID = 42
ROMS = "/emu/roms"
STATES = "/emu/saves/retroarch/states"
DEVICE_ID = "3F2A9C1E-7B4D-4E0A-9C3B-1234567890AB"
SHORT = "3f2a9c1e"
NOW = datetime(2026, 11, 26, 20, 0, tzinfo=UTC)
ENABLED_AT = NOW.timestamp() - 3600
AFTER = ENABLED_AT + 60
BEFORE = ENABLED_AT - 60


class _Paths:
    def __init__(self, states: str = STATES) -> None:
        self._states = states

    def roms_path(self) -> str:
        return ROMS

    def bios_path(self) -> str:
        return "/emu/bios"

    def saves_path(self) -> str:
        return "/emu/saves"

    def states_path(self) -> str:
        return self._states

    def standalone_saves_path(self, emulator_id: str) -> str:
        del emulator_id
        return ""


class _Device:
    def __init__(self, device_id: str | None = DEVICE_ID) -> None:
        self.device_id = device_id

    def get_device_id(self) -> str | None:
        return self.device_id


class _FailingPersister:
    def save_settings(self) -> None:
        raise OSError("disk full")


def _settings(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "save_sync_enabled": True,
        "savestate_backup_enabled": True,
        "savestate_backup_scope": "auto",
        "savestate_backup_enabled_at": ENABLED_AT,
    }
    settings.update(overrides)
    return settings


def _current_loop() -> asyncio.AbstractEventLoop:
    """The test's running loop; a fresh one for the synchronous settings tests, which never offload."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.new_event_loop()


class _Env:
    """One service plus the fakes behind it."""

    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        core: tuple[str | None, str | None] = ("snes9x_libretro", "Snes9x"),
        emulator: EmulatorInvocation | None = None,
        layout: InSaveDir | ContentDir | None = None,
        states: str = STATES,
        device_id: str | None = DEVICE_ID,
        file_path: str = f"{ROMS}/snes/Chrono Trigger (USA).sfc",
        rom_dir: str | None = None,
        selected_disc: str | None = None,
        installed: bool = True,
        persister: Any = None,
        corename: str | None = "Snes9x",
        core_version: str | None = "1.62.3",
    ) -> None:
        self.settings = settings if settings is not None else _settings()
        self.files = FakeSaveFileStore()
        self.api = FakeRommApi()
        self.factory = FakeUnitOfWorkFactory()
        self.uow = self.factory.uow
        self.clock = FakeClock(now=NOW)
        self.persister = persister if persister is not None else FakeSettingsPersister()
        self.disc = FakeDiscResolver()
        self.debug: list[str] = []
        self.core_name_calls: list[str] = []
        rom = Rom(
            rom_id=ROM_ID,
            platform_slug="snes",
            name="Chrono Trigger",
            fs_name="Chrono Trigger (USA).sfc",
            shortcut_app_id=1001,
            last_synced_at="2026-01-01T00:00:00Z",
            selected_disc=selected_disc,
        )
        self.uow.roms.save(rom)
        if installed:
            self.uow.rom_installs.save(
                RomInstall.mark_installed(
                    rom_id=ROM_ID,
                    file_path=file_path,
                    rom_dir=rom_dir,
                    platform_slug="snes",
                    system="snes",
                    installed_at="2026-01-01T00:00:00Z",
                )
            )

        def get_core_name(core_so: str) -> str | None:
            self.core_name_calls.append(core_so)
            return corename

        self.service = SavestateService(
            config=SavestateServiceConfig(
                romm_api=self.api,
                uow_factory=self.factory,
                settings=self.settings,
                settings_persister=self.persister,
                savestate_file_store=self.files,
                launcher_paths=_Paths(states),
                savestate_layout=lambda: layout or InSaveDir(sort_by_content=False, sort_by_core=False),
                active_core=FakeActiveCoreResolver(default=core, default_emulator=emulator),
                disc_resolver=self.disc,
                get_core_name=get_core_name,
                get_core_version=lambda core_so: core_version,
                device_id_provider=_Device(device_id),
                clock=self.clock,
                loop=_current_loop(),
                logger=logging.getLogger("test_savestates"),
                log_debug=self._log_debug,
            )
        )

    def _log_debug(self, msg: str) -> None:
        self.debug.append(msg)

    def put(self, name: str, data: bytes, mtime: float = AFTER, directory: str = STATES) -> str:
        path = os.path.join(directory, name)
        self.files.files[path] = data
        self.files.set_mtime(path, mtime)
        return path

    def uploads(self) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for name, args, kwargs in self.api.call_log if name == "upload_state"]

    def record(self) -> RomSavestateSyncState | None:
        return self.uow.rom_savestate_sync_states.get(ROM_ID)

    async def backup(self) -> SavestateBackupOutcome:
        return await self.service.backup_after_session(ROM_ID)


@pytest.fixture
async def env() -> _Env:
    return _Env()


class TestUploadsOnlyChangedSavestates:
    async def test_new_auto_state_is_uploaded_with_its_server_name(self, env: _Env):
        path = env.put("Chrono Trigger (USA).state.auto", b"S1")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(backed_up=1)
        (args, kwargs) = env.uploads()[0]
        assert args == (ROM_ID, path)
        assert kwargs["file_name"] == f"Chrono Trigger (USA) [{SHORT}].state.auto"
        assert kwargs["emulator"] == "snes9x"
        assert kwargs["core"] == "snes9x"
        assert kwargs["core_version"] == "1.62.3"
        assert kwargs["device_id"] == DEVICE_ID
        assert kwargs["screenshot_path"] is None
        record = env.record()
        assert record is not None
        auto = record.slots["auto"]
        assert auto.uploaded_hash == env.files.checksum_md5(path)
        assert auto.server_state_id == 1
        assert auto.server_file_name == f"Chrono Trigger (USA) [{SHORT}].state.auto"
        assert auto.uploaded_at == NOW.isoformat()

    async def test_unchanged_savestate_is_not_uploaded_again(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        await env.backup()

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(unchanged=1)
        assert len(env.uploads()) == 1

    async def test_changed_savestate_replaces_its_own_server_copy(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        await env.backup()
        env.put("Chrono Trigger (USA).state.auto", b"S2", mtime=AFTER + 100)

        outcome = await env.backup()

        assert outcome.backed_up == 1
        names = [kwargs["file_name"] for _args, kwargs in env.uploads()]
        assert names == [names[0], names[0]]
        assert len(env.api.states) == 1

    async def test_screenshot_is_sent_when_retroarch_wrote_one(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        shot = env.put("Chrono Trigger (USA).state.auto.png", b"PNG")

        await env.backup()

        assert env.uploads()[0][1]["screenshot_path"] == shot

    async def test_auto_scope_ignores_numbered_slots(self, env: _Env):
        env.put("Chrono Trigger (USA).state", b"S0")
        env.put("Chrono Trigger (USA).state3", b"S3")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome()
        assert env.uploads() == []

    async def test_all_scope_backs_up_every_slot_present(self):
        env = _Env(settings=_settings(savestate_backup_scope="all"))
        env.put("Chrono Trigger (USA).state.auto", b"SA")
        env.put("Chrono Trigger (USA).state", b"S0")
        env.put("Chrono Trigger (USA).state9", b"S9")
        env.put("Chrono Trigger (USA).state10", b"S10")

        outcome = await env.backup()

        assert outcome.backed_up == 3
        names = sorted(kwargs["file_name"] for _args, kwargs in env.uploads())
        assert names == sorted(
            [
                f"Chrono Trigger (USA) [{SHORT}].state.auto",
                f"Chrono Trigger (USA) [{SHORT}].state",
                f"Chrono Trigger (USA) [{SHORT}].state9",
            ]
        )

    async def test_other_games_savestates_in_the_shared_folder_are_never_touched(self, env: _Env):
        env.put("Chrono Trigger (USA) 2.state.auto", b"OTHER")
        env.put("Chrono Trigger.state.auto", b"OTHER")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome()
        assert env.uploads() == []


class TestBaselineOnFirstEnable:
    async def test_savestate_older_than_enabling_is_baselined_not_uploaded(self, env: _Env):
        path = env.put("Chrono Trigger (USA).state.auto", b"OLD", mtime=BEFORE)

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(baselined=1)
        assert env.uploads() == []
        record = env.record()
        assert record is not None
        assert record.slots["auto"].content_hash == env.files.checksum_md5(path)
        assert record.slots["auto"].uploaded_hash is None

    async def test_baselined_savestate_uploads_once_it_is_overwritten(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"OLD", mtime=BEFORE)
        await env.backup()
        env.put("Chrono Trigger (USA).state.auto", b"NEW", mtime=AFTER)

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(backed_up=1)

    async def test_missing_enable_stamp_uploads_nothing(self):
        settings = _settings()
        del settings["savestate_backup_enabled_at"]
        env = _Env(settings=settings)
        env.put("Chrono Trigger (USA).state.auto", b"S1")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(baselined=1)
        assert env.uploads() == []


class TestNeverDownloadsOrWrites:
    async def test_backup_makes_no_request_but_the_upload_and_writes_no_file(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        env.put("Chrono Trigger (USA).state.auto.png", b"PNG")
        before = dict(env.files.files)

        await env.backup()
        env.put("Chrono Trigger (USA).state.auto", b"S2", mtime=AFTER + 1)
        await env.backup()

        assert {name for name, _args, _kwargs in env.api.call_log} == {"upload_state"}
        assert set(env.files.files) == set(before)
        assert env.files.remove_calls == []
        assert env.files.rename_calls == []


class TestFailures:
    async def test_refused_upload_leaves_the_slot_unrecorded_for_next_time(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        env.api.upload_state_side_effect = RommNotFoundError("Rom with id 42 not found")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(failed=1)
        assert env.record() is None

        env.api.upload_state_side_effect = None
        assert (await env.backup()).backed_up == 1

    async def test_unreachable_server_stops_the_run(self):
        env = _Env(settings=_settings(savestate_backup_scope="all"))
        env.put("Chrono Trigger (USA).state.auto", b"SA")
        env.put("Chrono Trigger (USA).state", b"S0")
        env.api.upload_state_side_effect = RommConnectionError("down")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(failed=1)
        assert len(env.uploads()) == 1

    async def test_baselines_survive_a_failed_upload_in_the_same_run(self):
        env = _Env(settings=_settings(savestate_backup_scope="all"))
        env.put("Chrono Trigger (USA).state.auto", b"OLD", mtime=BEFORE)
        env.put("Chrono Trigger (USA).state", b"S0")
        env.api.upload_state_side_effect = RommNotFoundError("Rom with id 42 not found")

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(baselined=1, failed=1)
        record = env.record()
        assert record is not None
        assert set(record.slots) == {"auto"}

    @pytest.mark.parametrize("response", [{}, {"id": 0}, {"id": True}, {"id": "7"}])
    async def test_answer_without_a_state_id_counts_as_failed(self, env: _Env, response, monkeypatch):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        monkeypatch.setattr(env.api, "upload_state", lambda *a, **k: response)

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(failed=1)
        assert env.record() is None

    async def test_too_large_savestate_is_skipped(self, env: _Env, monkeypatch):
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        monkeypatch.setattr(env.files, "get_size", lambda path: 600 * 1024 * 1024)

        outcome = await env.backup()

        assert outcome == SavestateBackupOutcome(too_large=1)
        assert env.uploads() == []


class TestSkips:
    @pytest.mark.parametrize(
        "settings",
        [_settings(savestate_backup_enabled=False), _settings(save_sync_enabled=False), {}],
    )
    async def test_disabled(self, settings):
        env = _Env(settings=settings)
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        assert await env.backup() == SavestateBackupOutcome(skipped="disabled")
        assert env.uploads() == []

    async def test_standalone_emulator(self):
        env = _Env(emulator=EmulatorInvocation.standalone("pcsx2-qt %ROM%", "PCSX2"))
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        assert await env.backup() == SavestateBackupOutcome(skipped="not_retroarch")

    async def test_unresolved_core(self):
        env = _Env(core=(None, None))
        assert await env.backup() == SavestateBackupOutcome(skipped="not_retroarch")

    async def test_not_installed(self):
        assert await _Env(installed=False).backup() == SavestateBackupOutcome(skipped="not_installed")

    async def test_no_states_folder(self):
        assert await _Env(states="").backup() == SavestateBackupOutcome(skipped="no_states_folder")

    async def test_savestates_in_the_content_folder(self):
        assert await _Env(layout=ContentDir()).backup() == SavestateBackupOutcome(skipped="content_dir")

    @pytest.mark.parametrize("device_id", [None, "", "---"])
    async def test_no_device_id(self, device_id):
        env = _Env(device_id=device_id)
        env.put("Chrono Trigger (USA).state.auto", b"S1")
        assert await env.backup() == SavestateBackupOutcome(skipped="no_device")
        assert env.uploads() == []


class TestWhereSavestatesAre:
    async def test_multi_disc_game_uses_the_booted_file_name(self):
        rom_dir = f"{ROMS}/psx/Final Fantasy VII (USA)"
        env = _Env(
            core=("swanstation_libretro", "SwanStation"),
            corename="SwanStation",
            file_path=f"{rom_dir}/Final Fantasy VII (USA).m3u",
            rom_dir=rom_dir,
            selected_disc="Final Fantasy VII (USA) (Disc 2).chd",
        )
        env.disc.set_discs(
            rom_dir,
            [
                Disc(
                    filename="Final Fantasy VII (USA) (Disc 1).chd",
                    path=f"{rom_dir}/Final Fantasy VII (USA) (Disc 1).chd",
                    label="Disc 1",
                    index=1,
                ),
                Disc(
                    filename="Final Fantasy VII (USA) (Disc 2).chd",
                    path=f"{rom_dir}/Final Fantasy VII (USA) (Disc 2).chd",
                    label="Disc 2",
                    index=2,
                ),
            ],
        )
        env.put("Final Fantasy VII (USA) (Disc 2).state.auto", b"S")
        env.put("Final Fantasy VII (USA).state.auto", b"M3U")

        await env.backup()

        (args, kwargs) = env.uploads()[0]
        assert args[1].endswith("Final Fantasy VII (USA) (Disc 2).state.auto")
        assert kwargs["file_name"] == f"Final Fantasy VII (USA) (Disc 2) [{SHORT}].state.auto"
        assert kwargs["emulator"] == "swanstation"

    async def test_sort_by_core_looks_in_the_core_folder(self):
        env = _Env(layout=InSaveDir(sort_by_content=False, sort_by_core=True))
        env.put("Chrono Trigger (USA).state.auto", b"FLAT")
        path = env.put("Chrono Trigger (USA).state.auto", b"SORTED", directory=os.path.join(STATES, "Snes9x"))

        await env.backup()

        assert env.uploads()[0][0][1] == path

    async def test_sort_by_content_looks_in_the_system_folder(self):
        env = _Env(layout=InSaveDir(sort_by_content=True, sort_by_core=False))
        path = env.put("Chrono Trigger (USA).state.auto", b"S", directory=os.path.join(STATES, "snes"))

        await env.backup()

        assert env.uploads()[0][0][1] == path


class TestLock:
    async def test_concurrent_runs_for_one_rom_upload_once(self, env: _Env):
        env.put("Chrono Trigger (USA).state.auto", b"S1")

        first, second = await asyncio.gather(env.backup(), env.backup())

        assert sorted([first.backed_up, second.backed_up]) == [0, 1]
        assert len(env.uploads()) == 1

    def test_one_lock_per_rom(self, env: _Env):
        assert env.service.rom_lock(1) is env.service.rom_lock(1)
        assert env.service.rom_lock(1) is not env.service.rom_lock(2)


class TestSettings:
    def test_defaults_are_off_and_auto(self):
        env = _Env(settings={})
        assert env.service.get_backup_settings() == {"enabled": False, "scope": "auto"}

    def test_turning_on_stamps_the_moment_and_persists(self):
        env = _Env(settings={"save_sync_enabled": True})
        result = env.service.update_backup_settings({"enabled": True})

        assert result == {"success": True, "settings": {"enabled": True, "scope": "auto"}}
        assert env.settings["savestate_backup_enabled_at"] == NOW.timestamp()
        assert env.persister.save_count == 1

    def test_staying_on_keeps_the_original_stamp(self, env: _Env):
        env.service.update_backup_settings({"enabled": True, "scope": "all"})
        assert env.settings["savestate_backup_enabled_at"] == ENABLED_AT
        assert env.settings["savestate_backup_scope"] == "all"

    def test_turning_off_drops_the_stamp(self, env: _Env):
        env.service.update_backup_settings({"enabled": False})
        assert "savestate_backup_enabled_at" not in env.settings
        assert env.settings["savestate_backup_enabled"] is False

    @pytest.mark.parametrize("scope", ["everything", "", None, 3])
    def test_invalid_scope_is_refused_and_changes_nothing(self, env: _Env, scope):
        before = dict(env.settings)
        result = env.service.update_backup_settings({"enabled": False, "scope": scope})

        assert result["success"] is False
        assert result["reason"] == "invalid_scope"
        assert result["message"]
        assert env.settings == before
        assert env.persister.save_count == 0

    def test_failed_persist_restores_the_previous_values(self):
        env = _Env(settings={"save_sync_enabled": True}, persister=_FailingPersister())
        with pytest.raises(OSError, match="disk full"):
            env.service.update_backup_settings({"enabled": True, "scope": "all"})
        assert env.settings == {"save_sync_enabled": True}
