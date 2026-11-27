"""Tests for domain.game_mods — emulator identification, homes, targets, ini switches, install plans."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.disc_ids import GAMECUBE, N3DS, PS2, PSP, WII, DiscCode
from domain.game_mods import (
    AZAHAR,
    CEMU,
    DOLPHIN,
    DOLPHIN_HIRES_TEXTURES,
    IDENTIFIER_FAMILIES,
    KIND_BUILTIN_TOGGLE,
    KIND_CHEAT_FILE,
    KIND_FILES,
    KIND_GRAPHICS_MODS,
    KIND_LAYERED_FS,
    KIND_RIIVOLUTION,
    PCSX2,
    PCSX2_LOAD_TEXTURE_REPLACEMENTS,
    PPSSPP,
    PPSSPP_REPLACE_TEXTURES,
    RETROARCH,
    RPCS3,
    SCOPE_FILE,
    SCOPE_GAME,
    SCOPE_PATCH,
    SCOPE_SHARED,
    SCOPE_TOGGLE,
    SETTING_OFF,
    SETTING_ON,
    SETTING_UNKNOWN,
    SHADPS4,
    SOURCE_CHEAT,
    SOURCE_FOLDER,
    SOURCE_PATCH,
    SOURCE_UNSUPPORTED_ARCHIVE,
    SOURCE_ZIP,
    TARGET_GRAPHIC_MODS,
    TARGET_MODS,
    TARGET_RIIVOLUTION,
    TARGET_SOFT_PATCH,
    TARGET_TEXTURES,
    XEMU,
    XENIA,
    EmulatorHome,
    InstallPlan,
    ModTarget,
    PlanRefusal,
    SourceEntry,
    azahar_home,
    backup_dir,
    check_against_disk,
    core_needs_fullpath,
    dolphin_home,
    enable_setting,
    identify_mod_emulator,
    ini_value,
    join_path,
    mod_entry_name,
    patch_file_names,
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
    valid_identifier,
)

_EMU = "C:\\Emulation\\Emulators"


class TestIdentifyModEmulator:
    @pytest.mark.parametrize(
        ("exe", "expected"),
        [
            (f"{_EMU}\\RetroArch-Win64\\retroarch.exe", RETROARCH),
            (f"{_EMU}\\Dolphin-x64\\Dolphin.exe", DOLPHIN),
            (f"{_EMU}\\PPSSPP\\PPSSPPWindows64.exe", PPSSPP),
            (f"{_EMU}\\PCSX2-Qt\\pcsx2-qt.exe", PCSX2),
            (f"{_EMU}\\azahar\\azahar.exe", AZAHAR),
            (f"{_EMU}\\citra\\citra-qt.exe", AZAHAR),
            (f"{_EMU}\\lime3ds\\lime3ds-gui.exe", AZAHAR),
            ("/opt/dolphin/dolphin-emu", DOLPHIN),
        ],
    )
    def test_known(self, exe, expected):
        assert identify_mod_emulator(exe) == expected

    @pytest.mark.parametrize(
        ("exe", "expected"),
        [
            (f"{_EMU}\\Cemu\\Cemu.exe", CEMU),
            (f"{_EMU}\\RPCS3\\rpcs3.exe", RPCS3),
            (f"{_EMU}\\xenia\\xenia_canary.exe", XENIA),
            (f"{_EMU}\\shadps4\\shadPS4.exe", SHADPS4),
            (f"{_EMU}\\xemu\\xemu.exe", XEMU),
        ],
    )
    def test_newly_known(self, exe, expected):
        assert identify_mod_emulator(exe) == expected

    @pytest.mark.parametrize("exe", [None, "", f"{_EMU}\\Ryujinx\\Ryujinx.exe", f"{_EMU}\\mGBA\\mGBA.exe"])
    def test_unknown(self, exe):
        assert identify_mod_emulator(exe) is None


class TestJoinPath:
    def test_windows_base_keeps_backslashes(self):
        assert join_path("C:\\a\\", "b", "c") == "C:\\a\\b\\c"

    def test_posix_base_keeps_slashes(self):
        assert join_path("/a/", "b") == "/a/b"


class TestIni:
    def test_read_on_off(self):
        text = "[Settings]\nHiresTextures = True\n"
        assert read_setting(text, DOLPHIN_HIRES_TEXTURES) == (SETTING_ON, True)
        assert read_setting(text.replace("True", "False"), DOLPHIN_HIRES_TEXTURES) == (SETTING_OFF, True)

    def test_case_insensitive_names(self):
        assert read_setting("[settings]\nhirestextures=true\n", DOLPHIN_HIRES_TEXTURES) == (SETTING_ON, True)

    def test_missing_file_uses_default_and_is_not_editable(self):
        assert read_setting(None, DOLPHIN_HIRES_TEXTURES) == (SETTING_OFF, False)
        assert read_setting(None, PPSSPP_REPLACE_TEXTURES) == (SETTING_ON, False)

    def test_absent_key_uses_default_and_is_editable(self):
        assert read_setting("[Settings]\nOther = 1\n", DOLPHIN_HIRES_TEXTURES) == (SETTING_OFF, True)

    def test_odd_value_is_unknown(self):
        assert read_setting("[Settings]\nHiresTextures = 1\n", DOLPHIN_HIRES_TEXTURES) == (SETTING_UNKNOWN, False)

    @pytest.mark.parametrize(
        "text",
        [
            "[Settings]\nHiresTextures = False\n[Settings]\nX = 1\n",
            "[Settings]\nHiresTextures = False\nhirestextures = True\n",
            "[Settings]\nthis line is not ini\n",
        ],
    )
    def test_surprising_format_is_not_editable(self, text):
        assert read_setting(text, DOLPHIN_HIRES_TEXTURES) == (SETTING_UNKNOWN, False)
        assert enable_setting(text, DOLPHIN_HIRES_TEXTURES) is None

    def test_enable_changes_only_the_one_value(self):
        text = "; c\r\n[Settings]\r\nA = 1\r\nHiresTextures   =  False\r\nB = 2\r\n[Hacks]\r\nC = 3\r\n"
        assert enable_setting(text, DOLPHIN_HIRES_TEXTURES) == text.replace(
            "HiresTextures   =  False", "HiresTextures   =  True"
        )

    def test_enable_adds_missing_key_at_end_of_its_section(self):
        text = "[EmuCore/GS]\nA = 1\nB = 2\n\n[Other]\nC = 3\n"
        assert enable_setting(text, PCSX2_LOAD_TEXTURE_REPLACEMENTS) == (
            "[EmuCore/GS]\nA = 1\nB = 2\nLoadTextureReplacements = true\n\n[Other]\nC = 3\n"
        )

    def test_enable_appends_missing_section(self):
        assert enable_setting("[General]\nX = 1\n", PPSSPP_REPLACE_TEXTURES) == (
            "[General]\nX = 1\n\n[Graphics]\nReplaceTextures = True\n"
        )

    def test_enable_on_empty_section_header(self):
        assert enable_setting("[Settings]\n", DOLPHIN_HIRES_TEXTURES) == "[Settings]\nHiresTextures = True\n"

    def test_ini_value(self):
        assert ini_value("[General]\nLoadPath = D:\\Load\n", "general", "loadpath") == "D:\\Load"
        assert ini_value(None, "General", "LoadPath") is None
        assert ini_value("[General]\n", "General", "LoadPath") is None


class TestHomes:
    _DOLPHIN = f"{_EMU}\\Dolphin-x64\\Dolphin.exe"

    def test_dolphin_portable(self):
        home = dolphin_home(self._DOLPHIN, portable=True, user_dir_exists=True, dolphin_ini=None)
        assert home.data_root == f"{_EMU}\\Dolphin-x64\\User"
        assert home.folders["load"] == f"{_EMU}\\Dolphin-x64\\User\\Load"

    def test_dolphin_custom_absolute_load_path(self):
        home = dolphin_home(
            self._DOLPHIN, portable=True, user_dir_exists=True, dolphin_ini="[General]\nLoadPath = D:\\Mods\\Load\\\n"
        )
        assert home.folders["load"] == "D:\\Mods\\Load"

    def test_dolphin_relative_load_path_is_not_guessed(self):
        home = dolphin_home(self._DOLPHIN, portable=True, user_dir_exists=True, dolphin_ini="[General]\nLoadPath = x\n")
        assert home.data_root is None
        assert "not absolute" in (home.reason or "")

    def test_dolphin_not_portable(self):
        home = dolphin_home(self._DOLPHIN, portable=False, user_dir_exists=True, dolphin_ini=None)
        assert home.data_root is None
        assert "portable" in (home.reason or "")

    def test_dolphin_missing_user(self):
        assert dolphin_home(self._DOLPHIN, portable=True, user_dir_exists=False, dolphin_ini=None).data_root is None

    def test_ppsspp(self):
        exe = f"{_EMU}\\PPSSPP\\PPSSPPWindows64.exe"
        assert ppsspp_home(exe, installed_marker=False, memstick_exists=True).data_root == f"{_EMU}\\PPSSPP\\memstick"
        assert ppsspp_home(exe, installed_marker=True, memstick_exists=True).data_root is None
        assert ppsspp_home(exe, installed_marker=False, memstick_exists=False).data_root is None

    def test_pcsx2_default_and_custom_textures(self):
        exe = f"{_EMU}\\PCSX2-Qt\\pcsx2-qt.exe"
        home = pcsx2_home(exe, portable_marker=True, portable_txt="", pcsx2_ini="[EmuCore]\n")
        assert home.folders["textures"] == f"{_EMU}\\PCSX2-Qt\\textures"
        rel = pcsx2_home(exe, portable_marker=True, portable_txt=None, pcsx2_ini="[Folders]\nTextures = tex/packs\n")
        assert rel.folders["textures"] == f"{_EMU}\\PCSX2-Qt\\tex\\packs"
        absolute = pcsx2_home(exe, portable_marker=True, portable_txt=None, pcsx2_ini="[Folders]\nTextures = E:\\T\n")
        assert absolute.folders["textures"] == "E:\\T"

    @pytest.mark.parametrize(
        ("marker", "txt", "ini"),
        [(False, None, "[x]\n"), (True, "D:\\elsewhere", "[x]\n"), (True, None, None)],
    )
    def test_pcsx2_unknown_layouts(self, marker, txt, ini):
        exe = f"{_EMU}\\PCSX2-Qt\\pcsx2-qt.exe"
        assert pcsx2_home(exe, portable_marker=marker, portable_txt=txt, pcsx2_ini=ini).data_root is None

    def test_azahar(self):
        exe = f"{_EMU}\\azahar\\azahar.exe"
        assert azahar_home(exe, user_dir_exists=True).data_root == f"{_EMU}\\azahar\\user"
        assert azahar_home(exe, user_dir_exists=False).data_root is None

    def test_retroarch(self):
        assert retroarch_home(f"{_EMU}\\RA\\retroarch.exe").data_root == f"{_EMU}\\RA"


def _dolphin() -> EmulatorHome:
    return EmulatorHome(DOLPHIN, "x", "C:\\D\\User", folders={"load": "C:\\D\\User\\Load"})


class TestStandaloneTargets:
    def test_dolphin_gamecube(self):
        targets, omitted = standalone_targets(_dolphin(), DiscCode(GAMECUBE, "GALE01"))
        assert [t.target_id for t in targets] == [TARGET_TEXTURES, TARGET_GRAPHIC_MODS]
        assert targets[0].path == "C:\\D\\User\\Load\\Textures\\GALE01"
        assert targets[0].scope == SCOPE_GAME
        assert targets[0].setting is DOLPHIN_HIRES_TEXTURES
        assert targets[1].path == "C:\\D\\User\\Load\\GraphicMods"
        assert targets[1].scope == SCOPE_SHARED
        assert omitted == ()

    def test_dolphin_wii_adds_riivolution(self):
        targets, _ = standalone_targets(_dolphin(), DiscCode(WII, "RMGE01"))
        assert targets[-1].target_id == TARGET_RIIVOLUTION
        assert targets[-1].path == "C:\\D\\User\\Load\\Riivolution"

    def test_ppsspp(self):
        home = EmulatorHome(PPSSPP, "x", "C:\\P\\memstick")
        (target,), _ = standalone_targets(home, DiscCode(PSP, "ULUS10041"))
        assert target.path == "C:\\P\\memstick\\PSP\\TEXTURES\\ULUS10041"
        assert target.setting is PPSSPP_REPLACE_TEXTURES

    def test_pcsx2_textures(self):
        home = EmulatorHome(PCSX2, "x", "C:\\P", folders={"textures": "C:\\P\\textures"})
        (target,), omitted = standalone_targets(home, DiscCode(PS2, "SLUS-20946"))
        assert target.path == "C:\\P\\textures\\SLUS-20946"
        assert target.required_prefix == "replacements"
        assert target.kind == KIND_FILES
        assert omitted == ()

    def test_azahar(self):
        home = EmulatorHome(AZAHAR, "x", "C:\\A\\user")
        targets, _ = standalone_targets(home, DiscCode(N3DS, "0004000000055D00"))
        assert [t.path for t in targets] == [
            "C:\\A\\user\\load\\mods\\0004000000055D00",
            "C:\\A\\user\\load\\textures\\0004000000055D00",
        ]
        assert targets[0].target_id == TARGET_MODS

    @pytest.mark.parametrize(
        ("emulator", "code"),
        [
            (DOLPHIN, None),
            (DOLPHIN, DiscCode(GAMECUBE, "../x01")),
            (PPSSPP, DiscCode(PSP, "ULUS-10041")),
            (PCSX2, DiscCode(PS2, "SLUS20946")),
            (AZAHAR, DiscCode(N3DS, "0004000000055d00")),
        ],
    )
    def test_no_valid_identifier_means_no_target(self, emulator, code):
        assert valid_identifier(emulator, code) is None
        home = EmulatorHome(emulator, "x", "C:\\R", folders={"load": "C:\\L", "textures": "C:\\T"})
        assert standalone_targets(home, code) == ((), ())

    def test_home_without_root_has_no_targets(self):
        assert standalone_targets(EmulatorHome(DOLPHIN, "x", None, "r"), DiscCode(GAMECUBE, "GALE01")) == ((), ())


class TestSoftPatch:
    _HOME = EmulatorHome(RETROARCH, "C:\\RA\\retroarch.exe", "C:\\RA")

    def test_cartridge(self):
        target, omitted = soft_patch_target(
            self._HOME, "C:\\roms\\snes\\Game (USA).sfc", single_file=True, needs_fullpath=False
        )
        assert omitted is None
        assert target is not None
        assert target.target_id == TARGET_SOFT_PATCH
        assert target.scope == SCOPE_PATCH
        assert target.path == "C:\\roms\\snes"
        assert target.patch_stem == "Game (USA)"
        assert any("unverified" in note for note in target.notes)

    def test_unknown_fullpath_is_flagged(self):
        target, _ = soft_patch_target(self._HOME, "C:\\r\\g.nes", single_file=True, needs_fullpath=None)
        assert target is not None
        assert any("loads the game into memory" in n for n in target.notes)

    @pytest.mark.parametrize("path", ["C:\\r\\g.zip", "C:\\r\\g.chd", "C:\\r\\g.cue", "C:\\r\\g.iso"])
    def test_archives_and_discs_are_omitted(self, path):
        target, omitted = soft_patch_target(self._HOME, path, single_file=True, needs_fullpath=False)
        assert target is None
        assert omitted is not None

    def test_folder_rom_and_fullpath_core_are_omitted(self):
        assert soft_patch_target(self._HOME, "C:\\r\\g.sfc", single_file=False, needs_fullpath=False)[0] is None
        target, omitted = soft_patch_target(self._HOME, "C:\\r\\g.sfc", single_file=True, needs_fullpath=True)
        assert target is None
        assert omitted is not None
        assert "from disk" in omitted.reason

    def test_core_needs_fullpath(self):
        assert core_needs_fullpath('display_name = "x"\nneeds_fullpath = "true"\n') is True
        assert core_needs_fullpath('needs_fullpath = "false"\n') is False
        assert core_needs_fullpath('display_name = "x"\n') is None
        assert core_needs_fullpath(None) is None

    def test_patch_file_names(self):
        names = patch_file_names("G")
        assert names[:2] == ("G.ips", "G.ips1")
        assert "G.bps9" in names
        assert "G.xdelta" in names
        assert len(names) == 40


class TestSources:
    @pytest.mark.parametrize(
        ("name", "is_dir", "kind"),
        [
            ("Pack", True, SOURCE_FOLDER),
            ("pack.ZIP", False, SOURCE_ZIP),
            ("hack.bps", False, SOURCE_PATCH),
            ("pack.7z", False, SOURCE_UNSUPPORTED_ARCHIVE),
            ("pack.rar", False, SOURCE_UNSUPPORTED_ARCHIVE),
            ("setup.exe", False, None),
        ],
    )
    def test_kind(self, name, is_dir, kind):
        assert source_kind(name, is_dir=is_dir) == kind

    def test_fits(self):
        game = ModTarget(TARGET_TEXTURES, "t", SCOPE_GAME, "C:\\T", game_folder="GALE01")
        patch = ModTarget(TARGET_SOFT_PATCH, "p", SCOPE_PATCH, "C:\\r", patch_stem="g")
        assert source_fits(game, SOURCE_FOLDER)
        assert not source_fits(game, SOURCE_PATCH)
        assert source_fits(patch, SOURCE_PATCH)
        assert not source_fits(patch, SOURCE_FOLDER)
        assert not source_fits(game, None)


class TestModEntryName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("a/b.png", "a/b.png"), ("a\\b.png", "a/b.png"), ("dir/", "dir"), ("GALE01/tex/x.dds", "GALE01/tex/x.dds")],
    )
    def test_accepted(self, name, expected):
        assert mod_entry_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "/etc/passwd",
            "\\windows\\x",
            "C:/x",
            "C:x",
            "../x",
            "a/../../x",
            "a/./b",
            "a//b",
            "a\x00b",
            "con.txt",
            "a/NUL",
            "a/b.",
            "a/b ",
            "a/b?c",
            "a/b:stream",
        ],
    )
    def test_refused(self, name):
        assert mod_entry_name(name) is None


def _textures(prefix: str | None = None) -> ModTarget:
    return ModTarget(TARGET_TEXTURES, "t", SCOPE_GAME, "C:\\T", game_folder="GALE01", required_prefix=prefix)


def _files(*names: str) -> list[SourceEntry]:
    return [SourceEntry(n, n.endswith("/"), 0 if n.endswith("/") else 10) for n in names]


class TestPlanInstall:
    def test_single_top_folder_named_like_the_game_is_not_nested_twice(self):
        plan = plan_install(_textures(), _files("GALE01/", "GALE01/a.png", "gale01/sub/b.png"))
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["a.png", "sub/b.png"]
        assert plan.stripped_folder == "GALE01"
        assert plan.total_bytes == 20

    def test_other_wrapper_is_kept(self):
        plan = plan_install(_textures(), _files("Pack/a.png"))
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["Pack/a.png"]
        assert plan.stripped_folder is None

    def test_loose_file_named_like_the_game_folder_is_not_stripped(self):
        plan = plan_install(_textures(), _files("GALE01/a.png", "readme.txt"))
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["GALE01/a.png", "readme.txt"]

    def test_required_prefix_added_where_missing(self):
        plan = plan_install(_textures("replacements"), _files("GALE01/replacements/a.dds", "GALE01/b.dds"))
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["replacements/a.dds", "replacements/b.dds"]

    def test_prefix_collision_refused(self):
        plan = plan_install(_textures("replacements"), _files("a.dds", "replacements/a.dds"))
        assert isinstance(plan, PlanRefusal)

    @pytest.mark.parametrize(
        "entries",
        [
            _files("../evil.png"),
            _files("ok.png", "/abs.png"),
            _files("C:/Windows/x.dll"),
            [SourceEntry("link", False, 0, link=True)],
            _files("a.png", "A.PNG"),
            _files("a", "a/b.png"),
        ],
    )
    def test_unsafe_sources_are_refused_whole(self, entries):
        plan = plan_install(_textures(), entries)
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "unsafe_source"

    def test_empty(self):
        plan = plan_install(_textures(), _files("dir/"))
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "empty_source"

    def test_shared_folder_keeps_layout(self):
        target = ModTarget(TARGET_GRAPHIC_MODS, "g", SCOPE_SHARED, "C:\\G")
        plan = plan_install(target, _files("Mod/metadata.json", "Mod/a.png"))
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["Mod/metadata.json", "Mod/a.png"]

    def test_patch_renamed_to_rom_stem(self):
        target = ModTarget(TARGET_SOFT_PATCH, "p", SCOPE_PATCH, "C:\\r", patch_stem="Game (USA)")
        plan = plan_install(target, _files("Hack v1.2/hack.BPS", "Hack v1.2/readme.txt"))
        assert isinstance(plan, InstallPlan)
        assert [(w.source, w.dest) for w in plan.writes] == [("Hack v1.2/hack.BPS", "Game (USA).bps")]

    @pytest.mark.parametrize("names", [("readme.txt",), ("a.ips", "b.ups")])
    def test_patch_needs_exactly_one(self, names):
        target = ModTarget(TARGET_SOFT_PATCH, "p", SCOPE_PATCH, "C:\\r", patch_stem="g")
        plan = plan_install(target, _files(*names))
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "not_one_patch"

    def test_too_large(self):
        plan = plan_install(_textures(), [SourceEntry("a.png", False, 100 * 1024**3)])
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "too_large"


class TestCheckAgainstDisk:
    def _plan(self) -> InstallPlan:
        plan = plan_install(_textures(), _files("sub/a.png", "b.png"))
        assert isinstance(plan, InstallPlan)
        return plan

    def test_dirs(self):
        assert plan_dirs(self._plan()) == ("sub",)

    def test_existing_files_are_replaced(self):
        check = check_against_disk(self._plan(), {"b.png": "file", "sub": "dir"})
        assert check.replaces == frozenset({"b.png"})
        assert check.blocked == ()

    def test_shape_conflicts_block(self):
        check = check_against_disk(self._plan(), {"sub": "file", "b.png": "dir"})
        assert set(check.blocked) == {"sub", "b.png"}

    def test_fingerprint_moves_with_inputs(self):
        plan = self._plan()
        none = check_against_disk(plan, {})
        one = check_against_disk(plan, {"b.png": "file"})
        assert plan_fingerprint("s", plan, none) == plan_fingerprint("s", plan, none)
        assert plan_fingerprint("s", plan, none) != plan_fingerprint("t", plan, none)
        assert plan_fingerprint("s", plan, none) != plan_fingerprint("s", plan, one)


class TestRemovable:
    def test_whole_game_folder(self):
        assert removable_name(_textures(), None) == "GALE01"
        assert removable_name(ModTarget(TARGET_GRAPHIC_MODS, "g", SCOPE_SHARED, "C:\\G"), None) is None

    def test_plain_names_only(self):
        assert removable_name(_textures(), "sub") == "sub"
        assert removable_name(_textures(), "..") is None
        assert removable_name(_textures(), "a/b") is None
        assert removable_name(_textures(), "C:x") is None

    def test_patch_only_own_names(self):
        target = ModTarget(TARGET_SOFT_PATCH, "p", SCOPE_PATCH, "C:\\r", patch_stem="g")
        assert removable_name(target, "g.ips") == "g.ips"
        assert removable_name(target, "g.sfc") is None
        assert removable_name(target, "other.ips") is None


def test_backup_dir():
    assert backup_dir("C:\\D\\User", "20261124-1-ab", "textures") == (
        "C:\\D\\User\\romm-mod-backups\\20261124-1-ab\\textures"
    )


def test_forge_bridge_identifier_families_mirror_the_domain():
    """The mods bridge reports ``family`` from a copy of ``IDENTIFIER_FAMILIES`` in the frontend; keep them equal."""
    source = (Path(__file__).resolve().parents[2] / "src" / "utils" / "collectorModsBridge.ts").read_text("utf-8")
    block = re.search(r"const IDENTIFIER_FAMILIES[^{]*\{(?P<body>[^}]*)\}", source)
    assert block is not None
    mirrored = dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group("body")))
    assert mirrored == IDENTIFIER_FAMILIES


class TestSingleFileTargets:
    _CHEAT = ModTarget(
        "cheats",
        "Cheat file (.pnach)",
        SCOPE_FILE,
        "C:\\PCSX2\\cheats",
        kind=KIND_CHEAT_FILE,
        file_name="SLUS-20946_ABCD1234.pnach",
        file_ext=".pnach",
    )
    _TOGGLE = ModTarget("patches", "Patches", SCOPE_TOGGLE, "C:\\PCSX2\\gamesettings", kind=KIND_BUILTIN_TOGGLE)

    def test_cheat_sources(self):
        assert source_kind("codes.pnach", is_dir=False) == SOURCE_CHEAT
        assert source_kind("0004000000055D00.TXT", is_dir=False) == SOURCE_CHEAT
        assert source_fits(self._CHEAT, SOURCE_CHEAT)
        assert source_fits(self._CHEAT, SOURCE_ZIP)
        assert not source_fits(self._CHEAT, SOURCE_FOLDER)
        assert not source_fits(self._TOGGLE, SOURCE_ZIP)

    def test_one_matching_file_is_renamed(self):
        plan = plan_install(
            self._CHEAT, [SourceEntry("pack/readme.md", False, 3), SourceEntry("pack/sotc.pnach", False, 9)]
        )
        assert isinstance(plan, InstallPlan)
        assert [(w.source, w.dest) for w in plan.writes] == [("pack/sotc.pnach", "SLUS-20946_ABCD1234.pnach")]

    @pytest.mark.parametrize(
        "entries",
        [
            [SourceEntry("a.txt", False, 1)],
            [SourceEntry("a.pnach", False, 1), SourceEntry("b.pnach", False, 1)],
        ],
    )
    def test_not_exactly_one_file_is_refused(self, entries):
        plan = plan_install(self._CHEAT, entries)
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "not_one_file"

    def test_toggle_targets_are_never_installed(self):
        plan = plan_install(self._TOGGLE, [SourceEntry("a.zip", False, 1)])
        assert isinstance(plan, PlanRefusal)
        assert plan.reason == "not_installable"

    def test_removal_takes_only_the_named_file(self):
        assert removable_name(self._CHEAT, "SLUS-20946_ABCD1234.pnach") == "SLUS-20946_ABCD1234.pnach"
        assert removable_name(self._CHEAT, "other.pnach") is None
        assert removable_name(self._CHEAT, None) is None
        assert removable_name(self._TOGGLE, "anything") is None

    def test_existing_targets_carry_their_kind(self):
        home = EmulatorHome(DOLPHIN, "x", "C:\\D\\User", folders={"load": "C:\\D\\User\\Load"})
        targets, _ = standalone_targets(home, DiscCode(WII, "RMGE01"))
        assert [t.kind for t in targets] == [KIND_FILES, KIND_GRAPHICS_MODS, KIND_RIIVOLUTION]
        azahar, _ = standalone_targets(EmulatorHome(AZAHAR, "x", "C:\\A\\user"), DiscCode(N3DS, "0004000000055D00"))
        assert [t.kind for t in azahar] == [KIND_LAYERED_FS, KIND_FILES]
