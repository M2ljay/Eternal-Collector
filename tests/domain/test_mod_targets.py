"""Tests for domain.mod_targets — cheat-file, toggle and graphic-pack targets per emulator layout."""

from __future__ import annotations

import pytest

from domain.disc_ids import GAMECUBE, DiscCode
from domain.game_mods import (
    AZAHAR,
    CEMU,
    DOLPHIN,
    KIND_BUILTIN_TOGGLE,
    KIND_CHEAT_FILE,
    KIND_GRAPHICS_MODS,
    PCSX2,
    RPCS3,
    SCOPE_FILE,
    SCOPE_SHARED,
    SCOPE_TOGGLE,
    SHADPS4,
    XEMU,
    XENIA,
    EmulatorHome,
)
from domain.mod_targets import (
    DOLPHIN_ENABLE_CHEATS,
    PCSX2_ENABLE_CHEATS,
    TOGGLE_AZAHAR_CHEATS,
    TOGGLE_DOLPHIN_ACTION_REPLAY,
    TOGGLE_DOLPHIN_GECKO,
    TOGGLE_PCSX2_CHEATS,
    TOGGLE_PCSX2_PATCHES,
    azahar_cheat_targets,
    cemu_home,
    cemu_targets,
    dolphin_code_targets,
    not_offered,
    pcsx2_patch_targets,
    pcsx2_pnach_matches,
    retroarch_cheat_dir,
    retroarch_cheat_target,
)

_EMU = "C:\\Emulation\\Emulators"


class TestAzahar:
    def test_cheat_file_and_its_toggles(self):
        home = EmulatorHome(AZAHAR, f"{_EMU}\\azahar\\azahar.exe", f"{_EMU}\\azahar\\user")
        cheat, toggles = azahar_cheat_targets(home, "0004000000055D00")
        assert (cheat.kind, cheat.scope, cheat.path, cheat.file_name, cheat.file_ext) == (
            KIND_CHEAT_FILE,
            SCOPE_FILE,
            f"{_EMU}\\azahar\\user\\cheats",
            "0004000000055D00.txt",
            ".txt",
        )
        assert toggles.kind == KIND_BUILTIN_TOGGLE
        assert toggles.toggle is not None
        assert toggles.toggle.format == TOGGLE_AZAHAR_CHEATS
        assert toggles.toggle.write_file == f"{_EMU}\\azahar\\user\\cheats\\0004000000055D00.txt"

    def test_no_home_no_targets(self):
        assert azahar_cheat_targets(EmulatorHome(AZAHAR, "x", None, "no user folder"), "0004000000055D00") == ()


class TestDolphin:
    def test_gecko_and_action_replay_read_sys_and_user_and_write_id6(self):
        exe = f"{_EMU}\\Dolphin-x64\\Dolphin.exe"
        home = EmulatorHome(DOLPHIN, exe, f"{_EMU}\\Dolphin-x64\\User")
        gecko, ar = dolphin_code_targets(home, DiscCode(GAMECUBE, "GALE01", revision=2))
        assert (gecko.scope, gecko.kind, gecko.setting) == (SCOPE_TOGGLE, KIND_BUILTIN_TOGGLE, DOLPHIN_ENABLE_CHEATS)
        assert gecko.toggle is not None and ar.toggle is not None
        assert gecko.toggle.format == TOGGLE_DOLPHIN_GECKO
        assert ar.toggle.format == TOGGLE_DOLPHIN_ACTION_REPLAY
        assert gecko.toggle.read_files == tuple(
            f"{_EMU}\\Dolphin-x64\\Sys\\GameSettings\\{n}" for n in ("G.ini", "GAL.ini", "GALE01.ini", "GALE01r2.ini")
        )
        assert gecko.toggle.user_files[-1] == f"{_EMU}\\Dolphin-x64\\User\\GameSettings\\GALE01r2.ini"
        assert gecko.toggle.write_file == f"{_EMU}\\Dolphin-x64\\User\\GameSettings\\GALE01.ini"


class TestPcsx2:
    _HOME = EmulatorHome(PCSX2, f"{_EMU}\\PCSX2\\pcsx2-qt.exe", f"{_EMU}\\PCSX2")

    def test_default_folders(self):
        cheat, patches, cheats = pcsx2_patch_targets(self._HOME, "[Folders]\n", "SLUS-20946", "ABCD1234")
        assert (cheat.path, cheat.file_name, cheat.setting) == (
            f"{_EMU}\\PCSX2\\cheats",
            "SLUS-20946_ABCD1234.pnach",
            PCSX2_ENABLE_CHEATS,
        )
        assert patches.toggle is not None and cheats.toggle is not None
        assert patches.toggle.format == TOGGLE_PCSX2_PATCHES
        assert patches.toggle.scan_dir == f"{_EMU}\\PCSX2\\patches"
        assert patches.toggle.scan_prefixes == ("SLUS-20946_ABCD1234", "ABCD1234")
        assert patches.toggle.zip_file == f"{_EMU}\\PCSX2\\resources\\patches.zip"
        assert patches.toggle.zip_members == ("SLUS-20946_ABCD1234.pnach", "ABCD1234.pnach")
        assert patches.toggle.write_file == f"{_EMU}\\PCSX2\\gamesettings\\SLUS-20946_ABCD1234.ini"
        assert cheats.toggle.format == TOGGLE_PCSX2_CHEATS
        assert cheats.toggle.scan_dir == f"{_EMU}\\PCSX2\\cheats"

    def test_folders_from_pcsx2_ini(self):
        ini = "[Folders]\nCheats = D:\\PS2\\cheats\nPatches = mine\\patches\nGameSettings = gs\n"
        cheat, patches, _ = pcsx2_patch_targets(self._HOME, ini, "SLUS-20946", "ABCD1234")
        assert cheat.path == "D:\\PS2\\cheats"
        assert patches.toggle is not None
        assert patches.toggle.scan_dir == f"{_EMU}\\PCSX2\\mine\\patches"
        assert patches.toggle.write_file == f"{_EMU}\\PCSX2\\gs\\SLUS-20946_ABCD1234.ini"

    def test_pnach_matches_serial_first_case_insensitive(self):
        names = ["abcd1234.pnach", "SLUS-20946_ABCD1234_ws.pnach", "SLUS-20946_ABCD1234.pnach", "OTHER.pnach", "x.txt"]
        assert pcsx2_pnach_matches(names, ("SLUS-20946_ABCD1234", "ABCD1234")) == [
            "SLUS-20946_ABCD1234.pnach",
            "SLUS-20946_ABCD1234_ws.pnach",
            "abcd1234.pnach",
        ]


class TestRetroArch:
    _DIR = f"{_EMU}\\RetroArch"

    @pytest.mark.parametrize(
        ("cfg", "expected"),
        [
            (None, f"{_EMU}\\RetroArch\\cheats"),
            ('cheat_database_path = ""\n', f"{_EMU}\\RetroArch\\cheats"),
            ('cheat_database_path = ":\\cheats"\n', f"{_EMU}\\RetroArch\\cheats"),
            ('cheat_database_path = "D:\\RA\\cheats\\"\n', "D:\\RA\\cheats"),
        ],
    )
    def test_cheat_dir(self, cfg, expected):
        assert retroarch_cheat_dir(self._DIR, cfg) == (expected, None)

    def test_relative_cheat_dir_is_refused(self):
        folder, reason = retroarch_cheat_dir(self._DIR, 'cheat_database_path = "cheats"\n')
        assert folder is None
        assert reason is not None and "cheats" in reason

    def test_target_named_by_core_and_content_stem(self):
        target, omitted = retroarch_cheat_target(
            f"{self._DIR}\\cheats", "Snes9x", "C:\\roms\\snes\\Game (USA).sfc", single_file=True
        )
        assert omitted is None and target is not None
        assert (target.path, target.file_name, target.kind) == (
            f"{self._DIR}\\cheats\\Snes9x",
            "Game (USA).cht",
            KIND_CHEAT_FILE,
        )

    @pytest.mark.parametrize(
        ("core", "rom", "single"),
        [("Snes9x", "C:\\r\\g.zip", True), ("Snes9x", "C:\\r\\g.sfc", False), (None, "C:\\r\\g.sfc", True)],
    )
    def test_no_target(self, core, rom, single):
        target, omitted = retroarch_cheat_target("C:\\c", core, rom, single_file=single)
        assert target is None
        assert omitted is not None


class TestCemu:
    _EXE = f"{_EMU}\\cemu\\Cemu.exe"

    def test_portable_folder_wins(self):
        home = cemu_home(self._EXE, portable_dir_exists=True, settings_beside_exe=True)
        assert home.data_root == f"{_EMU}\\cemu\\portable"

    def test_old_install_with_settings_beside_exe(self):
        assert cemu_home(self._EXE, portable_dir_exists=False, settings_beside_exe=True).data_root == f"{_EMU}\\cemu"

    def test_appdata_install_is_not_read(self):
        home = cemu_home(self._EXE, portable_dir_exists=False, settings_beside_exe=False)
        assert home.data_root is None
        assert home.reason is not None and "portable" in home.reason

    def test_graphic_packs_target(self):
        (target,) = cemu_targets(EmulatorHome(CEMU, self._EXE, f"{_EMU}\\cemu\\portable"))
        assert (target.scope, target.kind, target.path) == (
            SCOPE_SHARED,
            KIND_GRAPHICS_MODS,
            f"{_EMU}\\cemu\\portable\\graphicPacks",
        )


class TestNotOffered:
    @pytest.mark.parametrize("emulator", [RPCS3, XENIA, SHADPS4, XEMU, CEMU])
    def test_every_new_emulator_says_why(self, emulator):
        omitted = not_offered(emulator)
        assert omitted
        assert all(o.reason for o in omitted)

    def test_others_have_nothing_to_add(self):
        assert not_offered(DOLPHIN) == ()
