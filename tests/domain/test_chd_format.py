"""Tests for domain.chd_format — CHD v5 header, hunk maps, Huffman, CD frames.

The synthetic CHDs come from ``fakes.disc_images.build_chd``, whose output was
cross-checked hunk-for-hunk against libchdr when the writer was written.
"""

import itertools
import random
import struct

import pytest
from fakes.disc_images import HunkSpec, _BitWriter, build_chd, cd_frames_from_iso, cht2, huff_encode

from domain import chd_format as chd


def _map_of(blob: bytes) -> tuple[chd.ChdHeader, list[chd.MapEntry]]:
    header = chd.parse_v5_header(blob[: chd.V5_HEADER_SIZE])
    if not header.is_compressed:
        return header, chd.decode_raw_map(blob[header.map_offset :], header)
    map_header = blob[header.map_offset : header.map_offset + 16]
    size = chd.compressed_map_size(map_header)
    coded = blob[header.map_offset + 16 : header.map_offset + 16 + size]
    return header, chd.decode_compressed_map(map_header, coded, header)


_DATA = bytes(random.Random(7).randrange(4) for _ in range(4096 * 48))


class TestHeader:
    def test_parses_v5(self):
        blob = build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048, codecs=("zlib", "lzma"))
        header = chd.parse_v5_header(blob)
        assert header.compressors[:2] == (chd.CODEC_ZLIB, chd.CODEC_LZMA)
        assert header.hunk_bytes == 4096 and header.unit_bytes == 2048
        assert header.hunk_count == 48 and header.is_compressed

    def test_rejects_non_chd(self):
        with pytest.raises(chd.ChdFormatError):
            chd.parse_v5_header(b"NotAChd!" + bytes(116))

    def test_rejects_v4(self):
        head = bytearray(build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048)[:124])
        struct.pack_into(">I", head, 12, 4)
        with pytest.raises(chd.ChdFormatError):
            chd.parse_v5_header(bytes(head))

    def test_rejects_zero_hunk_size(self):
        head = bytearray(build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048)[:124])
        struct.pack_into(">I", head, 56, 0)
        with pytest.raises(chd.ChdFormatError):
            chd.parse_v5_header(bytes(head))


class TestRawMap:
    def test_uncompressed_chd(self):
        header, entries = _map_of(build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048, codecs=()))
        assert not header.is_compressed
        assert all(e.kind == chd.COMPRESSION_NONE and e.offset % 4096 == 0 for e in entries)

    def test_zero_entry_is_an_unwritten_hunk(self):
        header = chd.ChdHeader((0, 0, 0, 0), 8192, 0, 0, 4096, 2048)
        entries = chd.decode_raw_map(struct.pack(">II", 0, 3), header)
        assert entries[0].kind == chd.COMPRESSION_ZERO
        assert entries[1] == chd.MapEntry(chd.COMPRESSION_NONE, 4096, 3 * 4096, None)

    def test_truncated(self):
        header = chd.ChdHeader((0, 0, 0, 0), 8192, 0, 0, 4096, 2048)
        with pytest.raises(chd.ChdFormatError):
            chd.decode_raw_map(b"\x00\x00\x00\x01", header)


class TestCompressedMap:
    @pytest.mark.parametrize("uniform", [True, False])
    def test_every_entry_type(self, uniform):
        specs = (
            [HunkSpec(codec=i % 3) for i in range(6)]
            + [HunkSpec(mode="none")] * 2
            + [HunkSpec(mode="self", target=t) for t in (1, 1, 2, 5)]  # SELF, SELF_0, SELF_1, SELF
            + [HunkSpec(codec=1)] * 6  # small RLE run
            + [HunkSpec(codec=0)] * 24  # large RLE run
        )
        blob = build_chd(
            _DATA[: 4096 * len(specs)],
            hunk_bytes=4096,
            unit_bytes=2048,
            codecs=("zlib", "lzma", "huff"),
            hunks=specs,
            uniform_tree=uniform,
        )
        _header, entries = _map_of(blob)
        kinds = [e.kind for e in entries]
        assert kinds[:6] == [0, 1, 2, 0, 1, 2]
        assert kinds[6:8] == [chd.COMPRESSION_NONE] * 2
        assert [(e.kind, e.offset) for e in entries[8:12]] == [(chd.COMPRESSION_SELF, t) for t in (1, 1, 2, 5)]
        assert kinds[12:18] == [1] * 6 and kinds[18:] == [0] * 24
        assert all(e.crc is not None for e in entries if e.kind <= chd.COMPRESSION_NONE)
        assert all(e.crc is None for e in entries if e.kind == chd.COMPRESSION_SELF)
        stored = [e for e in entries if e.kind <= chd.COMPRESSION_NONE]
        assert all(b.offset == a.offset + a.length for a, b in itertools.pairwise(stored))

    def test_crc_mismatch_is_rejected(self):
        blob = bytearray(build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048))
        header = chd.parse_v5_header(bytes(blob))
        blob[header.map_offset + 10] ^= 0xFF
        with pytest.raises(chd.ChdFormatError, match="CRC"):
            _map_of(bytes(blob))

    def test_oversized_field_width_is_rejected(self):
        blob = bytearray(build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048))
        header = chd.parse_v5_header(bytes(blob))
        blob[header.map_offset + 12] = 33
        with pytest.raises(chd.ChdFormatError):
            _map_of(bytes(blob))

    def test_truncated_map_is_rejected(self):
        blob = build_chd(_DATA, hunk_bytes=4096, unit_bytes=2048)
        header = chd.parse_v5_header(blob)
        map_header = blob[header.map_offset : header.map_offset + 16]
        with pytest.raises(chd.ChdFormatError):
            chd.decode_compressed_map(map_header, b"", header)


class TestHuffman:
    def test_canonical_codes_match_libchdr_assignment(self):
        # Longest codes take the smallest values (libchdr huffman_assign_canonical_codes).
        assert chd._assign_canonical_codes([1, 2, 3, 3], 8) == [1, 1, 0, 1]

    def test_inconsistent_lengths_are_rejected(self):
        with pytest.raises(chd.ChdFormatError):
            chd._assign_canonical_codes([2, 2, 2], 8)

    def test_length_over_maximum_is_rejected(self):
        with pytest.raises(chd.ChdFormatError):
            chd._assign_canonical_codes([9, 1], 8)

    def test_rle_tree_run_overflow_is_rejected(self):
        w = _BitWriter()
        w.write(1, 4)
        w.write(4, 4)
        w.write(15, 4)  # 18 repeats of length 4 into a 16-symbol alphabet
        with pytest.raises(chd.ChdFormatError):
            chd.import_tree_rle(chd.BitReader(w.getvalue()), 16, 8)

    def test_huff_codec_round_trip(self):
        data = bytes(random.Random(1).randrange(4) for _ in range(4096))
        assert chd.decode_huff_codec(huff_encode(data), 4096) == data

    def test_huff_codec_truncated(self):
        data = bytes(4096)
        with pytest.raises(chd.ChdFormatError):
            chd.decode_huff_codec(huff_encode(data)[:100], 4096)

    def test_bit_reader_reads_msb_first_and_pads_with_zeros(self):
        bits = chd.BitReader(b"\xa5")
        assert [bits.read(1) for _ in range(8)] == [1, 0, 1, 0, 0, 1, 0, 1]
        assert bits.read(4) == 0 and bits.overflowed


class TestCdFrames:
    def _hunk(self, mode=1):
        iso = bytes(random.Random(mode).randrange(256) for _ in range(2048 * 8))
        return cd_frames_from_iso(iso, mode=mode), iso

    @pytest.mark.parametrize("mode", [1, 2])
    def test_stripped_ecc_is_regenerated(self, mode):
        frames, _iso = self._hunk(mode)
        sectors = bytearray()
        subcode = bytearray()
        for f in range(8):
            sector = bytearray(frames[f * 2448 : f * 2448 + 2352])
            if f in (0, 5):
                sector[0:12] = bytes(12)
                sector[0x81C:0x930] = bytes(0x930 - 0x81C)
            sectors += sector
            subcode += frames[f * 2448 + 2352 : (f + 1) * 2448]
        payload = chd.CdCodecPayload(frames=8, ecc_bitmap=bytes([0b00100001]), base=b"", subcode=b"")
        assert chd.assemble_cd_frames(payload, bytes(sectors), bytes(subcode)) == frames

    def test_wrong_sizes_are_rejected(self):
        payload = chd.CdCodecPayload(frames=8, ecc_bitmap=b"\x00", base=b"", subcode=b"")
        with pytest.raises(chd.ChdFormatError):
            chd.assemble_cd_frames(payload, bytes(10), bytes(8 * 96))

    def test_split_payload(self):
        src = b"\x01" + (3).to_bytes(2, "big") + b"abc" + b"subcode"
        payload = chd.split_cd_codec_payload(src, 8 * 2448)
        assert (payload.ecc_bitmap, payload.base, payload.subcode) == (b"\x01", b"abc", b"subcode")

    def test_split_truncated(self):
        with pytest.raises(chd.ChdFormatError):
            chd.split_cd_codec_payload(b"\x00" + (50).to_bytes(2, "big") + b"abc", 8 * 2448)

    @pytest.mark.parametrize(("mode", "track_type"), [(1, "MODE1_RAW"), (2, "MODE2_RAW")])
    def test_user_data(self, mode, track_type):
        frames, iso = self._hunk(mode)
        assert chd.cd_user_data(frames[2448:4896], track_type) == iso[2048:4096]

    def test_cooked_tracks(self):
        frame = b"D" * 2048 + bytes(400)
        assert chd.cd_user_data(frame, "MODE1") == b"D" * 2048
        assert chd.cd_user_data(b"subh0008" + b"E" * 2048 + bytes(392), "MODE2") == b"E" * 2048

    def test_raw_sector_without_sync_is_rejected(self):
        with pytest.raises(chd.ChdFormatError):
            chd.cd_user_data(bytes(2448), "MODE1_RAW")

    def test_mode_mismatch_is_rejected(self):
        frames, _iso = self._hunk(1)
        with pytest.raises(chd.ChdFormatError):
            chd.cd_user_data(frames[:2448], "MODE2_RAW")

    def test_audio_is_unsupported(self):
        with pytest.raises(chd.ChdFormatError):
            chd.cd_user_data(bytes(2448), "AUDIO")


class TestTrackMetadata:
    def test_cht2(self):
        track = chd.parse_cd_track(cht2(1000, "MODE2_RAW", pregap=150, pgtype="VMODE2_RAW"))
        assert track == chd.CdTrack(1, "MODE2_RAW", 1000, 150, "VMODE2_RAW")
        assert chd.first_data_frame(track) == 150

    def test_pregap_not_in_data(self):
        assert chd.first_data_frame(chd.parse_cd_track(cht2(10, pregap=150, pgtype="MODE1"))) == 0

    def test_chtr_without_pregap_fields(self):
        track = chd.parse_cd_track(b"TRACK:1 TYPE:MODE1 SUBTYPE:NONE FRAMES:500\x00")
        assert (track.track_type, track.frames, track.pregap) == ("MODE1", 500, 0)

    def test_unreadable(self):
        with pytest.raises(chd.ChdFormatError):
            chd.parse_cd_track(b"TRACK:x TYPE:MODE1")

    def test_metadata_header(self):
        assert chd.parse_metadata_header(b"CHT2" + b"\x01\x00\x00\x2a" + struct.pack(">Q", 999)) == (
            chd.CDROM_TRACK_METADATA2_TAG,
            42,
            999,
        )


class TestCrc16:
    def test_known_value(self):
        # CRC-16/CCITT-FALSE check value.
        assert chd.crc16(b"123456789") == 0x29B1


class TestRoundTripWithCdHunks:
    def test_cd_chd_map_decodes(self):
        frames, _ = TestCdFrames()._hunk(1)
        blob = build_chd(frames, hunk_bytes=2448 * 8, unit_bytes=2448, codecs=("cdlz",), metadata=[("CHT2", cht2(8))])
        header, entries = _map_of(blob)
        assert header.unit_bytes == 2448 and entries[0].kind == 0
