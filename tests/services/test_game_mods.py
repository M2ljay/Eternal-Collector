"""Tests for GameModsService — the Mods panel callables, over in-memory fakes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fakes.disc_images import param_sfo
from fakes.fake_active_core_resolver import FakeActiveCoreResolver
from fakes.fake_disc_code_reader import FakeDiscCodeReader
from fakes.fake_game_mod_store import FakeGameModStore, FakeSource
from fakes.fake_launch_command_renderer import FakeLaunchCommandRenderer
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock, FakeUuidGen

from adapters.yaml_codec import YamlCodecAdapter
from domain.console_ids import TitleIdAnswer
from domain.disc_ids import GAMECUBE, N3DS, PS2, WII, DiscCode, Ps2ElfCrc
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
                elf_crcs=self.discs,
                console_ids=self.discs,
                yaml=YamlCodecAdapter(),
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
        env.emulator = EmulatorInvocation.standalone(f'"{_EMU}\\Ryujinx\\Ryujinx.exe"', "Ryujinx")
        result = env.run(env.service().get_game_mods(1))
        assert result["emulator"] == {"id": None, "label": "Ryujinx.exe", "exe": f"{_EMU}\\Ryujinx\\Ryujinx.exe"}
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
        textures, graphic, gecko, action_replay = result["targets"]
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
        assert [textures["kind"], graphic["kind"], gecko["kind"], action_replay["kind"]] == [
            "files",
            "graphicsMods",
            "builtinToggle",
            "builtinToggle",
        ]
        assert gecko["accepts"] == "none"
        assert env.discs.calls == [(_ISO, "gc-wii")]

    def test_wii_adds_riivolution(self, env):
        env.discs.codes[_ISO] = DiscCode(WII, "RMGE01")
        ids = [t["target_id"] for t in env.run(env.service().get_game_mods(1))["targets"]]
        assert ids == ["textures", "graphic_mods", "riivolution", "gecko_codes", "action_replay_codes"]

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


# -- cheat files, built-in toggles and the newer emulators ---------------------------

_AZ_DIR = f"{_EMU}\\azahar"
_AZ_USER = f"{_AZ_DIR}\\user"
_AZ_CHEATS = f"{_AZ_USER}\\cheats"
_AZ_FILE = f"{_AZ_CHEATS}\\0004000000055D00.txt"
_3DS = "C:\\Emulation\\roms\\n3ds\\Game.3ds"
_PS2_DIR = f"{_EMU}\\PCSX2"
_PS2_ROM = "C:\\Emulation\\roms\\ps2\\SotC.chd"
_PS2_INI = f"{_PS2_DIR}\\inis\\PCSX2.ini"
_PS2_GAME_INI = f"{_PS2_DIR}\\gamesettings\\SCUS-97472_ABCD1234.ini"
_SYS_GAMESETTINGS = f"{_DOLPHIN_DIR}\\Sys\\GameSettings"
_USER_GAMESETTINGS = f"{_USER}\\GameSettings"


def _targets(result: dict) -> dict[str, dict]:
    return {t["target_id"]: t for t in result["targets"]}


class TestAzaharCheats:
    @pytest.fixture
    def az(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_3DS, platform="3ds")
        env.emulator = EmulatorInvocation.standalone(f'"{_AZ_DIR}\\azahar.exe"', "Azahar")
        env.discs.codes[_3DS] = DiscCode(N3DS, "0004000000055D00")
        env.store.dirs.add(_AZ_USER)
        return env

    def test_cheat_file_target_named_by_title_id(self, az):
        az.store.listings[_AZ_CHEATS] = [ModEntryInfo("0004000000055D00.txt", False, 40, 1.0, files=1)]
        targets = _targets(az.run(az.service().get_game_mods(1)))
        cheats = targets["cheats"]
        assert (cheats["kind"], cheats["scope"], cheats["accepts"]) == ("cheatFile", "file", "cheat_file")
        assert cheats["file_name"] == "0004000000055D00.txt"
        assert [e["name"] for e in cheats["installed"]] == ["0004000000055D00.txt"]
        assert targets["cheat_codes"]["kind"] == "builtinToggle"
        assert targets["mods"]["kind"] == "layeredFs"

    def test_a_downloaded_cheat_is_installed_under_the_title_id(self, az):
        az.store.sources["mk7 cheats.txt"] = FakeSource(entries=[SourceEntry("mk7 cheats.txt", False, 40)])
        svc = az.service()
        preview = az.run(svc.preview_mod_install(1, "cheats", "mk7 cheats.txt"))
        assert preview["destination"] == _AZ_CHEATS
        assert [w["path"] for w in preview["writes"]] == ["0004000000055D00.txt"]
        result = az.run(svc.install_mod(1, "cheats", "mk7 cheats.txt", preview["fingerprint"]))
        assert result["success"] is True
        (_source, root, writes, _replaces, _backup) = az.store.installs[0]
        assert root == _AZ_CHEATS
        assert writes[0].dest == "0004000000055D00.txt"

    def test_lists_and_switches_a_cheat_with_a_backup(self, az):
        az.store.files[_AZ_FILE] = "[Infinite HP]\n12345678 00000063\n"
        svc = az.service()
        listing = az.run(svc.list_mod_builtins(1, "cheat_codes"))
        assert listing["success"] is True
        assert listing["editable"] is True
        assert [(e["entry_id"], e["enabled"], e["can_toggle"]) for e in listing["entries"]] == [
            ("Infinite HP", False, True)
        ]
        result = az.run(svc.set_mod_builtin(1, "cheat_codes", "Infinite HP", True))
        assert result == {
            "success": True,
            "file": _AZ_FILE,
            "backup_path": f"{_AZ_USER}\\romm-mod-backups\\20261124-153000-abcdef12\\settings\\0004000000055D00.txt",
            "enabled": True,
        }
        path, expected, new_text, _backup = az.store.replacements[0]
        assert (path, expected) == (_AZ_FILE, "[Infinite HP]\n12345678 00000063\n")
        assert new_text == "[Infinite HP]\n*citra_enabled\n12345678 00000063\n"

    def test_switching_to_the_current_state_writes_nothing(self, az):
        az.store.files[_AZ_FILE] = "[A]\n*citra_enabled\n1 2\n"
        result = az.run(az.service().set_mod_builtin(1, "cheat_codes", "A", True))
        assert result["success"] is True
        assert result["backup_path"] is None
        assert az.store.replacements == []

    def test_refused_while_the_emulator_runs(self, az):
        az.store.files[_AZ_FILE] = "[A]\n1 2\n"
        az.store.running = frozenset({"azahar.exe"})
        result = az.run(az.service().set_mod_builtin(1, "cheat_codes", "A", True))
        assert result["reason"] == "emulator_running"
        assert az.store.replacements == []

    def test_unknown_entry_and_changed_file(self, az):
        az.store.files[_AZ_FILE] = "[A]\n1 2\n"
        svc = az.service()
        assert az.run(svc.set_mod_builtin(1, "cheat_codes", "Nope", True))["reason"] == "not_found"
        az.store.replace_result = False
        assert az.run(svc.set_mod_builtin(1, "cheat_codes", "A", True))["reason"] == "changed"

    def test_unreadable_file_is_read_only(self, az):
        az.store.files[_AZ_FILE] = None
        listing = az.run(az.service().list_mod_builtins(1, "cheat_codes"))
        assert listing["editable"] is False
        assert "could not be read" in listing["reason"]

    def test_listing_a_files_target_is_unsupported(self, az):
        assert az.run(az.service().list_mod_builtins(1, "cheats"))["reason"] == "unsupported"


class TestPcsx2Patches:
    @pytest.fixture
    def ps2(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_PS2_ROM, platform="ps2")
        env.emulator = EmulatorInvocation.standalone(f'"{_PS2_DIR}\\pcsx2-qt.exe" -batch', "PCSX2")
        env.discs.codes[_PS2_ROM] = DiscCode(PS2, "SCUS-97472")
        env.discs.elf_crcs[_PS2_ROM] = Ps2ElfCrc(0xABCD1234)
        env.store.files.update({f"{_PS2_DIR}\\portable.ini": "", _PS2_INI: "[Folders]\n"})
        return env

    def test_targets_named_by_serial_and_crc(self, ps2):
        targets = _targets(ps2.run(ps2.service().get_game_mods(1)))
        assert list(targets) == ["textures", "cheats", "patches", "cheat_codes"]
        assert targets["cheats"]["file_name"] == "SCUS-97472_ABCD1234.pnach"
        assert targets["cheats"]["path"] == f"{_PS2_DIR}\\cheats"
        assert targets["cheats"]["setting"]["key"] == "EnableCheats"

    def test_unreadable_crc_omits_them_with_the_reason(self, ps2):
        ps2.discs.elf_crcs[_PS2_ROM] = Ps2ElfCrc(None, "the image could not be decoded: unsupported CHD codec")
        result = ps2.run(ps2.service().get_game_mods(1))
        assert list(_targets(result)) == ["textures"]
        (omitted,) = result["omitted"]
        assert "CRC" in omitted["reason"]
        assert "unsupported CHD codec" in omitted["reason"]

    def test_patches_come_from_the_folder_and_the_shipped_zip(self, ps2):
        patches_dir = f"{_PS2_DIR}\\patches"
        ps2.store.file_names[patches_dir] = ["SCUS-97472_ABCD1234_mine.pnach", "unrelated.pnach"]
        ps2.store.files[f"{patches_dir}\\SCUS-97472_ABCD1234_mine.pnach"] = "[Mine]\npatch=1,EE,0,word,0\n"
        ps2.store.zips[(f"{_PS2_DIR}\\resources\\patches.zip", "SCUS-97472_ABCD1234.pnach")] = (
            "[Widescreen 16:9]\ndescription=wide\npatch=1,EE,0,word,0\n"
        )
        ps2.store.files[_PS2_GAME_INI] = "[Patches]\nEnable = Widescreen 16:9\n"
        listing = ps2.run(ps2.service().list_mod_builtins(1, "patches"))
        assert [(e["name"], e["enabled"], e["origin"]) for e in listing["entries"]] == [
            ("Mine", False, "SCUS-97472_ABCD1234_mine.pnach"),
            ("Widescreen 16:9", True, "built-in"),
        ]

    def test_an_unlabelled_patch_on_disk_hides_the_zip(self, ps2):
        patches_dir = f"{_PS2_DIR}\\patches"
        ps2.store.file_names[patches_dir] = ["ABCD1234.pnach"]
        ps2.store.files[f"{patches_dir}\\ABCD1234.pnach"] = "patch=1,EE,0,word,0\n"
        ps2.store.zips[(f"{_PS2_DIR}\\resources\\patches.zip", "SCUS-97472_ABCD1234.pnach")] = "[Zip]\n"
        names = [e["name"] for e in ps2.run(ps2.service().list_mod_builtins(1, "patches"))["entries"]]
        assert names == ["Unlabelled patches in ABCD1234.pnach"]

    def test_switching_creates_the_game_settings_file(self, ps2):
        ps2.store.zips[(f"{_PS2_DIR}\\resources\\patches.zip", "SCUS-97472_ABCD1234.pnach")] = "[60 FPS]\n"
        result = ps2.run(ps2.service().set_mod_builtin(1, "patches", "60 FPS", True))
        assert result == {"success": True, "file": _PS2_GAME_INI, "backup_path": None, "enabled": True}
        assert ps2.store.created == [(_PS2_GAME_INI, "[Patches]\r\nEnable = 60 FPS\r\n")]

    def test_switching_a_cheat_edits_the_existing_file(self, ps2):
        cheats_dir = f"{_PS2_DIR}\\cheats"
        ps2.store.file_names[cheats_dir] = ["SCUS-97472_ABCD1234.pnach"]
        ps2.store.files[f"{cheats_dir}\\SCUS-97472_ABCD1234.pnach"] = "[Max Money]\npatch=1,EE,0,word,0\n"
        ps2.store.files[_PS2_GAME_INI] = "[EmuCore]\nEnableCheats = true\n"
        result = ps2.run(ps2.service().set_mod_builtin(1, "cheat_codes", "Max Money", True))
        assert result["success"] is True
        _path, _expected, new_text, backup = ps2.store.replacements[0]
        assert new_text == "[EmuCore]\nEnableCheats = true\n\n[Cheats]\nEnable = Max Money\n"
        assert backup.endswith("\\settings\\SCUS-97472_ABCD1234.ini")

    def test_unlabelled_entries_cannot_be_switched(self, ps2):
        cheats_dir = f"{_PS2_DIR}\\cheats"
        ps2.store.file_names[cheats_dir] = ["ABCD1234.pnach"]
        ps2.store.files[f"{cheats_dir}\\ABCD1234.pnach"] = "patch=1,EE,0,word,0\n"
        result = ps2.run(ps2.service().set_mod_builtin(1, "cheat_codes", "unlabelled:ABCD1234.pnach", False))
        assert result["reason"] == "not_editable"


class TestDolphinCodes:
    def test_lists_shipped_and_user_codes_and_switches_into_the_id6_file(self, env):
        env.store.files[f"{_SYS_GAMESETTINGS}\\GALE01.ini"] = "[Gecko]\n$Widescreen [x]\n04000000 00000000\n"
        svc = env.service()
        listing = env.run(svc.list_mod_builtins(1, "gecko_codes"))
        assert listing["setting"]["key"] == "EnableCheats"
        assert [(e["name"], e["enabled"], e["origin"]) for e in listing["entries"]] == [
            ("Widescreen", False, "built-in")
        ]
        result = env.run(svc.set_mod_builtin(1, "gecko_codes", "Widescreen", True))
        assert result["success"] is True
        assert env.store.created == [(f"{_USER_GAMESETTINGS}\\GALE01.ini", "[Gecko_Enabled]\r\n$Widescreen\r\n")]

    def test_switches_in_another_user_file_make_it_read_only(self, env):
        env.store.files[f"{_SYS_GAMESETTINGS}\\GALE01.ini"] = "[Gecko]\n$Widescreen\n04000000 00000000\n"
        env.store.files[f"{_USER_GAMESETTINGS}\\GAL.ini"] = "[Gecko_Enabled]\n$Widescreen\n"
        svc = env.service()
        listing = env.run(svc.list_mod_builtins(1, "gecko_codes"))
        assert listing["editable"] is False
        assert env.run(svc.set_mod_builtin(1, "gecko_codes", "Widescreen", False))["reason"] == "not_editable"


class TestNewerEmulators:
    def test_cemu_portable_offers_graphic_packs(self, env):
        cemu_dir = f"{_EMU}\\cemu"
        env.emulator = EmulatorInvocation.standalone(f'"{cemu_dir}\\Cemu.exe" -g', "Cemu")
        env.store.dirs.add(f"{cemu_dir}\\portable")
        result = env.run(env.service().get_game_mods(1))
        (target,) = result["targets"]
        assert (target["target_id"], target["kind"], target["scope"]) == ("graphic_packs", "graphicsMods", "shared")
        assert target["path"] == f"{cemu_dir}\\portable\\graphicPacks"
        assert result["omitted"][0]["label"] == "Switching graphic packs"
        assert "meta.xml" in result["omitted"][0]["reason"]

    def test_cemu_not_portable_says_why(self, env):
        env.emulator = EmulatorInvocation.standalone(f'"{_EMU}\\cemu\\Cemu.exe"', "Cemu")
        result = env.run(env.service().get_game_mods(1))
        assert result["targets"] == []
        assert "portable" in result["note"]

    @pytest.mark.parametrize(
        ("exe", "label"),
        [("xemu\\xemu.exe", "xemu")],
    )
    def test_emulators_with_nothing_offered_name_the_reason(self, env, exe, label):
        env.emulator = EmulatorInvocation.standalone(f'"{_EMU}\\{exe}"', label)
        result = env.run(env.service().get_game_mods(1))
        assert result["emulator"]["label"] == label
        assert result["targets"] == []
        assert result["note"] == f"Nothing is offered for {label}."
        assert result["omitted"]
        assert env.discs.calls == []

    def test_retroarch_cheat_file_from_cfg_and_core_info(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_SFC, platform="snes")
        env.emulator = EmulatorInvocation.libretro("snes9x_libretro", "Snes9x")
        env.store.files[f"{_RA_DIR}\\info\\snes9x_libretro.info"] = 'needs_fullpath = "false"\ncorename = "Snes9x"\n'
        env.store.files[f"{_RA_DIR}\\retroarch.cfg"] = 'cheat_database_path = ":\\cheats"\n'
        targets = _targets(env.run(env.service().get_game_mods(1)))
        assert list(targets) == ["soft_patch", "cheats"]
        assert targets["cheats"]["path"] == f"{_RA_DIR}\\cheats\\Snes9x"
        assert targets["cheats"]["file_name"] == "Game (USA).cht"


# -- win.30: RPCS3, Xenia, Cemu packs, shadPS4 and Azahar content ----------------------

_PS3_EXE_DIR = f"{_EMU}\\RPCS3"
_PS3_GAME = "C:\\Emulation\\roms\\ps3\\Demon's Souls.ps3"
_PS3_HASH = "PPU-b8c34f774adb367761706a7f685d4f8d9d355426"
_PATCH_YML = (
    "Version: 1.2\n\n"
    f"{_PS3_HASH}:\n"
    '  "60 FPS":\n'
    "    Games:\n"
    '      "Demon\'s Souls":\n'
    "        BLUS30443: [ 01.04 ]\n"
    "    Patch Version: 1.0\n"
    "    Patch:\n"
    "      - [ be32, 0x10000, 0x60000000 ]\n"
)


class TestRpcs3:
    @pytest.fixture
    def ps3(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_PS3_GAME, platform="ps3")
        env.emulator = EmulatorInvocation.standalone(f'"{_PS3_EXE_DIR}\\rpcs3.exe" --no-gui', "RPCS3")
        disc_sfo = f"{_PS3_GAME}\\PS3_GAME\\PARAM.SFO"
        update_sfo = f"{_PS3_EXE_DIR}\\dev_hdd0\\game\\BLUS30443\\PARAM.SFO"
        env.store.dirs.add(_PS3_GAME)
        env.store.files.update({disc_sfo: "", update_sfo: "", f"{_PS3_EXE_DIR}\\patches\\patch.yml": _PATCH_YML})
        env.store.binaries[disc_sfo] = param_sfo({"TITLE_ID": "BLUS30443", "APP_VER": "01.00"})
        env.store.binaries[update_sfo] = param_sfo({"TITLE_ID": "BLUS30443", "APP_VER": "01.04"})
        return env

    def test_patches_and_installed_update_are_offered_with_downloads_refused(self, ps3):
        result = ps3.run(ps3.service().get_game_mods(1))
        assert result["game_id"] == "BLUS30443"
        targets = _targets(result)
        assert list(targets) == ["patches", "update"]
        assert targets["update"]["notes"] == ["Installed update: version 01.04."]
        assert targets["update"]["accepts"] == "none"
        assert "certificate" in result["omitted"][0]["reason"]

    def test_patch_for_the_installed_version_is_switched_in_patch_config(self, ps3):
        svc = ps3.service()
        (entry,) = ps3.run(svc.list_mod_builtins(1, "patches"))["entries"]
        assert (entry["name"], entry["enabled"], entry["can_toggle"]) == ("60 FPS", False, True)
        result = ps3.run(svc.set_mod_builtin(1, "patches", entry["entry_id"], True))
        assert result["success"] is True
        ((path, text),) = ps3.store.created
        assert path == f"{_PS3_EXE_DIR}\\config\\patch_config.yml"
        assert "Enabled: true" in text and "'01.04'" in text and "BLUS30443" in text

    def test_unreadable_serial_says_why(self, ps3):
        ps3.store.binaries.clear()
        result = ps3.run(ps3.service().get_game_mods(1))
        assert result["targets"] == []
        assert "serial" in result["note"]

    def test_vfs_moving_dev_hdd0_leaves_the_update_out(self, ps3):
        ps3.store.files[f"{_PS3_EXE_DIR}\\config\\vfs.yml"] = '/dev_hdd0/: "D:/PS3HDD/"\n'
        result = ps3.run(ps3.service().get_game_mods(1))
        assert list(_targets(result)) == ["patches"]
        assert any("vfs.yml" in o["reason"] for o in result["omitted"])


_XENIA_DIR = f"{_EMU}\\xenia"
_X360_ROM = "C:\\Emulation\\roms\\xbox360\\Halo 3.iso"
_XENIA_PATCH = f"{_XENIA_DIR}\\patches\\4D5307E6 - Halo 3.patch.toml"


class TestXenia:
    @pytest.fixture
    def x360(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_X360_ROM, platform="xbox360")
        env.emulator = EmulatorInvocation.standalone(f'"{_XENIA_DIR}\\xenia_canary.exe"', "Xenia")
        env.discs.xbox_titles[_X360_ROM] = TitleIdAnswer("4D5307E6")
        env.store.file_names[f"{_XENIA_DIR}\\patches"] = ["4D5307E6 - Halo 3.patch.toml", "584111F7 - Other.patch.toml"]
        env.store.files[_XENIA_PATCH] = 'title_id = "4D5307E6"\n[[patch]]\nname = "60 FPS"\nis_enabled = false\n'
        return env

    def test_patches_and_content_targets(self, x360):
        content = f"{_XENIA_DIR}\\content\\0000000000000000\\4D5307E6\\000B0000"
        x360.store.dirs.add(content)
        x360.store.listings[content] = [ModEntryInfo("TU5", True, 100, 1.0, files=2)]
        result = x360.run(x360.service().get_game_mods(1))
        targets = _targets(result)
        assert list(targets) == ["patches", "update", "dlc"]
        assert [e["name"] for e in targets["update"]["installed"]] == ["TU5"]
        assert result["omitted"][0]["label"] == "Installing title updates and DLC"

    def test_switching_a_patch_edits_its_file(self, x360):
        result = x360.run(x360.service().set_mod_builtin(1, "patches", "60 FPS", True))
        assert result["success"] is True
        ((path, _old, new_text, backup),) = x360.store.replacements
        assert path == _XENIA_PATCH
        assert "is_enabled = true" in new_text
        assert backup.endswith("\\settings\\4D5307E6 - Halo 3.patch.toml")

    def test_unreadable_title_id_says_why(self, x360):
        x360.discs.xbox_titles.clear()
        result = x360.run(x360.service().get_game_mods(1))
        assert result["targets"] == []
        assert "title ID" in result["note"]

    def test_relative_content_root_is_refused(self, x360):
        x360.store.files[f"{_XENIA_DIR}\\xenia-canary.config.toml"] = 'content_root = "content2"\n'
        targets = _targets(x360.run(x360.service().get_game_mods(1)))
        assert list(targets) == ["patches"]


_CEMU_DIR = f"{_EMU}\\cemu"
_CEMU_DATA = f"{_CEMU_DIR}\\portable"
_WIIU_GAME = "C:\\Emulation\\roms\\wiiu\\BotW"


class TestCemuPacks:
    @pytest.fixture
    def wiiu(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=f"{_WIIU_GAME}\\code\\U-King.rpx", platform="wiiu")
        env.emulator = EmulatorInvocation.standalone(f'"{_CEMU_DIR}\\Cemu.exe" -g', "Cemu")
        env.store.dirs.add(_CEMU_DATA)
        env.store.files[f"{_WIIU_GAME}\\meta\\meta.xml"] = "<title_id>00050000101C9400</title_id>"
        env.store.found[(f"{_CEMU_DATA}\\graphicPacks", "rules.txt")] = ["BotW_Res\\rules.txt"]
        env.store.files[f"{_CEMU_DATA}\\graphicPacks\\BotW_Res\\rules.txt"] = (
            "[Definition]\ntitleIds = 00050000101C9400\nname = Resolution\n"
        )
        env.store.files[f"{_CEMU_DATA}\\settings.xml"] = "<content>\n    <GraphicPack/>\n</content>\n"
        return env

    def test_lists_and_switches_the_games_packs(self, wiiu):
        svc = wiiu.service()
        result = wiiu.run(svc.get_game_mods(1))
        assert result["game_id"] == "00050000101C9400"
        assert list(_targets(result)) == ["graphic_packs", "pack_toggles"]
        (entry,) = wiiu.run(svc.list_mod_builtins(1, "pack_toggles"))["entries"]
        assert (entry["entry_id"], entry["name"], entry["enabled"]) == (
            "graphicPacks\\BotW_Res\\rules.txt",
            "Resolution",
            False,
        )
        assert wiiu.run(svc.set_mod_builtin(1, "pack_toggles", entry["entry_id"], True))["success"] is True
        new_text = wiiu.store.replacements[0][2]
        assert '<Entry filename="graphicPacks\\BotW_Res\\rules.txt"/>' in new_text


_PS4_DIR = f"{_EMU}\\shadps4"
_PS4_GAME = "D:\\ps4\\CUSA00001"


class TestShadPs4:
    @pytest.fixture
    def ps4(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=f"{_PS4_GAME}\\eboot.bin", platform="ps4")
        env.emulator = EmulatorInvocation.standalone(f'"{_PS4_DIR}\\shadPS4.exe"', "shadPS4")
        game_sfo = f"{_PS4_GAME}\\sce_sys\\param.sfo"
        env.store.files[game_sfo] = ""
        env.store.binaries[game_sfo] = param_sfo({"TITLE_ID": "CUSA00001", "APP_VER": "01.00"})
        return env

    def test_update_and_mods_targets_with_versions(self, ps4):
        update_sfo = f"{_PS4_GAME}-UPDATE\\sce_sys\\param.sfo"
        ps4.store.files[update_sfo] = ""
        ps4.store.binaries[update_sfo] = param_sfo({"TITLE_ID": "CUSA00001", "APP_VER": "01.09"})
        result = ps4.run(ps4.service().get_game_mods(1))
        targets = _targets(result)
        assert list(targets) == ["update", "overlay_mods"]
        assert targets["update"]["path"] == f"{_PS4_GAME}-UPDATE"
        assert "Game version 01.00." in targets["update"]["notes"]
        assert "Installed update: version 01.09." in targets["update"]["notes"]

    def test_installing_an_update_moves_the_old_one_to_the_backup_first(self, ps4):
        ps4.store.dirs.update({f"{_PS4_GAME}-UPDATE", "C:\\Users\\me\\Downloads\\CUSA00001-patch"})
        ps4.store.sources["CUSA00001-patch"] = FakeSource(
            is_dir=True, entries=[SourceEntry("CUSA00001-patch/sce_sys/param.sfo", False, 10)]
        )
        svc = ps4.service()
        preview = ps4.run(svc.preview_mod_install(1, "update", "CUSA00001-patch"))
        assert preview["replaces_folder"] is True
        assert [w["path"] for w in preview["writes"]] == ["sce_sys/param.sfo"]
        result = ps4.run(svc.install_mod(1, "update", "CUSA00001-patch", preview["fingerprint"]))
        assert result["success"] is True
        ((root, name, backup),) = ps4.store.moves
        assert (root, name) == (f"{_PS4_GAME}-UPDATE", "")
        assert backup.endswith("\\update\\CUSA00001-UPDATE")
        assert ps4.store.installs[0][3] == frozenset()


class TestAzaharContent:
    @pytest.fixture
    def az(self, env):
        env.uow = FakeUnitOfWork()
        _seed(env.uow, path=_3DS, platform="3ds")
        env.emulator = EmulatorInvocation.standalone(f'"{_AZ_DIR}\\azahar.exe"', "Azahar")
        env.discs.codes[_3DS] = DiscCode(N3DS, "0004000000055D00")
        env.store.dirs.add(_AZ_USER)
        env.store.sources["MK7 Update.cia"] = FakeSource(entries=[SourceEntry("MK7 Update.cia", False, 1000)])
        return env

    _UPDATE = f"{_AZ_USER}\\sdmc\\Nintendo 3DS\\{'0' * 32}\\{'0' * 32}\\title\\0004000e\\00055d00"

    def test_installs_a_cia_with_azahar_after_backing_up_the_old_update(self, az):
        az.store.dirs.add(self._UPDATE)
        svc = az.service()
        preview = az.run(svc.preview_mod_install(1, "content", "MK7 Update.cia"))
        assert preview["installer"] == "azahar_cia"
        result = az.run(svc.install_mod(1, "content", "MK7 Update.cia", preview["fingerprint"]))
        assert result["success"] is True
        assert az.store.installer_runs == [
            (f"{_AZ_DIR}\\azahar.exe", ("-i", "C:\\Users\\me\\Downloads\\MK7 Update.cia"))
        ]
        ((copied, backup),) = az.store.copies
        assert copied == self._UPDATE
        assert backup.endswith("\\content\\Update")
        assert az.store.installs == []

    def test_an_encrypted_cia_is_reported(self, az):
        az.store.installer_result = (7, "Failed to install CIA: CIA is encrypted.")
        svc = az.service()
        preview = az.run(svc.preview_mod_install(1, "content", "MK7 Update.cia"))
        result = az.run(svc.install_mod(1, "content", "MK7 Update.cia", preview["fingerprint"]))
        assert result["success"] is False
        assert result["reason"] == "installer_failed"
        assert "encrypted" in result["message"]

    def test_refused_while_azahar_runs(self, az):
        az.store.running = frozenset({"azahar.exe"})
        svc = az.service()
        preview = az.run(svc.preview_mod_install(1, "content", "MK7 Update.cia"))
        assert az.run(svc.install_mod(1, "content", "MK7 Update.cia", preview["fingerprint"]))["reason"] == (
            "emulator_running"
        )
        assert az.store.installer_runs == []

    def test_installed_update_is_listed_by_label(self, az):
        az.store.dirs.add(self._UPDATE)
        parent = self._UPDATE.rsplit("\\", 1)[0]
        az.store.listings[parent] = [ModEntryInfo("00055d00", True, None, 5.0)]
        content = _targets(az.run(az.service().get_game_mods(1)))["content"]
        assert content["accepts"] == "cia_file"
        assert [e["name"] for e in content["installed"]] == ["Update"]
