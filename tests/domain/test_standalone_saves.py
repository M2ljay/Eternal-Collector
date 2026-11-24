"""Tests for domain.standalone_saves — exact standalone save sets and server-save mapping."""

import pytest

from domain.disc_ids import GAMECUBE, PS2, PSP, WII, DiscCode
from domain.save_bundles import DIR_MEMBERS, GCI_MEMBERS
from domain.standalone_saves import (
    BUNDLE_SUFFIX,
    DOLPHIN,
    DUCKSTATION,
    MELONDS,
    PCSX2,
    PPSSPP,
    STANDALONE_EMULATOR_TAGS,
    VITA3K,
    SaveSetEntry,
    bundle_dir_for,
    bundle_layout,
    disc_save_set,
    emulator_executable,
    identify_standalone_emulator,
    is_bundle_filename,
    pcsx2_slot1_card,
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
            ('"C:\\Emulation\\tools\\pcsx2\\pcsx2-qtx64-avx2.exe"', PCSX2),
            ('"C:\\tools\\ppsspp\\PPSSPPWindows64.exe"', PPSSPP),
            ('"C:\\Users\\v\\AppData\\Roaming\\EmuDeck\\Emulators\\Dolphin-x64\\Dolphin.exe" -b -e', DOLPHIN),
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
            '"C:\\Emulation\\tools\\rpcs3\\rpcs3.exe"',
            '"C:\\tools\\cemu\\Cemu.exe"',
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
        assert {MELONDS, DUCKSTATION, VITA3K, DOLPHIN, PPSSPP, PCSX2} == STANDALONE_EMULATOR_TAGS


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


class TestDiscSaveSet:
    def test_dolphin_gamecube(self):
        save_set = disc_save_set(DOLPHIN, DiscCode(GAMECUBE, "GALE01"))
        assert save_set is not None
        assert save_set.emulator_tag == DOLPHIN
        assert save_set.filenames == ("GALE01.dolphin-gc.zip",)
        layout = save_set.layout_for("GALE01.dolphin-gc.zip")
        assert layout is not None
        assert layout.label == "GALE01.dolphin-gc"
        assert [(s.directory, s.prefix, s.kind, s.pattern) for s in layout.sources] == [
            ("GC/USA/Card A", "Card A/", GCI_MEMBERS, "GALE"),
            ("GC/USA/Card B", "Card B/", GCI_MEMBERS, "GALE"),
        ]

    @pytest.mark.parametrize(("id6", "region"), [("GRSPAF", "EUR"), ("GRSJAF", "JAP")])
    def test_dolphin_gamecube_region_folder(self, id6, region):
        save_set = disc_save_set(DOLPHIN, DiscCode(GAMECUBE, id6))
        assert save_set is not None
        layout = save_set.entries[0].layout
        assert layout is not None
        assert layout.sources[0].directory == f"GC/{region}/Card A"

    def test_dolphin_gamecube_unknown_region_has_no_set(self):
        assert disc_save_set(DOLPHIN, DiscCode(GAMECUBE, "GALX01")) is None

    def test_dolphin_wii(self):
        save_set = disc_save_set(DOLPHIN, DiscCode(WII, "SMOXE8"))
        assert save_set is not None
        assert save_set.filenames == ("SMOX.dolphin-wii.zip",)
        layout = save_set.layout_for("SMOX.dolphin-wii.zip")
        assert layout is not None
        assert layout.folder == "Wii/title/00010000/534d4f58/data"
        assert layout.label == "SMOX.dolphin-wii"

    def test_ppsspp(self):
        save_set = disc_save_set(PPSSPP, DiscCode(PSP, "ULUS10234"))
        assert save_set is not None
        assert save_set.filenames == ("ULUS10234.ppsspp.zip",)
        layout = save_set.entries[0].layout
        assert layout is not None
        (source,) = layout.sources
        assert (source.directory, source.prefix, source.kind) == ("saves", "", DIR_MEMBERS)
        assert source.owns_name("ULUS10234DATA00") and source.owns_name("ULUS10234SYS")
        assert not source.owns_name("ULUS10235DATA00")

    def test_pcsx2(self):
        save_set = disc_save_set(PCSX2, DiscCode(PS2, "SLUS-20062"), "memcard.ps2")
        assert save_set is not None
        assert save_set.filenames == ("SLUS-20062.pcsx2.zip",)
        layout = save_set.entries[0].layout
        assert layout is not None
        (source,) = layout.sources
        assert source.directory == "saves/memcard.ps2"
        assert source.owns_name("BASLUS-20062GTA30000")
        assert source.owns_name("BESLUS-20062X")
        for other in ("BASLUS-21645SD8_0", "_pcsx2_superblock", "_pcsx2_index", "Mcd001.ps2", "BASLUS-2006"):
            assert not source.owns_name(other)

    @pytest.mark.parametrize("card", [None, "", "..", "a/b", "C:\\x"])
    def test_pcsx2_needs_a_plain_card_name(self, card):
        assert disc_save_set(PCSX2, DiscCode(PS2, "SLUS-20062"), card) is None

    def test_platform_mismatch(self):
        assert disc_save_set(PPSSPP, DiscCode(PS2, "SLUS-20062")) is None
        assert disc_save_set(DOLPHIN, DiscCode(PSP, "ULUS10234")) is None
        assert disc_save_set(MELONDS, DiscCode(GAMECUBE, "GALE01")) is None


class TestPcsx2Slot1Card:
    _INI = "[Folders]\nMemoryCards = memcards\n\n[MemoryCards]\nSlot1_Enable = true\nSlot1_Filename = memcard.ps2\n"

    def test_folder_card_name(self):
        assert pcsx2_slot1_card(self._INI) == "memcard.ps2"

    def test_memcards_folder_defaults_when_absent(self):
        assert pcsx2_slot1_card("[MemoryCards]\nSlot1_Enable = true\nSlot1_Filename = Mcd001.ps2\n") == "Mcd001.ps2"

    def test_disabled_slot(self):
        assert pcsx2_slot1_card(self._INI.replace("Slot1_Enable = true", "Slot1_Enable = false")) is None

    def test_relocated_memcards_folder(self):
        assert pcsx2_slot1_card(self._INI.replace("= memcards", "= D:\\cards")) is None

    @pytest.mark.parametrize("name", ["", "..\\x", "a/b"])
    def test_unsafe_filename(self, name):
        assert pcsx2_slot1_card(self._INI.replace("memcard.ps2", name)) is None

    def test_slot2_is_ignored(self):
        assert pcsx2_slot1_card("[MemoryCards]\nSlot2_Enable = true\nSlot2_Filename = x.ps2\n") is None


class TestBundleLayoutLookup:
    def test_from_save_set(self):
        save_set = disc_save_set(PPSSPP, DiscCode(PSP, "ULUS10234"))
        assert save_set is not None
        assert bundle_layout("ULUS10234.ppsspp.zip", save_set) == save_set.entries[0].layout

    def test_vita_name_alone(self):
        layout = bundle_layout("PCSE01274.vita3k.zip", None)
        assert layout is not None
        assert (layout.label, layout.folder) == ("PCSE01274", "PCSE01274")

    def test_plain_file(self):
        assert bundle_layout("Game.srm", None) is None

    @pytest.mark.parametrize("name", ["ULUS10234.ppsspp.zip", "GALE01.dolphin-gc.zip", "SLUS-20062.pcsx2.zip"])
    def test_bundle_without_its_set_raises(self, name):
        with pytest.raises(ValueError, match="no save set"):
            bundle_layout(name, None)

    def test_is_bundle_filename(self):
        assert is_bundle_filename("SMOX.dolphin-wii.zip")
        assert is_bundle_filename("PCSE01274.vita3k.zip")
        assert not is_bundle_filename("Game_1.mcd")

    def test_emulator_executable(self):
        assert emulator_executable('"C:\\PCSX2\\pcsx2-qt.exe" -batch') == "C:\\PCSX2\\pcsx2-qt.exe"
        assert emulator_executable("%EMULATOR% %ROM%") is None
        assert emulator_executable(None) is None
