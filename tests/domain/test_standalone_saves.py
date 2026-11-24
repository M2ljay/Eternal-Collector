"""Tests for domain.standalone_saves — exact standalone save sets and server-save mapping."""

import pytest

from domain.standalone_saves import (
    BUNDLE_SUFFIX,
    DUCKSTATION,
    MELONDS,
    STANDALONE_EMULATOR_TAGS,
    VITA3K,
    SaveSetEntry,
    bundle_dir_for,
    bundle_entries,
    bundle_entry_name,
    identify_standalone_emulator,
    standalone_save_set,
    standalone_target_for,
    strip_romm_timestamp_tag,
)


class TestIdentifyStandaloneEmulator:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ('"C:\\Emulation\\tools\\melonDS\\melonDS.exe"', MELONDS),
            ('"C:\\Emulation\\tools\\duckstation\\duckstation-qt-x64-ReleaseLTCG.exe" -batch', DUCKSTATION),
            ('--title-id-file "C:\\Users\\v\\AppData\\Roaming\\Vita3K\\Vita3K.exe" -F -r', VITA3K),
            ('"/opt/emus/melonDS.exe"', MELONDS),
        ],
    )
    def test_known_emulators(self, command, expected):
        assert identify_standalone_emulator(command) == expected

    @pytest.mark.parametrize(
        "command",
        [
            None,
            "",
            "%EMULATOR_MELONDS% %ROM%",  # RetroDECK form: no quoted executable
            '"C:\\RetroArch\\retroarch.exe" -L "cores\\melonds_libretro.dll"',
            '"C:\\Emulation\\tools\\pcsx2\\pcsx2-qt.exe"',
            '"C:\\tools\\ppsspp\\PPSSPPWindows64.exe"',
        ],
    )
    def test_anything_else_is_none(self, command):
        assert identify_standalone_emulator(command) is None


class TestStandaloneSaveSet:
    def test_melonds_is_the_rom_stem_sav(self):
        save_set = standalone_save_set(MELONDS, "Mario Kart DS")
        assert save_set is not None
        assert save_set.emulator_tag == MELONDS
        assert save_set.entries == (SaveSetEntry("Mario Kart DS.sav"),)

    def test_duckstation_is_exactly_the_two_per_game_cards(self):
        save_set = standalone_save_set(DUCKSTATION, "R4 - Ridge Racer Type 4 (USA)")
        assert save_set is not None
        assert save_set.filenames == (
            "R4 - Ridge Racer Type 4 (USA)_1.mcd",
            "R4 - Ridge Racer Type 4 (USA)_2.mcd",
        )
        assert all(entry.bundle_dir is None for entry in save_set.entries)

    def test_vita3k_bundles_the_title_id_folder(self):
        save_set = standalone_save_set(VITA3K, "PCSE01274")
        assert save_set is not None
        assert save_set.entries == (SaveSetEntry("PCSE01274.vita3k.zip", bundle_dir="PCSE01274"),)

    @pytest.mark.parametrize("rom_name", ["Persona 3 Dancing in Moonlight", "pcse01274", "PCSE0127", ""])
    def test_vita3k_needs_a_title_id_stem(self, rom_name):
        assert standalone_save_set(VITA3K, rom_name) is None

    def test_unknown_emulator_or_empty_stem(self):
        assert standalone_save_set("pcsx2", "Game") is None
        assert standalone_save_set(MELONDS, "") is None

    def test_tags_are_the_emulator_ids(self):
        assert {MELONDS, DUCKSTATION, VITA3K} == STANDALONE_EMULATOR_TAGS


class TestBundleNames:
    def test_bundle_dir_for_round_trips(self):
        assert bundle_dir_for(f"PCSE01274{BUNDLE_SUFFIX}") == "PCSE01274"

    @pytest.mark.parametrize(
        "filename",
        ["PCSE01274.zip", "pcse01274.vita3k.zip", "../PCSE01274.vita3k.zip", "Game.srm", "PCSE01274.vita3k.zip.tmp"],
    )
    def test_non_bundles(self, filename):
        assert bundle_dir_for(filename) is None


class TestStripRommTimestampTag:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Tekken 3_1 [2026-03-24_15-18-50].mcd", "Tekken 3_1.mcd"),
            ("PCSE01274.vita3k [2026-03-24_15-18-50].zip", "PCSE01274.vita3k.zip"),
            ("PCSE01274 [2026-03-24_15-18-50].vita3k.zip", "PCSE01274.vita3k.zip"),
            ("R4 - Ridge Racer Type 4 (USA)_1.mcd", "R4 - Ridge Racer Type 4 (USA)_1.mcd"),
            ("Game [Beta].sav", "Game [Beta].sav"),
        ],
    )
    def test_strip(self, raw, expected):
        assert strip_romm_timestamp_tag(raw) == expected


class TestStandaloneTargetFor:
    def _ds(self):
        save_set = standalone_save_set(DUCKSTATION, "R4 - Ridge Racer Type 4 (USA)")
        assert save_set is not None
        return save_set

    def test_tagged_upload_maps_by_name(self):
        save = {
            "id": 1,
            "emulator": DUCKSTATION,
            "file_name": "R4 - Ridge Racer Type 4 (USA)_2 [2026-03-24_15-18-50].mcd",
        }
        assert standalone_target_for(save, self._ds()) == "R4 - Ridge Racer Type 4 (USA)_2.mcd"

    def test_no_tags_plus_extension_is_a_second_route(self):
        save = {
            "id": 1,
            "emulator": DUCKSTATION,
            "file_name": "unparseable",
            "file_name_no_tags": "R4 - Ridge Racer Type 4 (USA)_1",
            "file_extension": "mcd",
        }
        assert standalone_target_for(save, self._ds()) == "R4 - Ridge Racer Type 4 (USA)_1.mcd"

    def test_other_emulator_never_maps(self):
        save = {"id": 1, "emulator": "retroarch-swanstation", "file_name": "R4 - Ridge Racer Type 4 (USA)_1.mcd"}
        assert standalone_target_for(save, self._ds()) is None
        save["emulator"] = None
        assert standalone_target_for(save, self._ds()) is None

    @pytest.mark.parametrize(
        "file_name",
        [
            "R4 - Ridge Racer Type 4_1.mcd",  # DuckStation's title differs from the ROM stem
            "r4 - ridge racer type 4 (usa)_1.mcd",  # case differs
            "R4 - Ridge Racer Type 4 (USA)_3.mcd",
            "R4 - Ridge Racer Type 4 (USA).mcd",
            "shared_card_1.mcd",
            "../R4 - Ridge Racer Type 4 (USA)_1.mcd",
        ],
    )
    def test_never_fuzzy(self, file_name):
        save = {"id": 1, "emulator": DUCKSTATION, "file_name": file_name}
        assert standalone_target_for(save, self._ds()) is None

    def test_tracked_id_keeps_an_own_upload_mapped(self):
        save = {"id": 77, "emulator": DUCKSTATION, "file_name": "renamed by server.bin"}
        tracked = {77: "R4 - Ridge Racer Type 4 (USA)_1.mcd"}
        assert standalone_target_for(save, self._ds(), tracked) == "R4 - Ridge Racer Type 4 (USA)_1.mcd"

    def test_tracked_id_cannot_widen_the_set(self):
        save = {"id": 77, "emulator": DUCKSTATION, "file_name": "x.bin"}
        assert standalone_target_for(save, self._ds(), {77: "../../evil"}) is None

    def test_vita_bundle(self):
        save_set = standalone_save_set(VITA3K, "PCSE01274")
        assert save_set is not None
        save = {"id": 5, "emulator": VITA3K, "file_name": "PCSE01274.vita3k [2026-03-24_15-18-50].zip"}
        assert standalone_target_for(save, save_set) == "PCSE01274.vita3k.zip"
        other = {"id": 6, "emulator": VITA3K, "file_name": "PCSE00023.vita3k [2026-03-24_15-18-50].zip"}
        assert standalone_target_for(other, save_set) is None


class TestBundleEntryName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("SlotParam_0.bin", "SlotParam_0.bin"),
            ("game_dir/MK9PSET", "game_dir/MK9PSET"),
            ("empty/", "empty/"),
            ("a/b/c.dat", "a/b/c.dat"),
        ],
    )
    def test_accepts_plain_relative_names(self, name, expected):
        assert bundle_entry_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "/etc/passwd",
            "../escape",
            "a/../../escape",
            "a/./b",
            "a//b",
            "C:\\Windows\\x",
            "C:x",
            "D:/x",
            "dir\\file",
            "nul\x00byte",
            "..",
            ".",
            "a/..",
        ],
    )
    def test_rejects_anything_that_could_escape(self, name):
        assert bundle_entry_name(name) is None


class TestBundleEntries:
    def test_sorted_with_only_empty_dirs_listed(self):
        assert bundle_entries(["system.bin", "game_dir/MK9PSET", "SlotParam_0.bin"], ["empty"]) == [
            "SlotParam_0.bin",
            "empty/",
            "game_dir/MK9PSET",
            "system.bin",
        ]

    def test_order_independent_of_input_order(self):
        assert bundle_entries(["b", "a"], []) == bundle_entries(["a", "b"], [])
