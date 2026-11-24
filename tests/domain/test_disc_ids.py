"""Tests for domain.disc_ids — game identifiers read from disc bytes, and the folders they name."""

import struct

import pytest
from fakes.disc_images import build_iso, gamecube_header, param_sfo

from domain.disc_ids import (
    GAMECUBE,
    ISO_SECTOR_SIZE,
    PRIMARY_VOLUME_DESCRIPTOR_LBA,
    WII,
    DiscCode,
    find_directory_entry,
    gamecube_region_folder,
    gci_game_code,
    normalize_psp_game_id,
    parse_nintendo_disc_header,
    parse_param_sfo_disc_id,
    parse_primary_volume_descriptor,
    parse_system_cnf_serial,
    parse_umd_data,
    wii_title_folder,
)


class TestNintendoDiscHeader:
    def test_gamecube_by_magic(self):
        assert parse_nintendo_disc_header(gamecube_header(b"GALE01")) == DiscCode(GAMECUBE, "GALE01")

    def test_wii_by_magic(self):
        assert parse_nintendo_disc_header(gamecube_header(b"SMOXE8", wii=True)) == DiscCode(WII, "SMOXE8")

    def test_revision_byte_is_kept(self):
        code = parse_nintendo_disc_header(gamecube_header(b"GALE01", revision=2))
        assert code is not None and code.revision == 2

    def test_console_comes_from_magic_not_the_id_letter(self):
        # A Wii disc whose ID starts with G (GameCube's usual letter) is still Wii.
        code = parse_nintendo_disc_header(gamecube_header(b"GHAE08", wii=True))
        assert code is not None and code.platform == WII

    def test_no_magic_is_none(self):
        header = bytearray(gamecube_header(b"GALE01"))
        header[0x1C:0x20] = b"\x00\x00\x00\x00"
        assert parse_nintendo_disc_header(bytes(header)) is None

    @pytest.mark.parametrize("id6", [b"gale01", b"GAL\x0001", b"GA E01", b"\xff\xff\xff\xff\xff\xff"])
    def test_malformed_id_is_none(self, id6):
        assert parse_nintendo_disc_header(gamecube_header(id6)) is None

    def test_short_header_is_none(self):
        assert parse_nintendo_disc_header(gamecube_header(b"GALE01")[:0x1F]) is None


class TestGamecubeRegionFolder:
    @pytest.mark.parametrize(
        ("id6", "folder"),
        [
            ("GALE01", "USA"),
            ("GALJ01", "JAP"),
            ("GALP01", "EUR"),
            ("GALD01", "EUR"),
            ("GALF01", "EUR"),
            ("GALS01", "EUR"),
            ("GALK01", "JAP"),
            ("GALW01", "JAP"),
            ("GALN01", "USA"),
        ],
    )
    def test_country_byte(self, id6, folder):
        assert gamecube_region_folder(id6) == folder

    def test_korean_english_revision_is_jap(self):
        assert gamecube_region_folder("GALE01", revision=0x30) == "JAP"
        assert gamecube_region_folder("GALE01", revision=0x2F) == "USA"

    @pytest.mark.parametrize("id6", ["GALX01", "GALY01", "GALZ01", "GALA01", "GAL"])
    def test_ambiguous_or_unknown_is_none(self, id6):
        assert gamecube_region_folder(id6) is None


class TestWiiTitleFolder:
    def test_hex_of_id4(self):
        assert wii_title_folder("SMOXE8") == "534d4f58"

    def test_short_is_none(self):
        assert wii_title_folder("SMO") is None


class TestGciGameCode:
    def test_first_four_bytes(self):
        assert gci_game_code(b"GALE01\xff\x00") == "GALE"

    @pytest.mark.parametrize("header", [b"GAL", b"ga le", b"\x00\x00\x00\x00"])
    def test_invalid_is_none(self, header):
        assert gci_game_code(header) is None


class TestIso9660:
    def test_walk_root_and_subdirectory(self):
        iso = build_iso({"SYSTEM.CNF": b"BOOT2 = x", "PSP_GAME/PARAM.SFO": b"sfo"})

        def sector(lba):
            return iso[lba * ISO_SECTOR_SIZE : (lba + 1) * ISO_SECTOR_SIZE]

        root = parse_primary_volume_descriptor(sector(PRIMARY_VOLUME_DESCRIPTOR_LBA))
        assert root is not None and root.is_dir
        directory = sector(root.lba)
        cnf = find_directory_entry(directory, "system.cnf")
        assert cnf is not None and not cnf.is_dir and cnf.size == 9
        game = find_directory_entry(directory, "PSP_GAME")
        assert game is not None and game.is_dir
        sfo = find_directory_entry(sector(game.lba), "PARAM.SFO")
        assert sfo is not None and sfo.size == 3
        assert find_directory_entry(directory, "MISSING") is None

    def test_pvd_rejects_other_descriptors(self):
        sector = bytearray(ISO_SECTOR_SIZE)
        sector[0:6] = b"\x02CD001"
        assert parse_primary_volume_descriptor(bytes(sector)) is None
        assert parse_primary_volume_descriptor(b"\x01CD001") is None

    def test_zero_length_record_pads_to_next_sector(self):
        record = bytearray(34 + 8)
        record[0] = 34 + 8
        struct.pack_into("<I", record, 2, 99)
        struct.pack_into("<I", record, 10, 5)
        record[32] = 8
        record[33:41] = b"LATE.BIN"
        directory = bytes(ISO_SECTOR_SIZE) + bytes(record)
        late = find_directory_entry(directory, "LATE.BIN")
        assert late is not None and late.lba == 99

    def test_truncated_record_is_none(self):
        assert find_directory_entry(bytes([40]) + bytes(10), "X") is None


class TestPsp:
    def test_umd_data(self):
        assert parse_umd_data(b"ULUS-10234|0001|G|") == "ULUS10234"

    def test_param_sfo_disc_id(self):
        sfo = param_sfo({"CATEGORY": "UG", "DISC_ID": "ULUS10234", "TITLE": "Game"})
        assert parse_param_sfo_disc_id(sfo) == "ULUS10234"

    def test_param_sfo_without_disc_id(self):
        assert parse_param_sfo_disc_id(param_sfo({"TITLE": "Game"})) is None

    def test_param_sfo_bad_magic(self):
        assert parse_param_sfo_disc_id(b"\x00XYZ" + bytes(40)) is None

    @pytest.mark.parametrize(("raw", "expected"), [("ULES-01234", "ULES01234"), ("NPUH10001", "NPUH10001")])
    def test_normalize(self, raw, expected):
        assert normalize_psp_game_id(raw) == expected

    @pytest.mark.parametrize("raw", ["", "ULUS-1023", "ulus10234", "ULUS102345", "../../x"])
    def test_normalize_rejects(self, raw):
        assert normalize_psp_game_id(raw) is None


class TestSystemCnf:
    @pytest.mark.parametrize(
        ("text", "serial"),
        [
            (b"BOOT2 = cdrom0:\\SLUS_200.62;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n", "SLUS-20062"),
            (b"BOOT2=cdrom0:\\SLES_123.45;1\n", "SLES-12345"),
            (b"BOOT2 = cdrom0:\\\\SLPM_654.32;1", "SLPM-65432"),
            (b"VER = 1.00\nboot2 = CDROM0:\\scus_971.13;1\n", "SCUS-97113"),
        ],
    )
    def test_boot2_serial(self, text, serial):
        assert parse_system_cnf_serial(text) == serial

    @pytest.mark.parametrize(
        "text",
        [
            b"BOOT = cdrom:\\SLUS_001.23;1\n",  # PS1 disc
            b"BOOT2 = cdrom0:\\GAME.ELF;1\n",
            b"",
            b"\xff\xfe\x00",
        ],
    )
    def test_no_ps2_serial(self, text):
        assert parse_system_cnf_serial(text) is None
