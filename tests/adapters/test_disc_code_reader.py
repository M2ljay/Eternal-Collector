"""Tests for adapters.disc_code_reader — identifying real-format disc image files."""

import logging
import os
import struct

import pytest
from fakes.disc_images import (
    build_chd,
    build_cso,
    build_iso,
    build_wia_header,
    build_xiso,
    cd_frames_from_iso,
    cht2,
    gamecube_header,
    param_sfo,
    xex_header,
)

from adapters.disc_code_reader import DiscCodeReaderAdapter
from domain.disc_ids import GAMECUBE, N3DS, NINTENDO_OPTICAL, PS2, PSP, WII, DiscCode

_PS2_ISO = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_200.62;1\r\nVER = 1.00\r\n"}, pad_sectors=8)
_PSP_ISO = build_iso(
    {"UMD_DATA.BIN": b"ULUS-10234|0001|G|", "PSP_GAME/PARAM.SFO": param_sfo({"DISC_ID": "ULUS10234"})},
    pad_sectors=8,
)


@pytest.fixture
def reader():
    return DiscCodeReaderAdapter(logger=logging.getLogger("test"))


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


class TestNintendo:
    @pytest.mark.parametrize("magic", [b"RVZ\x01", b"WIA\x01"])
    def test_rvz_and_wia_header(self, reader, tmp_path, magic):
        path = _write(
            tmp_path, "Soulcalibur II.rvz", build_wia_header(gamecube_header(b"GRSEAF"), magic=magic) + b"\x00" * 64
        )
        assert reader.read_disc_code(path, NINTENDO_OPTICAL) == DiscCode(GAMECUBE, "GRSEAF")

    def test_rvz_wii(self, reader, tmp_path):
        path = _write(tmp_path, "g.rvz", build_wia_header(gamecube_header(b"SMOXE8", wii=True), disc_type=2))
        assert reader.read_disc_code(path, NINTENDO_OPTICAL) == DiscCode(WII, "SMOXE8")

    def test_rvz_disc_type_must_agree_with_magic(self, reader, tmp_path):
        path = _write(tmp_path, "g.rvz", build_wia_header(gamecube_header(b"SMOXE8", wii=True), disc_type=1))
        assert reader.read_disc_code(path, NINTENDO_OPTICAL) is None

    def test_rvz_header_hash_mismatch(self, reader, tmp_path):
        blob = bytearray(build_wia_header(gamecube_header(b"GRSEAF")))
        blob[0x30] ^= 1
        assert reader.read_disc_code(_write(tmp_path, "g.rvz", bytes(blob)), NINTENDO_OPTICAL) is None

    def test_rvz_disc_struct_hash_mismatch(self, reader, tmp_path):
        blob = bytearray(build_wia_header(gamecube_header(b"GRSEAF")))
        blob[0x48 + 0x10] = ord("X")
        assert reader.read_disc_code(_write(tmp_path, "g.rvz", bytes(blob)), NINTENDO_OPTICAL) is None

    @pytest.mark.parametrize("ext", ["iso", "gcm"])
    def test_plain_gamecube_image(self, reader, tmp_path, ext):
        path = _write(tmp_path, f"g.{ext}", gamecube_header(b"GALE01") + bytes(4096))
        assert reader.read_disc_code(path, NINTENDO_OPTICAL) == DiscCode(GAMECUBE, "GALE01")

    @pytest.mark.parametrize("ext", ["wbfs", "gcz", "ciso", "nkit"])
    def test_unsupported_containers(self, reader, tmp_path, ext):
        path = _write(tmp_path, f"g.{ext}", gamecube_header(b"GALE01"))
        assert reader.read_disc_code(path, NINTENDO_OPTICAL) is None

    def test_rvz_named_file_that_is_not_one(self, reader, tmp_path):
        assert reader.read_disc_code(_write(tmp_path, "g.rvz", b"garbage" * 40), NINTENDO_OPTICAL) is None


class TestPsp:
    def test_iso(self, reader, tmp_path):
        assert reader.read_disc_code(_write(tmp_path, "g.iso", _PSP_ISO), PSP) == DiscCode(PSP, "ULUS10234")

    def test_cso(self, reader, tmp_path):
        path = _write(tmp_path, "g.cso", build_cso(_PSP_ISO, block_size=2048))
        assert reader.read_disc_code(path, PSP) == DiscCode(PSP, "ULUS10234")

    def test_umd_data_when_param_sfo_lacks_disc_id(self, reader, tmp_path):
        iso = build_iso({"UMD_DATA.BIN": b"ULES-01234|0001|G|", "PSP_GAME/PARAM.SFO": param_sfo({"TITLE": "x"})})
        assert reader.read_disc_code(_write(tmp_path, "g.iso", iso), PSP) == DiscCode(PSP, "ULES01234")

    def test_chd(self, reader, tmp_path):
        path = _write(tmp_path, "g.chd", build_chd(_PSP_ISO, hunk_bytes=4096, unit_bytes=2048, codecs=("lzma",)))
        assert reader.read_disc_code(path, PSP) == DiscCode(PSP, "ULUS10234")

    def test_iso_without_ids(self, reader, tmp_path):
        assert reader.read_disc_code(_write(tmp_path, "g.iso", build_iso({"README.TXT": b"x"})), PSP) is None

    @pytest.mark.parametrize("ext", ["pbp", "zso", "dax"])
    def test_unsupported_containers(self, reader, tmp_path, ext):
        assert reader.read_disc_code(_write(tmp_path, f"g.{ext}", _PSP_ISO), PSP) is None


class TestPs2:
    def test_iso(self, reader, tmp_path):
        assert reader.read_disc_code(_write(tmp_path, "g.iso", _PS2_ISO), PS2) == DiscCode(PS2, "SLUS-20062")

    def test_dvd_chd(self, reader, tmp_path):
        path = _write(
            tmp_path, "g.chd", build_chd(_PS2_ISO, hunk_bytes=2048 * 2, unit_bytes=2048, codecs=("lzma", "zlib"))
        )
        assert reader.read_disc_code(path, PS2) == DiscCode(PS2, "SLUS-20062")

    def test_cd_chd(self, reader, tmp_path):
        frames = cd_frames_from_iso(_PS2_ISO, mode=2)
        sectors = len(_PS2_ISO) // 2048
        blob = build_chd(
            frames,
            hunk_bytes=2448 * 8,
            unit_bytes=2448,
            codecs=("cdlz", "cdzl"),
            metadata=[("CHT2", cht2(sectors, "MODE2_RAW"))],
        )
        assert reader.read_disc_code(_write(tmp_path, "g.chd", blob), PS2) == DiscCode(PS2, "SLUS-20062")

    def test_ps1_disc_is_not_a_ps2_game(self, reader, tmp_path):
        iso = build_iso({"SYSTEM.CNF": b"BOOT = cdrom:\\SLUS_001.23;1\n"})
        assert reader.read_disc_code(_write(tmp_path, "g.iso", iso), PS2) is None

    def test_corrupt_chd(self, reader, tmp_path):
        blob = bytearray(build_chd(_PS2_ISO, hunk_bytes=4096, unit_bytes=2048, codecs=("zlib",)))
        (map_offset,) = struct.unpack_from(">Q", blob, 40)
        blob[map_offset + 10] ^= 0xFF  # the map's CRC-16
        assert reader.read_disc_code(_write(tmp_path, "g.chd", bytes(blob)), PS2) is None


class TestCaching:
    def test_reads_once_per_unchanged_file(self, reader, tmp_path, monkeypatch):
        path = _write(tmp_path, "g.iso", _PS2_ISO)
        assert reader.read_disc_code(path, PS2) is not None
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-read")))
        assert reader.read_disc_code(path, PS2) == DiscCode(PS2, "SLUS-20062")

    def test_rereads_a_changed_file(self, reader, tmp_path):
        path = _write(tmp_path, "g.iso", _PS2_ISO)
        assert reader.read_disc_code(path, PS2).code == "SLUS-20062"
        other = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLES_500.01;1\n"}, pad_sectors=9)
        with open(path, "wb") as f:
            f.write(other)
        os.utime(path, ns=(1, 1))
        assert reader.read_disc_code(path, PS2).code == "SLES-50001"

    def test_missing_file(self, reader, tmp_path):
        assert reader.read_disc_code(str(tmp_path / "nope.iso"), PS2) is None

    def test_unknown_family(self, reader, tmp_path):
        assert reader.read_disc_code(_write(tmp_path, "g.iso", _PS2_ISO), "n64") is None


def test_wia_disc_size_bounds(tmp_path):
    blob = bytearray(build_wia_header(gamecube_header(b"GALE01")))
    struct.pack_into(">I", blob, 12, 0x10)
    reader = DiscCodeReaderAdapter(logger=logging.getLogger("test"))
    assert reader.read_disc_code(_write(tmp_path, "g.rvz", bytes(blob)), NINTENDO_OPTICAL) is None


def _ncch(program_id: int) -> bytes:
    header = bytearray(0x200)
    header[0x100:0x104] = b"NCCH"
    struct.pack_into("<Q", header, 0x118, program_id)
    return bytes(header)


class TestNintendo3ds:
    def test_cartridge_image_reads_partition0_program_id(self, reader, tmp_path):
        ncsd = bytearray(0x4000)
        ncsd[0x100:0x104] = b"NCSD"
        struct.pack_into("<II", ncsd, 0x120, 0x20, 0x10)
        path = _write(tmp_path, "Game.3ds", bytes(ncsd) + _ncch(0x0004000000055D00) + bytes(0x200))
        assert reader.read_disc_code(path, N3DS) == DiscCode(N3DS, "0004000000055D00")

    def test_cxi(self, reader, tmp_path):
        path = _write(tmp_path, "Game.cxi", _ncch(0x000400000F700E00))
        assert reader.read_disc_code(path, N3DS) == DiscCode(N3DS, "000400000F700E00")

    def test_cia_reads_tmd_title_id(self, reader, tmp_path):
        header = struct.pack("<IHHIII", 0x2020, 0, 0, 0xA00, 0x350, 0x208) + bytes(0x2020 - 0x14)
        tmd = bytearray(0x300)
        struct.pack_into(">I", tmd, 0, 0x010004)
        struct.pack_into(">Q", tmd, 0x140 + 0x4C, 0x0004000000030800)
        blob = header + bytes(0x2040 - 0x2020) + bytes(0xA00) + bytes(0x380) + bytes(tmd)
        path = _write(tmp_path, "Game.cia", blob)
        assert reader.read_disc_code(path, N3DS) == DiscCode(N3DS, "0004000000030800")

    @pytest.mark.parametrize("name", ["Game.3dsx", "Game.3ds", "Game.cia"])
    def test_unrecognised_answers_none(self, reader, tmp_path, name):
        assert reader.read_disc_code(_write(tmp_path, name, bytes(0x400)), N3DS) is None


class TestDiscCodeProblem:
    """Why a read found no identifier — the save-sync blocker's cause."""

    def test_success_has_no_problem(self, reader, tmp_path):
        path = _write(tmp_path, "g.iso", _PS2_ISO)
        assert reader.read_disc_code(path, PS2) is not None
        assert reader.disc_code_problem(path, PS2) is None

    def test_missing_file_is_unreadable(self, reader, tmp_path):
        path = str(tmp_path / "nope.iso")
        reader.read_disc_code(path, PS2)
        kind, _detail = reader.disc_code_problem(path, PS2)
        assert kind == "unreadable"

    def test_corrupt_chd_is_an_unsupported_image(self, reader, tmp_path):
        blob = bytearray(build_chd(_PS2_ISO, hunk_bytes=4096, unit_bytes=2048, codecs=("zlib",)))
        (map_offset,) = struct.unpack_from(">Q", blob, 40)
        blob[map_offset + 10] ^= 0xFF
        path = _write(tmp_path, "g.chd", bytes(blob))
        reader.read_disc_code(path, PS2)
        kind, detail = reader.disc_code_problem(path, PS2)
        assert kind == "unsupported_image"
        assert detail

    def test_unhandled_extension_is_an_unsupported_format(self, reader, tmp_path):
        path = _write(tmp_path, "g.pbp", b"\0PBP" + b"\0" * 64)
        reader.read_disc_code(path, PSP)
        assert reader.disc_code_problem(path, PSP) == ("unsupported_format", ".pbp")

    def test_decoded_image_without_an_id(self, reader, tmp_path):
        iso = build_iso({"SYSTEM.CNF": b"BOOT = cdrom:\\SLUS_001.23;1\n"})
        path = _write(tmp_path, "g.iso", iso)
        reader.read_disc_code(path, PS2)
        assert reader.disc_code_problem(path, PS2) == ("no_disc_id", "")

    def test_a_later_success_clears_the_problem(self, reader, tmp_path):
        path = str(tmp_path / "g.iso")
        reader.read_disc_code(path, PS2)
        assert reader.disc_code_problem(path, PS2) is not None
        _write(tmp_path, "g.iso", _PS2_ISO)
        assert reader.read_disc_code(path, PS2) is not None
        assert reader.disc_code_problem(path, PS2) is None


def _elf(words: int) -> bytes:
    return b"\x7fELF" + bytes((i * 13 + 5) % 256 for i in range(words * 4 - 4))


class TestPs2ElfCrc:
    _ELF = _elf(3000)
    _ISO = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_209.46;1\r\n", "SLUS_209.46": _ELF}, pad_sectors=4)

    def _expected(self) -> int:
        crc = 0
        for (word,) in struct.iter_unpack("<I", self._ELF):
            crc ^= word
        return crc

    def test_iso(self, reader, tmp_path):
        answer = reader.read_ps2_elf_crc(_write(tmp_path, "g.iso", self._ISO))
        assert answer.crc == self._expected()
        assert answer.reason is None

    def test_cso(self, reader, tmp_path):
        answer = reader.read_ps2_elf_crc(_write(tmp_path, "g.cso", build_cso(self._ISO, block_size=2048)))
        assert answer.crc == self._expected()

    def test_chd(self, reader, tmp_path):
        blob = build_chd(self._ISO, hunk_bytes=4096, unit_bytes=2048, codecs=("zlib",))
        assert reader.read_ps2_elf_crc(_write(tmp_path, "g.chd", blob)).crc == self._expected()

    def test_boot_elf_in_a_folder(self, reader, tmp_path):
        iso = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\DATA\\MAIN.ELF;1\n", "DATA/MAIN.ELF": self._ELF})
        assert reader.read_ps2_elf_crc(_write(tmp_path, "g.iso", iso)).crc == self._expected()

    def test_answer_is_cached_per_file(self, reader, tmp_path, monkeypatch):
        path = _write(tmp_path, "g.iso", self._ISO)
        first = reader.read_ps2_elf_crc(path)
        monkeypatch.setattr(reader, "_read_ps2_elf_crc", lambda _p: pytest.fail("read again"))
        assert reader.read_ps2_elf_crc(path) is first

    @pytest.mark.parametrize(
        ("files", "reason"),
        [
            ({"SYSTEM.CNF": b"BOOT = cdrom:\\SLUS_001.23;1\n"}, "names no PS2 boot executable"),
            ({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_209.46;1\n"}, "missing or not an ELF"),
            ({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_209.46;1\n", "SLUS_209.46": b"not an elf"}, "not an ELF"),
        ],
    )
    def test_reasons(self, reader, tmp_path, files, reason):
        answer = reader.read_ps2_elf_crc(_write(tmp_path, "g.iso", build_iso(files)))
        assert answer.crc is None
        assert reason in (answer.reason or "")

    def test_unsupported_format_and_missing_file(self, reader, tmp_path):
        assert "not read here" in (reader.read_ps2_elf_crc(_write(tmp_path, "g.bin", b"x")).reason or "")
        assert "could not be read" in (reader.read_ps2_elf_crc(str(tmp_path / "gone.iso")).reason or "")


class TestXbox360TitleId:
    @pytest.mark.parametrize("base", [0, 0xFD90000])
    def test_iso_at_each_partition_offset(self, reader, tmp_path, base):
        image = build_xiso({"default.xex": xex_header(0x4D5307E6)}, base=base)
        answer = reader.read_xbox360_title_id(_write(tmp_path, "halo.iso", image))
        assert (answer.title_id, answer.reason) == ("4D5307E6", None)

    def test_xex_file(self, reader, tmp_path):
        assert reader.read_xbox360_title_id(_write(tmp_path, "default.xex", xex_header(0x584111F7))).title_id == (
            "584111F7"
        )

    @pytest.mark.parametrize(
        ("name", "data", "reason"),
        [
            ("g.iso", build_iso({"SYSTEM.CNF": b"x"}), "not an Xbox 360"),
            ("g.iso", build_xiso({"other.bin": b"x"}), "no default.xex"),
            ("g.zar", b"x", "not read here"),
            ("default.xex", b"XEX1", "no readable title ID"),
        ],
    )
    def test_reasons(self, reader, tmp_path, name, data, reason):
        answer = reader.read_xbox360_title_id(_write(tmp_path, name, data))
        assert answer.title_id is None
        assert reason in (answer.reason or "")


class TestIsoMember:
    def test_reads_a_ps3_param_sfo(self, reader, tmp_path):
        sfo = param_sfo({"TITLE_ID": "BLUS30443", "APP_VER": "01.00"})
        path = _write(tmp_path, "ds.iso", build_iso({"PS3_GAME/PARAM.SFO": sfo}))
        assert reader.read_iso_member(path, ("PS3_GAME", "PARAM.SFO"), 65536) == sfo
        assert reader.read_iso_member(path, ("MISSING",), 65536) is None
        assert reader.read_iso_member(str(tmp_path / "gone.iso"), ("X",), 10) is None
