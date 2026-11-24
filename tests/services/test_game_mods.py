"""Tests for GameModsService — the Mods panel callables, over in-memory fakes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fakes.fake_active_core_resolver import FakeActiveCoreResolver
from fakes.fake_disc_code_reader import FakeDiscCodeReader
from fakes.fake_game_mod_store import FakeGameModStore, FakeSource
from fakes.fake_launch_command_renderer import FakeLaunchCommandRenderer
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock, FakeUuidGen

from domain.disc_ids import GAMECUBE, WII, DiscCode
from domain.game_mods import InstallOutcome, ModEntryInfo, SourceEntry
from domain.rom import Rom
from domain.rom_install import RomInstall
from domain.shortcut_data import EmulatorInvocation
from services.game_mods import GameModsService, GameModsServiceConfig

_EMU = "C:\\Emulation\\Emulators"
_DOLPHIN_DIR = f"{_EMU}\\Dolphin-x64"
_DOLPHIN = f'"{_DOLPHIN_DIR}\\Dolphin.exe" -b -e'
_USER = f"{_DOLPHIN_DIR}\\User"
_TEXTURES = f"{_USER}\\Load\\Textures"
_GAME = f"{_TEXTURES}\\GALE01"
_GFX = f"{_USER}\\Config\\GFX.ini"
_RA_DIR = f"{_EMU}\\RetroArch"
_RA = f'"{_RA_DIR}\\retroarch.exe" -L "{_RA_DIR}\\cores\\snes9x_libretro.dll"'
_ISO = "C:\\Emulation\\roms\\gc\\Melee.rvz"
_SFC = "C:\\Emulation\\roms\\snes\\Game (USA).sfc"
_STAMP_UUID = "abcdef12-0000-0000-0000-000000000000"
_BACKUPS = f"{_USER}\\romm-mod-backups\\20261124-153000-abcdef12"


def _seed(uow: FakeUnitOfWork, *, rom_id: int = 1, path: str = _ISO, platform: str = "ngc") -> None:
    uow.roms.save(
        Rom(
            rom_id=rom_id,
            platform_slug=platform,
            name="Game",
            fs_name="Game",
            shortcut_app_id=42,
            last_synced_at="2026-01-01T00:00:00+00:00",
        )
    )
    uow.rom_installs.save(
        RomInstall(
            rom_id=rom_id,
            file_path=path,
            rom_dir=None,
            platform_slug=platform,
            system=platform,
            installed_at="2026-01-01T00:00:00+00:00",
        )
    )


class _Env:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.uow = FakeUnitOfWork()
        self.store = FakeGameModStore()
        self.emulator: EmulatorInvocation | None = EmulatorInvocation.standalone(_DOLPHIN, "Dolphin")
        self.active = FakeActiveCoreResolver()
        self.discs = FakeDiscCodeReader({_ISO: DiscCode(GAMECUBE, "GALE01")})
        self.backend = "emudeck"
        self.debug: list[str] = []
        self.store.files.update({f"{_DOLPHIN_DIR}\\portable.txt": "", _GFX: "[Settings]\nHiresTextures = False\n"})
        self.store.dirs.update({_USER})

    def service(self, *, with_store: bool = True) -> GameModsService:
        self.active.default_emulator = self.emulator
        renderer = FakeLaunchCommandRenderer(
            resolve_invocation=lambda _rom, emu: (emu.command or (_RA if emu.kind == "libretro" else "")) if emu else ""
        )
        return GameModsService(
            config=GameModsServiceConfig(
                loop=self.loop,
                logger=logging.getLogger("test_game_mods"),
                log_debug=self.debug.append,
                clock=FakeClock(now=datetime(2026, 11, 24, 15, 30, 0, tzinfo=UTC)),
                uuid_gen=FakeUuidGen([_STAMP_UUID] * 5),
                uow_factory=FakeUnitOfWorkFactory(uow=self.uow),
                active_core=self.active,
                launch_renderer=renderer,
                active_backend_id=lambda: self.backend,
                disc_codes=self.discs,
                mod_store=self.store if with_store else None,
            )
        )

    def run(self, coro):
        return self.loop.run_until_complete(coro)


@pytest.fixture
def env():
    e = _Env()
    _seed(e.uow)
    yield e
    e.loop.close()


def _pack(*names: str) -> FakeSource:
    return FakeSource(entries=[SourceEntry(n, n.endswith("/"), 0 if n.endswith("/") else 4) for n in names])


class TestAvailability:
    def test_no_store_is_unsupported(self, env):
        result = env.run(env.service(with_store=False).get_game_mods(1))
        assert result["success"] is False
        assert result["reason"] == "unsupported"
        assert result["message"]

    def test_other_backend_is_unsupported(self, env):
        env.backend = "retrodeck"
        assert env.run(env.service().get_game_mods(1))["reason"] == "unsupported"

    def test_not_installed(self, env):
        result = env.run(env.service().get_game_mods(99))
        assert result == {"success": False, "reason": "not_installed", "message": "ROM 99 is not installed."}

    def test_no_emulator(self, env):
        env.emulator = None
        result = env.run(env.service().get_game_mods(1))
        assert result["success"] is True
        assert result["emulator"] is None
        assert result["targets"] == []
        assert "No known mod folder" in result["note"]

    def test_unknown_emulator_names_it_and_offers_nothing(self, env):
        env.emulator = EmulatorInvocation.standalone(f'"{_EMU}\\Cemu\\Cemu.exe" -g', "Cemu")
        result = env.run(env.service().get_game_mods(1))
        assert result["emulator"] == {"id": None, "label": "Cemu.exe", "exe": f"{_EMU}\\Cemu\\Cemu.exe"}
        assert result["targets"] == []
        assert result["note"] == "No known mod folder for this emulator."


class TestDolphin:
    def test_targets_installed_and_setting(self, env):
        env.store.dirs.add(_GAME)
        env.store.listings[_GAME] = [ModEntryInfo("tex", True, 100, 1.0, files=3)]
        result = env.run(env.service().get_game_mods(1))
        assert result["success"] is True
        assert result["emulator"]["label"] == "Dolphin"
        assert result["game_id"] == "GALE01"
        textures, graphic = result["targets"]
        assert textures["path"] == _GAME
        assert textures["exists"] is True
        assert textures["installed"] == [
            {"name": "tex", "is_dir": True, "size": 100, "files": 3, "modified": 1.0, "partial": False}
        ]
        assert textures["setting"] == {
            "label": "Load Custom Textures",
            "file": _GFX,
            "section": "Settings",
            "key": "HiresTextures",
            "state": "off",
            "can_enable": True,
        }
        assert graphic["scope"] == "shared"
        assert graphic["setting"] is None
        assert env.discs.calls == [(_ISO, "gc-wii")]

    def test_wii_adds_riivolution(self, env):
        env.discs.codes[_ISO] = DiscCode(WII, "RMGE01")
        ids = [t["target_id"] for t in env.run(env.service().get_game_mods(1))["targets"]]
        assert ids == ["textures", "graphic_mods", "riivolution"]

    def test_unreadable_setting_file_is_unknown(self, env):
        env.store.files[_GFX] = None
        setting = env.run(env.service().get_game_mods(1))["targets"][0]["setting"]
        assert setting["state"] == "unknown"
        assert setting["can_enable"] is False

    def test_not_portable_says_why(self, env):
        del env.store.files[f"{_DOLPHIN_DIR}\\portable.txt"]
        result = env.run(env.service().get_game_mods(1))
        assert result["targets"] == []
        assert "portable" in result["note"]

    def test_unreadable_disc_offers_nothing(self, env):
        env.discs.codes.clear()
        result = env.run(env.service().get_game_mods(1))
        assert result["targets"] == []
        assert "ID could not be read" in result["note"]


class TestRetroArch:
    @pytest.fixture
    def ra(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_SFC, platform="snes")
        env.emulator = EmulatorInvocation.libretro("snes9x_libretro", "Snes9x")
        env.store.files[f"{_RA_DIR}\\info\\snes9x_libretro.info"] = 'needs_fullpath = "false"\n'
        return env

    def test_soft_patch_target_lists_existing_patches(self, ra):
        folder = "C:\\Emulation\\roms\\snes"
        ra.store.listings[folder] = [ModEntryInfo("Game (USA).ips", False, 9, 2.0, files=1)]
        result = ra.run(ra.service().get_game_mods(1))
        (target,) = result["targets"]
        assert target["target_id"] == "soft_patch"
        assert target["path"] == folder
        assert target["accepts"] == "patch"
        assert [e["name"] for e in target["installed"]] == ["Game (USA).ips"]
        assert result["emulator"]["id"] == "retroarch"

    def test_fullpath_core_is_omitted_with_reason(self, ra):
        ra.store.files[f"{_RA_DIR}\\info\\snes9x_libretro.info"] = 'needs_fullpath = "true"\n'
        result = ra.run(ra.service().get_game_mods(1))
        assert result["targets"] == []
        assert "from disk" in result["omitted"][0]["reason"]


class TestSources:
    def test_filters_to_what_fits(self, env):
        env.store.source_listing = [
            ModEntryInfo("pack.zip", False, 10, 3.0),
            ModEntryInfo("Pack", True, None, 2.0),
            ModEntryInfo("pack.7z", False, 10, 1.5),
            ModEntryInfo("setup.exe", False, 10, 1.0),
            ModEntryInfo("hack.ips", False, 10, 0.5),
        ]
        result = env.run(env.service().list_mod_sources(1, "textures"))
        assert result["success"] is True
        assert [(e["name"], e["kind"], e["supported"]) for e in result["entries"]] == [
            ("pack.zip", "zip", True),
            ("Pack", "folder", True),
            ("pack.7z", "unsupported_archive", False),
        ]

    def test_unknown_target(self, env):
        result = env.run(env.service().list_mod_sources(1, "bogus"))
        assert result["reason"] == "not_found"

    def test_missing_downloads(self, env):
        env.store.dirs.discard(env.store.downloads)
        assert env.run(env.service().list_mod_sources(1, "textures"))["reason"] == "not_found"


class TestPreviewAndInstall:
    def test_preview_reports_writes_and_replacements(self, env):
        env.store.sources["pack.zip"] = _pack("GALE01/", "GALE01/a.png", "GALE01/b.png")
        env.store.kinds["a.png"] = "file"
        result = env.run(env.service().preview_mod_install(1, "textures", "pack.zip"))
        assert result["success"] is True
        assert result["destination"] == _GAME
        assert result["writes"] == [
            {"path": "a.png", "size": 4, "replaces": True},
            {"path": "b.png", "size": 4, "replaces": False},
        ]
        assert (result["write_count"], result["replace_count"], result["total_bytes"]) == (2, 1, 8)
        assert result["stripped_folder"] == "GALE01"
        assert result["backup_root"] == f"{_USER}\\romm-mod-backups"
        assert env.store.installs == []

    @pytest.mark.parametrize(
        ("source", "reason"),
        [
            (None, "not_found"),
            ("pack.7z", "unsupported"),
            ("hack.ips", "unsupported"),
        ],
    )
    def test_preview_refusals(self, env, source, reason):
        if source:
            env.store.sources[source] = _pack("x")
        result = env.run(env.service().preview_mod_install(1, "textures", source or "missing.zip"))
        assert result["success"] is False
        assert result["reason"] == reason
        assert result["message"]

    def test_unsafe_archive_refused(self, env):
        env.store.sources["evil.zip"] = _pack("../../evil.dll")
        assert env.run(env.service().preview_mod_install(1, "textures", "evil.zip"))["reason"] == "unsafe_source"

    def test_unreadable_archive(self, env):
        env.store.sources["bad.zip"] = FakeSource(read_error=ValueError("not a zip"))
        assert env.run(env.service().preview_mod_install(1, "textures", "bad.zip"))["reason"] == "unreadable_source"

    def test_shape_conflict_blocks(self, env):
        env.store.sources["pack.zip"] = _pack("a.png")
        env.store.kinds["a.png"] = "dir"
        result = env.run(env.service().preview_mod_install(1, "textures", "pack.zip"))
        assert result["reason"] == "conflict"

    def test_install_as_previewed(self, env):
        env.store.sources["pack.zip"] = _pack("a.png")
        env.store.kinds["a.png"] = "file"
        service = env.service()
        fingerprint = env.run(service.preview_mod_install(1, "textures", "pack.zip"))["fingerprint"]
        result = env.run(service.install_mod(1, "textures", "pack.zip", fingerprint))
        assert result == {
            "success": True,
            "destination": _GAME,
            "written": 1,
            "backed_up": 1,
            "backup_folder": f"{_BACKUPS}\\textures",
        }
        ((source, root, writes, replaces, backup),) = env.store.installs
        assert source == f"{env.store.downloads}\\pack.zip"
        assert root == _GAME
        assert [w.dest for w in writes] == ["a.png"]
        assert replaces == frozenset({"a.png"})
        assert backup == f"{_BACKUPS}\\textures"

    def test_install_refuses_when_anything_moved_since_preview(self, env):
        env.store.sources["pack.zip"] = _pack("a.png")
        service = env.service()
        fingerprint = env.run(service.preview_mod_install(1, "textures", "pack.zip"))["fingerprint"]
        env.store.kinds["a.png"] = "file"
        result = env.run(service.install_mod(1, "textures", "pack.zip", fingerprint))
        assert result["reason"] == "changed"
        assert env.store.installs == []

    def test_partial_install_reports_how_far_and_the_backup(self, env):
        env.store.sources["pack.zip"] = _pack("a.png", "b.png")
        env.store.kinds["a.png"] = "file"
        env.store.install_outcome = InstallOutcome(1, 1, "disk full")
        service = env.service()
        fingerprint = env.run(service.preview_mod_install(1, "textures", "pack.zip"))["fingerprint"]
        result = env.run(service.install_mod(1, "textures", "pack.zip", fingerprint))
        assert result["success"] is False
        assert result["reason"] == "partial"
        assert "1 of 2" in result["message"]
        assert result["backup_folder"] == f"{_BACKUPS}\\textures"


class TestRemove:
    def test_whole_game_folder(self, env):
        env.store.dirs.add(_GAME)
        result = env.run(env.service().remove_mod(1, "textures", None))
        assert result == {
            "success": True,
            "removed": _GAME,
            "backup_folder": f"{_BACKUPS}\\textures\\GALE01",
        }
        assert env.store.moves == [(_GAME, "", f"{_BACKUPS}\\textures\\GALE01")]

    def test_one_entry(self, env):
        env.store.listings[_GAME] = [ModEntryInfo("sub", True, 1, 1.0)]
        result = env.run(env.service().remove_mod(1, "textures", "sub"))
        assert result["removed"] == f"{_GAME}\\sub"
        assert env.store.moves == [(_GAME, "sub", f"{_BACKUPS}\\textures\\sub")]

    @pytest.mark.parametrize("name", ["missing", "..", "a\\b"])
    def test_refused(self, env, name):
        result = env.run(env.service().remove_mod(1, "textures", name))
        assert result["reason"] == "not_found"
        assert env.store.moves == []

    def test_shared_target_needs_a_name(self, env):
        assert env.run(env.service().remove_mod(1, "graphic_mods", None))["reason"] == "not_found"

    def test_move_failure(self, env):
        env.store.dirs.add(_GAME)
        env.store.move_error = OSError("locked")
        result = env.run(env.service().remove_mod(1, "textures", None))
        assert result["reason"] == "io_error"
        assert "locked" in result["message"]


class TestEnableSetting:
    def test_edits_one_key_with_backup(self, env):
        result = env.run(env.service().enable_mod_setting(1, "textures"))
        assert result == {"success": True, "file": _GFX, "backup_path": f"{_BACKUPS}\\settings\\GFX.ini"}
        ((path, expected, new_text, backup),) = env.store.replacements
        assert (path, expected) == (_GFX, "[Settings]\nHiresTextures = False\n")
        assert new_text == "[Settings]\nHiresTextures = True\n"
        assert backup == f"{_BACKUPS}\\settings\\GFX.ini"

    def test_refused_while_the_emulator_runs(self, env):
        env.store.running = frozenset({"dolphin.exe"})
        result = env.run(env.service().enable_mod_setting(1, "textures"))
        assert result["reason"] == "emulator_running"
        assert env.store.replacements == []

    def test_unknown_process_state_still_edits(self, env):
        env.store.running = None
        assert env.run(env.service().enable_mod_setting(1, "textures"))["success"] is True

    @pytest.mark.parametrize("text", [None, "[Settings]\ngarbage\n"])
    def test_unsafe_file(self, env, text):
        if text is None:
            del env.store.files[_GFX]
        else:
            env.store.files[_GFX] = text
        assert env.run(env.service().enable_mod_setting(1, "textures"))["reason"] == "setting_unavailable"

    def test_content_moved(self, env):
        env.store.replace_result = False
        assert env.run(env.service().enable_mod_setting(1, "textures"))["reason"] == "changed"

    def test_write_error(self, env):
        env.store.replace_result = PermissionError("denied")
        assert env.run(env.service().enable_mod_setting(1, "textures"))["reason"] == "io_error"

    def test_target_without_setting(self, env):
        assert env.run(env.service().enable_mod_setting(1, "graphic_mods"))["reason"] == "unsupported"


class TestOpenFolder:
    def test_opens_game_folder(self, env):
        env.store.dirs.add(_GAME)
        assert env.run(env.service().open_mod_folder(1, "textures")) == {"success": True, "folder": _GAME}

    def test_falls_back_to_the_parent(self, env):
        env.store.dirs.add(_TEXTURES)
        assert env.run(env.service().open_mod_folder(1, "textures"))["folder"] == _TEXTURES

    def test_nothing_to_open(self, env):
        assert env.run(env.service().open_mod_folder(1, "textures"))["reason"] == "not_found"
        assert env.store.opened == []

    def test_open_failure(self, env):
        env.store.dirs.add(_GAME)
        env.store.open_result = False
        assert env.run(env.service().open_mod_folder(1, "textures"))["reason"] == "open_failed"
