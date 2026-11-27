"""Tests for domain.mod_toggles — reading and switching Dolphin, PCSX2 and Azahar entries, per format."""

from __future__ import annotations

import pytest

from domain.mod_toggles import (
    DOLPHIN_ACTION_REPLAY,
    DOLPHIN_GECKO,
    ORIGIN_BUILTIN,
    ORIGIN_USER,
    PCSX2_CHEATS,
    PCSX2_PATCHES,
    azahar_cheats,
    azahar_set_cheat,
    dolphin_codes,
    dolphin_game_ini_names,
    dolphin_set_code,
    pcsx2_enabled,
    pcsx2_entries,
    pcsx2_set_enabled,
    plain_entry_name,
    pnach_groups,
)

_SYS = (
    "[Gecko]\r\n"
    "$Widescreen 16:9 [Ralf]\r\n"
    "04000000 00000000\r\n"
    "*Makes the game wide\r\n"
    "+$Always On\r\n"
    "04000004 00000001\r\n"
    "[Gecko_Enabled]\r\n"
    "$Widescreen Fix\r\n"
    "[ActionReplay]\r\n"
    "$Infinite Lives\r\n"
    "00000000 00000000\r\n"
)


class TestDolphinIniNames:
    def test_disc_id_with_revision(self):
        assert dolphin_game_ini_names("GALE01", 2) == ("G.ini", "GAL.ini", "GALE01.ini", "GALE01r2.ini")

    def test_without_revision(self):
        assert dolphin_game_ini_names("GALE01", None) == ("G.ini", "GAL.ini", "GALE01.ini")


class TestDolphinCodes:
    def test_lists_shipped_codes_with_their_defaults(self):
        listing = dolphin_codes(DOLPHIN_GECKO, [None, None, _SYS], [], "GALE01.ini")
        assert listing.editable is True
        by_name = {e.name: e for e in listing.entries}
        assert list(by_name) == ["Widescreen 16:9", "Always On"]
        assert by_name["Widescreen 16:9"].enabled is False
        assert by_name["Always On"].enabled is True
        assert by_name["Always On"].origin == ORIGIN_BUILTIN

    def test_user_ini_switches_and_adds_codes(self):
        user = (
            "[Gecko]\n$My Code\n04000008 00000002\n"
            "[Gecko_Enabled]\n$Widescreen 16:9\n$My Code\n"
            "[Gecko_Disabled]\n$Always On\n"
        )
        listing = dolphin_codes(DOLPHIN_GECKO, [_SYS], [("GALE01.ini", user)], "GALE01.ini")
        state = {e.name: (e.enabled, e.origin) for e in listing.entries}
        assert state == {
            "Widescreen 16:9": (True, ORIGIN_BUILTIN),
            "Always On": (False, ORIGIN_BUILTIN),
            "My Code": (True, ORIGIN_USER),
        }

    def test_action_replay_names_are_the_whole_line(self):
        listing = dolphin_codes(DOLPHIN_ACTION_REPLAY, [_SYS], [], "GALE01.ini")
        assert [e.name for e in listing.entries] == ["Infinite Lives"]

    def test_another_user_file_switching_codes_is_read_only(self):
        listing = dolphin_codes(DOLPHIN_GECKO, [_SYS], [("GAL.ini", "[Gecko_Enabled]\n$Always On\n")], "GALE01.ini")
        assert listing.editable is False
        assert "GAL.ini" in (listing.reason or "")
        assert all(not e.can_toggle for e in listing.entries)

    def test_repeated_section_is_refused(self):
        listing = dolphin_codes(DOLPHIN_GECKO, [_SYS], [("GALE01.ini", "[Gecko]\n[Gecko]\n")], "GALE01.ini")
        assert listing.editable is False
        assert listing.entries == ()


class TestDolphinSetCode:
    def test_enabling_a_default_off_code_lists_it_enabled(self):
        text = "[Core]\r\nCPUThread = True\r\n"
        out = dolphin_set_code(text, DOLPHIN_GECKO, "Widescreen 16:9", True, False)
        assert out == "[Core]\r\nCPUThread = True\r\n\r\n[Gecko_Enabled]\r\n$Widescreen 16:9\r\n"

    def test_disabling_a_default_on_code_lists_it_disabled(self):
        out = dolphin_set_code(None, DOLPHIN_GECKO, "Always On", False, True)
        assert out == "[Gecko_Disabled]\r\n$Always On\r\n"

    def test_back_to_default_removes_the_line_and_keeps_others(self):
        text = "[Gecko_Enabled]\n$Widescreen 16:9\n$Other\n[Video]\nX = 1\n"
        out = dolphin_set_code(text, DOLPHIN_GECKO, "Widescreen 16:9", False, False)
        assert out == "[Gecko_Enabled]\n$Other\n[Video]\nX = 1\n"

    def test_adds_into_an_existing_section_before_its_trailing_blank(self):
        text = "[Gecko_Enabled]\n$Other\n\n[Video]\n"
        out = dolphin_set_code(text, DOLPHIN_GECKO, "New", True, False)
        assert out == "[Gecko_Enabled]\n$Other\n$New\n\n[Video]\n"

    def test_round_trips_through_the_reader(self):
        out = dolphin_set_code(None, DOLPHIN_GECKO, "Widescreen 16:9", True, False)
        listing = dolphin_codes(DOLPHIN_GECKO, [_SYS], [("GALE01.ini", out)], "GALE01.ini")
        assert {e.name: e.enabled for e in listing.entries}["Widescreen 16:9"] is True

    @pytest.mark.parametrize("name", ["", " padded", "line\nbreak"])
    def test_refuses_names_that_cannot_stand_on_a_line(self, name):
        assert dolphin_set_code(None, DOLPHIN_GECKO, name, True, False) is None

    def test_refuses_a_file_with_a_repeated_section(self):
        assert dolphin_set_code("[A]\n[A]\n", DOLPHIN_GECKO, "x", True, False) is None


_PNACH = (
    "gametitle=Shadow of the Colossus\n"
    "[Widescreen 16:9]\n"
    "author=someone\n"
    "description=Renders in 16:9 // with HUD fix\n"
    "patch=1,EE,0012AB00,word,3F400000\n"
    "[60 FPS]\n"
    "comment=Doubles the frame rate\n"
    "patch=1,EE,00200000,word,00000001\n"
    "[Widescreen 16:9]\n"
    "description=duplicate, ignored\n"
)


class TestPnach:
    def test_groups_descriptions_and_first_name_wins(self):
        groups, unlabelled = pnach_groups(_PNACH)
        assert groups == [("Widescreen 16:9", "Renders in 16:9"), ("60 FPS", "Doubles the frame rate")]
        assert unlabelled is False

    def test_patch_line_before_any_label_is_unlabelled(self):
        _groups, unlabelled = pnach_groups("patch=1,EE,00000000,word,0\n[Later]\n")
        assert unlabelled is True

    def test_comment_lines_are_skipped(self):
        groups, _ = pnach_groups("// [Not a label]\n[Real]\npatch=1,EE,0,word,0\n")
        assert groups == [("Real", "")]


class TestPcsx2Settings:
    def test_reads_the_repeated_enable_list(self):
        text = "[Patches]\nEnable = Widescreen 16:9\nEnable = 60 FPS\n[Cheats]\nEnable = Max Money\n"
        assert pcsx2_enabled(text, PCSX2_PATCHES) == {"Widescreen 16:9", "60 FPS"}
        assert pcsx2_enabled(text, PCSX2_CHEATS) == {"Max Money"}

    def test_absent_file_has_nothing_enabled(self):
        assert pcsx2_enabled(None, PCSX2_PATCHES) == set()

    def test_repeated_ordinary_key_is_unreadable(self):
        assert pcsx2_enabled("[EmuCore]\nEnableCheats = true\nEnableCheats = false\n", PCSX2_PATCHES) is None

    def test_adds_after_the_section_last_key(self):
        text = "[Patches]\r\nEnable = 60 FPS\r\n\r\n[EmuCore]\r\nEnableCheats = true\r\n"
        out = pcsx2_set_enabled(text, PCSX2_PATCHES, "Widescreen 16:9", True)
        assert (
            out
            == "[Patches]\r\nEnable = 60 FPS\r\nEnable = Widescreen 16:9\r\n\r\n[EmuCore]\r\nEnableCheats = true\r\n"
        )

    def test_creates_the_section_and_the_file(self):
        assert pcsx2_set_enabled(None, PCSX2_CHEATS, "Max Money", True) == "[Cheats]\r\nEnable = Max Money\r\n"
        out = pcsx2_set_enabled("[EmuCore]\nX = 1\n", PCSX2_CHEATS, "Max Money", True)
        assert out == "[EmuCore]\nX = 1\n\n[Cheats]\nEnable = Max Money\n"

    def test_removes_every_matching_line_only_in_its_section(self):
        text = "[Patches]\nEnable = A\nEnable = B\nEnable = A\n[Cheats]\nEnable = A\n"
        assert pcsx2_set_enabled(text, PCSX2_PATCHES, "A", False) == "[Patches]\nEnable = B\n[Cheats]\nEnable = A\n"

    def test_already_present_is_unchanged(self):
        text = "[Patches]\nEnable = A\n"
        assert pcsx2_set_enabled(text, PCSX2_PATCHES, "A", True) == text

    @pytest.mark.parametrize("name", ["; comment", "# x", " padded"])
    def test_refuses_names_the_ini_reader_would_misread(self, name):
        assert pcsx2_set_enabled(None, PCSX2_PATCHES, name, True) is None

    def test_entries_mark_enabled_and_list_unlabelled_files(self):
        listing = pcsx2_entries(
            [("SLUS-20946_ABCD1234.pnach", "patch=1,EE,0,word,0\n"), ("built-in", _PNACH)],
            {"60 FPS"},
            editable=True,
        )
        names = [(e.name, e.enabled, e.can_toggle) for e in listing.entries]
        assert names == [
            ("Widescreen 16:9", False, True),
            ("60 FPS", True, True),
            ("Unlabelled patches in SLUS-20946_ABCD1234.pnach", True, False),
        ]


_AZAHAR = "[Infinite HP]\n*citra_enabled\n*Keeps HP full\n12345678 00000063\n\n[Max Coins]\n87654321 0000270F\n"


class TestAzahar:
    def test_lists_cheats_and_state(self):
        listing = azahar_cheats(_AZAHAR, "0004000000055D00.txt")
        assert [(e.name, e.enabled) for e in listing.entries] == [("Infinite HP", True), ("Max Coins", False)]
        assert listing.editable is True

    def test_absent_file_has_none(self):
        assert azahar_cheats(None, "x.txt").entries == ()

    @pytest.mark.parametrize(
        "text",
        [
            "12345678 00000001\n[A]\n12345678 00000001\n",
            "[Empty]\n[B]\n12345678 00000001\n",
            "[A]\n1 2\n[A]\n3 4\n",
        ],
    )
    def test_files_azahar_would_misread_are_read_only(self, text):
        listing = azahar_cheats(text, "x.txt")
        assert listing.editable is False
        assert listing.entries == ()

    def test_enable_puts_the_marker_right_after_the_header(self):
        out = azahar_set_cheat(_AZAHAR, "Max Coins", True)
        assert out is not None
        assert "[Max Coins]\n*citra_enabled\n87654321 0000270F\n" in out
        assert azahar_cheats(out, "x").entries[1].enabled is True

    def test_disable_removes_the_marker_and_keeps_comments(self):
        out = azahar_set_cheat(_AZAHAR, "Infinite HP", False)
        assert out == "[Infinite HP]\n*Keeps HP full\n12345678 00000063\n\n[Max Coins]\n87654321 0000270F\n"

    def test_unknown_name_is_refused(self):
        assert azahar_set_cheat(_AZAHAR, "Nope", True) is None


class TestPlainEntryName:
    @pytest.mark.parametrize(("name", "ok"), [("A b", True), ("", False), ("a ", False), ("a\tb", False)])
    def test_rule(self, name, ok):
        assert plain_entry_name(name) is ok
