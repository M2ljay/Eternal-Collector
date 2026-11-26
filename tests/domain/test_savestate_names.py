"""Tests for ``domain.savestate_names`` — slots, RetroArch names, server names, core table."""

from __future__ import annotations

import pytest

from domain.savestate_names import (
    ALL_SLOTS,
    NUMBERED_SLOTS,
    RETROARCH_DIR_BY_ROMM_EMULATOR,
    ROMM_EMULATOR_BY_RETROARCH_DIR,
    SLOT_AUTO,
    core_id,
    device_short_id,
    local_savestate_name,
    local_savestate_names,
    romm_emulator_for_core,
    screenshot_name,
    server_savestate_name,
    slot_suffix,
    slots_for_scope,
    split_savestate_name,
)


class TestSlotVocabulary:
    def test_auto_then_zero_to_nine(self):
        assert ALL_SLOTS == ("auto", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")
        assert ALL_SLOTS[1:] == NUMBERED_SLOTS

    def test_auto_scope_is_the_auto_state_alone(self):
        assert slots_for_scope("auto") == (SLOT_AUTO,)

    def test_all_scope_is_every_slot(self):
        assert slots_for_scope("all") == ALL_SLOTS

    @pytest.mark.parametrize("scope", ["", "ALL", "everything", None])
    def test_unknown_scope_never_widens(self, scope):
        assert slots_for_scope(scope) == (SLOT_AUTO,)  # type: ignore[arg-type]  # deliberately not a str


class TestSlotSuffix:
    @pytest.mark.parametrize(
        ("slot", "suffix"),
        [("auto", ".state.auto"), ("0", ".state"), ("1", ".state1"), ("9", ".state9")],
    )
    def test_retroarch_suffixes(self, slot, suffix):
        assert slot_suffix(slot) == suffix

    @pytest.mark.parametrize("slot", ["10", "-1", "", "state"])
    def test_unknown_slot_raises(self, slot):
        with pytest.raises(ValueError, match="unknown savestate slot"):
            slot_suffix(slot)


class TestLocalNames:
    def test_name_is_stem_plus_suffix(self):
        assert local_savestate_name("Chrono Trigger (USA)", "auto") == "Chrono Trigger (USA).state.auto"
        assert local_savestate_name("Chrono Trigger (USA)", "0") == "Chrono Trigger (USA).state"

    def test_stem_with_dots_is_kept_whole(self):
        assert local_savestate_name("Final Fantasy VI v1.1", "3") == "Final Fantasy VI v1.1.state3"

    def test_empty_stem_raises(self):
        with pytest.raises(ValueError, match="stem"):
            local_savestate_name("", "auto")

    def test_probe_list_follows_the_slot_order(self):
        assert local_savestate_names("Game", ("auto", "0", "2")) == (
            ("auto", "Game.state.auto"),
            ("0", "Game.state"),
            ("2", "Game.state2"),
        )


class TestSplitSavestateName:
    def test_auto_state_is_one_two_part_suffix(self):
        # A last-dot split would read stem "Game.state" with suffix ".auto".
        assert split_savestate_name("Game.state.auto") == ("Game", "auto")

    def test_stem_containing_state_keeps_it(self):
        assert split_savestate_name("Game.state.state.auto") == ("Game.state", "auto")

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("Game.state", ("Game", "0")), ("Game.state1", ("Game", "1")), ("Game v1.1.state9", ("Game v1.1", "9"))],
    )
    def test_numbered_slots(self, name, expected):
        assert split_savestate_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "Game.state10",
            "Game.state0",
            "Game.srm",
            "Game.state.auto.png",
            ".state.auto",
            ".state",
            "Game",
            "Game.statex",
        ],
    )
    def test_non_savestates_answer_none(self, name):
        assert split_savestate_name(name) is None

    @pytest.mark.parametrize("slot", ALL_SLOTS)
    def test_round_trips_every_slot(self, slot):
        assert split_savestate_name(local_savestate_name("Game (USA)", slot)) == ("Game (USA)", slot)


class TestScreenshotName:
    def test_screenshot_is_the_full_savestate_name_plus_png(self):
        assert screenshot_name("Game.state.auto") == "Game.state.auto.png"
        assert screenshot_name("Game [ab12cd34].state1") == "Game [ab12cd34].state1.png"


class TestDeviceShortId:
    def test_first_eight_alphanumerics_lowercased(self):
        assert device_short_id("3F2A9C1E-7B4D-4E0A-9C3B-1234567890AB") == "3f2a9c1e"

    def test_short_ids_are_kept_whole(self):
        assert device_short_id("ab-12") == "ab12"

    def test_punctuation_only_id_raises(self):
        with pytest.raises(ValueError, match="no letters or digits"):
            device_short_id("---")


class TestServerSavestateName:
    @pytest.mark.parametrize(
        ("slot", "expected"),
        [
            ("auto", "Chrono Trigger (USA) [3f2a9c1e].state.auto"),
            ("0", "Chrono Trigger (USA) [3f2a9c1e].state"),
            ("4", "Chrono Trigger (USA) [3f2a9c1e].state4"),
        ],
    )
    def test_stem_device_tag_slot_suffix(self, slot, expected):
        assert server_savestate_name("Chrono Trigger (USA)", "3f2a9c1e", slot) == expected

    def test_two_devices_never_share_a_name(self):
        assert server_savestate_name("Game", "aaaa1111", "auto") != server_savestate_name("Game", "bbbb2222", "auto")

    def test_server_name_still_splits_to_its_slot(self):
        assert split_savestate_name(server_savestate_name("Game", "aaaa1111", "auto")) == ("Game [aaaa1111]", "auto")

    def test_empty_short_id_raises(self):
        with pytest.raises(ValueError, match="short-id"):
            server_savestate_name("Game", "", "auto")


class TestCoreTable:
    def test_core_id_strips_the_libretro_suffix(self):
        assert core_id("snes9x_libretro") == "snes9x"
        assert core_id("mupen64plus_next_libretro") == "mupen64plus_next"
        assert core_id("custom") == "custom"

    @pytest.mark.parametrize(
        ("core_so", "corename", "expected"),
        [
            ("snes9x_libretro", "Snes9x", "snes9x"),
            ("mupen64plus_next_libretro", None, "mupen64plus_next"),
            ("mednafen_psx_hw_libretro", "Beetle PSX HW", "mednafen_psx_hw"),
            ("swanstation_libretro", "SwanStation", "swanstation"),
        ],
    )
    def test_core_known_to_romm_keeps_its_own_id(self, core_so, corename, expected):
        assert romm_emulator_for_core(core_so, corename) == expected

    def test_unlisted_core_id_falls_back_to_the_folder_name(self):
        # mgba is listed, so take a hypothetical renamed build of it.
        assert romm_emulator_for_core("mgba_dev_libretro", "mGBA") == "mgba"

    def test_beetle_folder_maps_to_the_mednafen_id_romm_uses(self):
        assert ROMM_EMULATOR_BY_RETROARCH_DIR["Beetle PSX"] == "mednafen_psx"
        assert ROMM_EMULATOR_BY_RETROARCH_DIR["Beetle PCE Fast"] == "mednafen_pce_fast"

    def test_unknown_core_keeps_its_own_id(self):
        assert romm_emulator_for_core("bluemsx_libretro", "blueMSX") == "bluemsx"
        assert romm_emulator_for_core("bluemsx_libretro", None) == "bluemsx"

    def test_table_matches_romm_5_4_1(self):
        assert len(RETROARCH_DIR_BY_ROMM_EMULATOR) == 45
        assert RETROARCH_DIR_BY_ROMM_EMULATOR["snes9x"] == "Snes9x"
        assert RETROARCH_DIR_BY_ROMM_EMULATOR["mupen64plus_next"] == "Mupen64Plus-Next"
