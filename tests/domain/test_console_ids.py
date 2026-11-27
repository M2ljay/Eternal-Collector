"""Tests for domain.console_ids — PARAM.SFO, XDVDFS + XEX title IDs and Wii U meta.xml."""

from __future__ import annotations

import struct

import pytest
from fakes.disc_images import build_xiso, param_sfo, xex_header

from domain.console_ids import (
    SfoGame,
    find_xdvdfs_entry,
    parse_param_sfo,
    parse_xdvdfs_descriptor,
    ps3_game,
    ps4_game,
    wiiu_title_id,
    xex_title_id,
)


class TestParamSfo:
    def test_strings_and_integers(self):
        data = bytearray(param_sfo({"TITLE_ID": "BLUS30443", "APP_VER": "01.04"}))
        sfo = parse_param_sfo(bytes(data))
        assert sfo == {"TITLE_ID": "BLUS30443", "APP_VER": "01.04"}

    @pytest.mark.parametrize("data", [b"", b"NOPE" + bytes(30), b"\x00PSF" + bytes(4)])
    def test_not_an_sfo(self, data):
        assert parse_param_sfo(data) is None

    def test_ps3_and_ps4_games(self):
        assert ps3_game({"TITLE_ID": "BLUS30443", "APP_VER": "01.04"}) == SfoGame("BLUS30443", "01.04")
        assert ps4_game({"TITLE_ID": "CUSA00001", "APP_VER": "bad"}) == SfoGame("CUSA00001", None)
        assert ps3_game({"TITLE_ID": "not a serial"}) is None
        assert ps3_game(None) is None


class TestXdvdfs:
    def test_finds_default_xex_among_siblings(self):
        image = build_xiso({"media": b"x", "default.xex": xex_header(0x4D5307E6), "zzz.bin": b"y"})
        root = parse_xdvdfs_descriptor(image[32 * 2048 : 33 * 2048])
        assert root is not None
        table = image[root.sector * 2048 : root.sector * 2048 + root.size]
        entry = find_xdvdfs_entry(table, "DEFAULT.XEX")
        assert entry is not None and not entry.is_dir
        data = image[entry.sector * 2048 : entry.sector * 2048 + entry.size]
        assert xex_title_id(data) == "4D5307E6"
        assert find_xdvdfs_entry(table, "missing.xex") is None

    def test_descriptor_needs_both_magics(self):
        sector = bytearray(2048)
        sector[:20] = b"MICROSOFT*XBOX*MEDIA"
        struct.pack_into("<II", sector, 0x14, 34, 100)
        assert parse_xdvdfs_descriptor(bytes(sector)) is None

    def test_a_looping_table_ends(self):
        table = bytearray(32)
        struct.pack_into("<HHIIBB", table, 0, 0, 4, 1, 1, 0, 1)
        table[14:15] = b"a"
        struct.pack_into("<HHIIBB", table, 16, 4, 4, 2, 1, 0, 1)
        table[30:31] = b"c"
        assert find_xdvdfs_entry(bytes(table), "b") is None
        assert find_xdvdfs_entry(bytes(table), "c") is not None


class TestXex:
    def test_title_id_after_other_headers(self):
        assert xex_title_id(xex_header(0x584111F7, extra_headers=3)) == "584111F7"

    @pytest.mark.parametrize("data", [b"", b"XEX1" + bytes(40), xex_header(0)])
    def test_no_title_id(self, data):
        assert xex_title_id(data) is None


class TestWiiU:
    def test_meta_xml(self):
        xml = '<?xml version="1.0"?><menu><title_id type="hexBinary" length="8">00050000101c9400</title_id></menu>'
        assert wiiu_title_id(xml) == "00050000101C9400"

    def test_missing(self):
        assert wiiu_title_id("<menu/>") is None
        assert wiiu_title_id(None) is None
