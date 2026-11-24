"""Tests for adapters.disc_images — plain ISO, CSO v1 and CHD v5 sector sources."""

import io
import random
import struct
import zlib

import pytest
from fakes.disc_images import HunkSpec, build_chd, build_cso, build_iso, cd_frames_from_iso, cht2

from adapters.disc_images import (
    ChdReader,
    ChdSource,
    CsoSource,
    DiscImageError,
    PlainIsoSource,
    _unlzma,
    lzma_dictionary_size,
)
from domain import chd_format as chd

_ISO = build_iso({"SYSTEM.CNF": b"BOOT2 = cdrom0:\\SLUS_200.62;1\n"}, pad_sectors=40)
_RANDOM = bytes(random.Random(5).randrange(4) for _ in range(4096 * 20))

# A 4096-byte hunk LZMA-coded by the LZMA SDK's own encoder with the settings
# MAME's chdman uses (lc 3, lp 0, pb 2, no end marker); its input is
# ``_NO_END_MARKER_INPUT``. Python's encoder always writes an end marker, so
# this fixture is the only coverage of the marker-less streams real CHDs hold.
_NO_END_MARKER_LZMA = bytes.fromhex(
    "002996468d1c412f15fa5fa99b9a6e1e4004ed0c12a324092f11e308c77ca0bb704dc1672a355f27658bdc7009359960b10c4b2a"
    "4581cbdfd7cded2589d1f809abe0f9b62a34025f7460e24e3d0ad10b4ad924fa6cc5e7f81265249b560e8d24ae278b3b49ada7eb"
    "903a919b84463433264cd23fd3e00ae1d202b5f1b4b282980181aa4580ebee784f23910e5012340182c7041d847721ab4f028b3a"
    "79e71ee0e309586672e137a5f08713797cdf75a576793b0ce6c2c1a8f3388b074e9127f05c1a7581d1025b9c9704e85e16701"
    "41e0201b45b565d981103e2d3439883f5334a882059b58cf1219d4c355094ef05399a1d479d1d3154ff656e02"
)
_PATTERN = "SYSTEM.CNF BOOT2 = cdrom0:\\SLUS_200.62;1 VER = 1.00 VMODE = NTSC "
_NO_END_MARKER_INPUT = bytes(ord(_PATTERN[i % 62]) ^ ((i // 512) & 3) for i in range(4096))


def _sector(lba: int) -> bytes:
    return _ISO[lba * 2048 : (lba + 1) * 2048]


class TestPlainIso:
    def test_reads_sector(self):
        assert PlainIsoSource(io.BytesIO(_ISO)).read_sector(16) == _sector(16)

    def test_past_end(self):
        with pytest.raises(DiscImageError):
            PlainIsoSource(io.BytesIO(_ISO)).read_sector(10_000)


class TestCso:
    @pytest.mark.parametrize(
        ("block_size", "align", "plain"),
        [(2048, 0, frozenset()), (8192, 2, frozenset()), (2048, 0, frozenset({16, 17})), (4096, 4, frozenset({1}))],
    )
    def test_reads_sectors(self, block_size, align, plain):
        source = CsoSource(io.BytesIO(build_cso(_ISO, block_size=block_size, align=align, plain_blocks=plain)))
        for lba in (0, 16, 17, 18, 19):
            assert source.read_sector(lba) == _sector(lba)

    def test_version_2_is_unsupported(self):
        blob = bytearray(build_cso(_ISO))
        blob[20] = 2
        with pytest.raises(DiscImageError):
            CsoSource(io.BytesIO(bytes(blob)))

    def test_bad_magic(self):
        with pytest.raises(DiscImageError):
            CsoSource(io.BytesIO(b"ZISO" + bytes(40)))

    def test_non_power_of_two_block(self):
        blob = bytearray(build_cso(_ISO))
        struct.pack_into("<I", blob, 16, 3000)
        with pytest.raises(DiscImageError):
            CsoSource(io.BytesIO(bytes(blob)))

    def test_corrupt_block(self):
        blob = bytearray(build_cso(_ISO))
        (first,) = struct.unpack_from("<I", blob, 24 + 16 * 4)
        blob[first : first + 8] = b"\xff" * 8
        with pytest.raises(DiscImageError):
            CsoSource(io.BytesIO(bytes(blob))).read_sector(16)

    def test_past_end(self):
        with pytest.raises(DiscImageError):
            CsoSource(io.BytesIO(build_cso(_ISO))).read_sector(10_000)


class TestLzma:
    def test_dictionary_size_follows_libchdr(self):
        assert lzma_dictionary_size(4096) == 4096
        assert lzma_dictionary_size(19584) == 3 << 13  # rounded up to 2^n or 3*2^n
        assert lzma_dictionary_size(18816) == 3 << 13
        assert lzma_dictionary_size(100) == 4096

    def test_stream_without_end_marker(self):
        assert _unlzma(_NO_END_MARKER_LZMA, 4096, 4096) == _NO_END_MARKER_INPUT

    def test_short_output_is_rejected(self):
        with pytest.raises(DiscImageError):
            _unlzma(_NO_END_MARKER_LZMA[:100], 4096, 4096)


class TestChdReader:
    @pytest.mark.parametrize("codecs", [(), ("zlib",), ("lzma",), ("huff",), ("zlib", "lzma", "huff")])
    def test_hunks_decode(self, codecs):
        specs = [HunkSpec(codec=i % max(len(codecs), 1)) for i in range(20)] if codecs else None
        blob = build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048, codecs=codecs, hunks=specs)
        reader = ChdReader(io.BytesIO(blob))
        assert reader.read_bytes(0, len(_RANDOM)) == _RANDOM

    def test_self_and_uncompressed_hunks(self):
        specs = [HunkSpec(), HunkSpec(mode="none"), HunkSpec(mode="self", target=0)] + [HunkSpec()] * 17
        data = bytearray(_RANDOM)
        data[8192:12288] = data[0:4096]
        reader = ChdReader(io.BytesIO(build_chd(bytes(data), hunk_bytes=4096, unit_bytes=2048, hunks=specs)))
        assert reader.read_bytes(0, len(data)) == bytes(data)

    def test_crc_failure_is_rejected(self):
        blob = bytearray(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048, hunks=[HunkSpec(mode="none")] * 20))
        blob[chd.V5_HEADER_SIZE + 10] ^= 0xFF
        with pytest.raises(DiscImageError, match="CRC"):
            ChdReader(io.BytesIO(bytes(blob))).read_hunk(0)

    def test_parent_reference_is_unsupported(self):
        reader = ChdReader(io.BytesIO(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048)))
        reader._map[0] = chd.MapEntry(chd.COMPRESSION_PARENT, 0, 0, None)
        with pytest.raises(DiscImageError, match="parent"):
            reader.read_hunk(0)

    def test_forward_self_reference_is_rejected(self):
        reader = ChdReader(io.BytesIO(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048)))
        reader._map[0] = chd.MapEntry(chd.COMPRESSION_SELF, 0, 3, None)
        with pytest.raises(DiscImageError):
            reader.read_hunk(0)

    def test_flac_is_unsupported(self):
        blob = bytearray(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048))
        struct.pack_into(">I", blob, 16, int.from_bytes(b"flac", "big"))
        with pytest.raises(DiscImageError, match="unsupported"):
            ChdReader(io.BytesIO(bytes(blob))).read_hunk(0)

    def test_truncated_file(self):
        blob = build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048)
        with pytest.raises(DiscImageError):
            ChdReader(io.BytesIO(blob[:200]))

    def test_not_a_chd(self):
        with pytest.raises(DiscImageError):
            ChdReader(io.BytesIO(b"x" * 200))

    def test_hunk_past_end(self):
        with pytest.raises(DiscImageError):
            ChdReader(io.BytesIO(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048))).read_hunk(99)


class TestZstd:
    def _zstd_chd(self, codec):
        blob = bytearray(build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=2048))
        struct.pack_into(">I", blob, 16, int.from_bytes(codec, "big"))
        return bytes(blob)

    def test_unavailable_zstd_is_unreadable(self):
        def unavailable(_data):
            raise DiscImageError("zstd is not available on this runtime")

        reader = ChdReader(io.BytesIO(self._zstd_chd(b"zstd")), zstd_decompress=unavailable)
        with pytest.raises(DiscImageError, match="zstd"):
            reader.read_hunk(0)

    def test_zstd_hunk_goes_through_the_injected_decompressor(self):
        # The hunk bytes are really raw deflate; the stand-in proves only the routing.
        def fake_zstd(data):
            return zlib.decompressobj(-15).decompress(data)

        reader = ChdReader(io.BytesIO(self._zstd_chd(b"zstd")), zstd_decompress=fake_zstd)
        assert reader.read_hunk(0) == _RANDOM[:4096]

    def test_wrong_size_from_zstd_is_rejected(self):
        reader = ChdReader(io.BytesIO(self._zstd_chd(b"zstd")), zstd_decompress=lambda _d: b"short")
        with pytest.raises(DiscImageError):
            reader.read_hunk(0)

    def test_cdzs_routes_both_streams_through_zstd(self):
        frames = cd_frames_from_iso(_ISO[: 2048 * 16])
        blob = bytearray(
            build_chd(frames, hunk_bytes=2448 * 8, unit_bytes=2448, codecs=("cdzl",), metadata=[("CHT2", cht2(16))])
        )
        struct.pack_into(">I", blob, 16, int.from_bytes(b"cdzs", "big"))
        calls = []

        def fake_zstd(data):
            calls.append(len(data))
            return zlib.decompressobj(-15).decompress(data)

        source = ChdSource(ChdReader(io.BytesIO(bytes(blob)), zstd_decompress=fake_zstd))
        assert source.read_sector(1) == _ISO[2048:4096]
        assert len(calls) == 2

    def test_vendored_loader_degrades_cleanly(self):
        from adapters import disc_images

        try:
            out = disc_images._vendored_zstd_decompress(b"\x28\xb5\x2f\xfd\x00\x00\x01\x00\x00")
        except DiscImageError:
            return  # the sandbox / Windows case: no loadable compiled module
        assert out == b""


class TestChdSource:
    def test_dvd(self):
        source = ChdSource(ChdReader(io.BytesIO(build_chd(_ISO, hunk_bytes=4096, unit_bytes=2048, codecs=("lzma",)))))
        assert source.read_sector(16) == _sector(16)
        assert source.read_sector(17) == _sector(17)

    @pytest.mark.parametrize(("mode", "track_type"), [(1, "MODE1_RAW"), (2, "MODE2_RAW")])
    @pytest.mark.parametrize("codecs", [("cdlz", "cdzl"), ("cdzl",)])
    def test_cd(self, mode, track_type, codecs):
        frames = cd_frames_from_iso(_ISO, mode=mode)
        sectors = len(_ISO) // 2048
        hunks = (len(frames) + 2448 * 8 - 1) // (2448 * 8)
        specs = [HunkSpec(codec=i % len(codecs), ecc_frames=frozenset({0, 2, 7})) for i in range(hunks)]
        blob = build_chd(
            frames,
            hunk_bytes=2448 * 8,
            unit_bytes=2448,
            codecs=codecs,
            hunks=specs,
            metadata=[("CHT2", cht2(sectors, track_type))],
        )
        source = ChdSource(ChdReader(io.BytesIO(blob)))
        for lba in (16, 17, 18):
            assert source.read_sector(lba) == _sector(lba)

    def test_cd_pregap_stored_in_data(self):
        pregap = 2
        frames = bytes(2448) * pregap + cd_frames_from_iso(_ISO)
        sectors = len(_ISO) // 2048
        blob = build_chd(
            frames,
            hunk_bytes=2448 * 8,
            unit_bytes=2448,
            codecs=("cdzl",),
            metadata=[("CHT2", cht2(sectors, pregap=pregap, pgtype="VMODE1_RAW"))],
        )
        assert ChdSource(ChdReader(io.BytesIO(blob))).read_sector(16) == _sector(16)

    def test_audio_first_track_is_unreadable(self):
        frames = cd_frames_from_iso(_ISO)
        blob = build_chd(
            frames, hunk_bytes=2448 * 8, unit_bytes=2448, codecs=("cdzl",), metadata=[("CHT2", cht2(10, "AUDIO"))]
        )
        with pytest.raises(DiscImageError):
            ChdSource(ChdReader(io.BytesIO(blob))).read_sector(0)

    def test_neither_dvd_nor_cd(self):
        blob = build_chd(_RANDOM, hunk_bytes=4096, unit_bytes=512)
        with pytest.raises(DiscImageError):
            ChdSource(ChdReader(io.BytesIO(blob)))

    def test_cd_sector_past_first_track(self):
        frames = cd_frames_from_iso(_ISO)
        blob = build_chd(frames, hunk_bytes=2448 * 8, unit_bytes=2448, codecs=("cdzl",), metadata=[("CHT2", cht2(4))])
        with pytest.raises(DiscImageError):
            ChdSource(ChdReader(io.BytesIO(blob))).read_sector(16)
