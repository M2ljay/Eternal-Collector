"""The MAME CHD v5 container format, as far as reading a disc's first sectors needs it.

Covers the v5 header, both hunk-map encodings (the raw map of an uncompressed
CHD and the Huffman/RLE-coded map ``chdman`` writes by default), the per-hunk
CRC-16, the ``huff`` codec, the CD codecs' frame layout (sector data and
subcode compressed apart, sync header and ECC stripped and regenerated), and
the CD track metadata. Every rule here follows libchdr
(``src/libchdr_chd.c``, ``libchdr_huffman.c``, ``libchdr_cdrom.c``), the
reference decoder MAME's ``chdman`` output is read with; a structure that does
not decode exactly raises :class:`ChdFormatError`. Inflating zlib/LZMA/zstd
payloads and reading the file are the adapter's job.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import binascii
import re
import struct
from dataclasses import dataclass

CHD_MAGIC = b"MComprHD"
V5_HEADER_SIZE = 124

CODEC_NONE = 0
CODEC_ZLIB = int.from_bytes(b"zlib", "big")
CODEC_LZMA = int.from_bytes(b"lzma", "big")
CODEC_HUFF = int.from_bytes(b"huff", "big")
CODEC_ZSTD = int.from_bytes(b"zstd", "big")
CODEC_CD_ZLIB = int.from_bytes(b"cdzl", "big")
CODEC_CD_LZMA = int.from_bytes(b"cdlz", "big")
CODEC_CD_ZSTD = int.from_bytes(b"cdzs", "big")

# v5 map entry types (libchdr_chd.c, "V5 compression types").
COMPRESSION_TYPE_0, COMPRESSION_TYPE_3 = 0, 3
COMPRESSION_NONE = 4
COMPRESSION_SELF = 5
COMPRESSION_PARENT = 6
_RLE_SMALL, _RLE_LARGE, _SELF_0, _SELF_1, _PARENT_SELF, _PARENT_0, _PARENT_1 = range(7, 14)
COMPRESSION_ZERO = -1
"""A hunk an uncompressed map marks as never written: all zero bytes."""

CD_MAX_SECTOR_DATA = 2352
CD_MAX_SUBCODE_DATA = 96
CD_FRAME_SIZE = CD_MAX_SECTOR_DATA + CD_MAX_SUBCODE_DATA

METADATA_HEADER_SIZE = 16
CDROM_TRACK_METADATA_TAG = int.from_bytes(b"CHTR", "big")
CDROM_TRACK_METADATA2_TAG = int.from_bytes(b"CHT2", "big")

_CD_SYNC_HEADER = b"\x00" + b"\xff" * 10 + b"\x00"


class ChdFormatError(ValueError):
    """A CHD structure that does not decode exactly as libchdr would decode it."""


@dataclass(frozen=True)
class ChdHeader:
    """The fields of a CHD v5 header a reader needs."""

    compressors: tuple[int, int, int, int]
    logical_bytes: int
    map_offset: int
    meta_offset: int
    hunk_bytes: int
    unit_bytes: int

    @property
    def hunk_count(self) -> int:
        return (self.logical_bytes + self.hunk_bytes - 1) // self.hunk_bytes

    @property
    def is_compressed(self) -> bool:
        return self.compressors[0] != CODEC_NONE


@dataclass(frozen=True)
class MapEntry:
    """Where one hunk's bytes are and how they are stored.

    ``kind`` is ``0``-``3`` (the header's compressor of that index),
    :data:`COMPRESSION_NONE`, :data:`COMPRESSION_SELF` (``offset`` is the
    earlier hunk to copy), :data:`COMPRESSION_PARENT` (needs a parent CHD) or
    :data:`COMPRESSION_ZERO`. ``crc`` is the CRC-16 of the decoded hunk, when
    the map records one.
    """

    kind: int
    length: int
    offset: int
    crc: int | None


def parse_v5_header(data: bytes) -> ChdHeader:
    """Parse the 124-byte CHD v5 header; raises :class:`ChdFormatError` for anything else."""
    if len(data) < 16 or data[:8] != CHD_MAGIC:
        raise ChdFormatError("not a CHD file")
    length, version = struct.unpack_from(">II", data, 8)
    if version != 5 or length != V5_HEADER_SIZE or len(data) < V5_HEADER_SIZE:
        raise ChdFormatError(f"unsupported CHD version {version}")
    compressors = struct.unpack_from(">4I", data, 16)
    logical_bytes, map_offset, meta_offset = struct.unpack_from(">QQQ", data, 32)
    hunk_bytes, unit_bytes = struct.unpack_from(">II", data, 56)
    if hunk_bytes == 0 or unit_bytes == 0:
        raise ChdFormatError("zero hunk or unit size")
    return ChdHeader(
        compressors=(compressors[0], compressors[1], compressors[2], compressors[3]),
        logical_bytes=logical_bytes,
        map_offset=map_offset,
        meta_offset=meta_offset,
        hunk_bytes=hunk_bytes,
        unit_bytes=unit_bytes,
    )


def crc16(data: bytes) -> int:
    """libchdr's ``chd_crc16``: CRC-16/CCITT, polynomial 0x1021, initial value 0xFFFF, unreflected."""
    return binascii.crc_hqx(data, 0xFFFF)


# -- bit stream + Huffman (libchdr_bitstream.c, libchdr_huffman.c) --------------


class BitReader:
    """MSB-first bit reader; reads past the end yield zero bits, as libchdr's do."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.pos = 0

    def peek(self, count: int) -> int:
        if count == 0:
            return 0
        start = self.pos >> 3
        window = int.from_bytes(self._data[start : start + 5].ljust(5, b"\x00"), "big")
        return (window >> (40 - (self.pos & 7) - count)) & ((1 << count) - 1)

    def read(self, count: int) -> int:
        value = self.peek(count)
        self.pos += count
        return value

    @property
    def overflowed(self) -> bool:
        return self.pos > len(self._data) * 8


class HuffmanDecoder:
    """A canonical Huffman decoder built from code lengths exactly as libchdr builds one."""

    def __init__(self, lengths: list[int], max_bits: int) -> None:
        self._max_bits = max_bits
        codes = _assign_canonical_codes(lengths, max_bits)
        # An unfilled slot decodes as symbol 0 consuming one bit — libchdr's
        # placeholder for malformed trees (huffman_build_lookup_table).
        table = [(0, 1)] * (1 << max_bits)
        for symbol, (length, code) in enumerate(zip(lengths, codes, strict=True)):
            if length == 0:
                continue
            shift = max_bits - length
            start = code << shift
            end = (code + 1) << shift
            if end > len(table):
                raise ChdFormatError("Huffman code out of range")
            table[start:end] = [(symbol, length)] * (end - start)
        self._table = table

    def decode(self, bits: BitReader) -> int:
        symbol, length = self._table[bits.peek(self._max_bits)]
        bits.pos += length
        return symbol


def _assign_canonical_codes(lengths: list[int], max_bits: int) -> list[int]:
    histogram = [0] * 33
    for length in lengths:
        if length > max_bits:
            raise ChdFormatError("Huffman code length exceeds the maximum")
        histogram[length] += 1
    start = 0
    for length in range(32, 0, -1):
        next_start = (start + histogram[length]) >> 1
        if length != 1 and next_start * 2 != start + histogram[length]:
            raise ChdFormatError("inconsistent Huffman code lengths")
        histogram[length] = start
        start = next_start
    codes = []
    for length in lengths:
        if length > 0:
            codes.append(histogram[length])
            histogram[length] += 1
        else:
            codes.append(0)
    return codes


def import_tree_rle(bits: BitReader, num_codes: int, max_bits: int) -> HuffmanDecoder:
    """libchdr ``huffman_import_tree_rle``: code lengths, RLE-encoded."""
    field = 5 if max_bits >= 16 else 4 if max_bits >= 8 else 3
    lengths: list[int] = []
    while len(lengths) < num_codes:
        value = bits.read(field)
        if value != 1:
            lengths.append(value)
            continue
        value = bits.read(field)
        if value == 1:
            lengths.append(1)
            continue
        repeat = bits.read(field) + 3
        if len(lengths) + repeat > num_codes:
            raise ChdFormatError("Huffman tree run overflows the alphabet")
        lengths.extend([value] * repeat)
    if bits.overflowed:
        raise ChdFormatError("Huffman tree truncated")
    return HuffmanDecoder(lengths, max_bits)


def import_tree_huffman(bits: BitReader, num_codes: int, max_bits: int) -> HuffmanDecoder:
    """libchdr ``huffman_import_tree_huffman``: code lengths, themselves Huffman-coded."""
    small = [bits.read(3)]
    start = bits.read(3) + 1
    count = 0
    for index in range(1, 24):
        if index < start or count == 7:
            small.append(0)
        else:
            count = bits.read(3)
            small.append(0 if count == 7 else count)
    small_decoder = HuffmanDecoder(small, 6)
    rle_full_bits = (num_codes - 9).bit_length()
    lengths: list[int] = []
    last = 0
    while len(lengths) < num_codes:
        value = small_decoder.decode(bits)
        if value != 0:
            last = value - 1
            lengths.append(last)
            continue
        repeat = bits.read(3) + 2
        if repeat == 9:
            repeat += bits.read(rle_full_bits)
        lengths.extend([last] * min(repeat, num_codes - len(lengths)))
    if bits.overflowed:
        raise ChdFormatError("Huffman tree truncated")
    return HuffmanDecoder(lengths, max_bits)


def decode_huff_codec(src: bytes, dest_len: int) -> bytes:
    """Decode one hunk compressed with CHD's ``huff`` codec (256 symbols, codes up to 16 bits)."""
    bits = BitReader(src)
    decoder = import_tree_huffman(bits, 256, 16)
    out = bytes(decoder.decode(bits) for _ in range(dest_len))
    if bits.overflowed:
        raise ChdFormatError("huff hunk truncated")
    return out


# -- hunk map --------------------------------------------------------------------


def decode_raw_map(data: bytes, header: ChdHeader) -> list[MapEntry]:
    """The map of an uncompressed CHD: one big-endian u32 hunk index per hunk (0 = never written)."""
    count = header.hunk_count
    if len(data) < count * 4:
        raise ChdFormatError("truncated map")
    entries = []
    for (index,) in struct.iter_unpack(">I", data[: count * 4]):
        if index == 0:
            entries.append(MapEntry(COMPRESSION_ZERO, header.hunk_bytes, 0, None))
        else:
            entries.append(MapEntry(COMPRESSION_NONE, header.hunk_bytes, index * header.hunk_bytes, None))
    return entries


MAP_HEADER_SIZE = 16


def compressed_map_size(map_header: bytes) -> int:
    """The byte count of the Huffman-coded map that follows the 16-byte map header."""
    if len(map_header) < MAP_HEADER_SIZE:
        raise ChdFormatError("truncated map header")
    (size,) = struct.unpack_from(">I", map_header, 0)
    return size


def decode_compressed_map(map_header: bytes, coded: bytes, header: ChdHeader) -> list[MapEntry]:
    """libchdr ``decompress_v5_map``: decode the whole map and verify its CRC-16.

    *map_header* is the 16 bytes at the header's map offset, *coded* the
    :func:`compressed_map_size` bytes after them.
    """
    first_offset = int.from_bytes(map_header[4:10], "big")
    (map_crc,) = struct.unpack_from(">H", map_header, 10)
    length_bits, self_bits, parent_bits = map_header[12], map_header[13], map_header[14]
    if max(length_bits, self_bits, parent_bits) > 32:
        raise ChdFormatError("map field width over 32 bits")
    bits = BitReader(coded)
    decoder = import_tree_rle(bits, 16, 8)
    count = header.hunk_count
    kinds: list[int] = []
    repeat = 0
    last = 0
    while len(kinds) < count:
        if repeat > 0:
            kinds.append(last)
            repeat -= 1
            continue
        if bits.overflowed:
            raise ChdFormatError("map truncated")
        value = decoder.decode(bits)
        if value == _RLE_SMALL:
            kinds.append(last)
            repeat = 2 + decoder.decode(bits)
        elif value == _RLE_LARGE:
            kinds.append(last)
            repeat = 2 + 16 + (decoder.decode(bits) << 4)
            repeat += decoder.decode(bits)
        else:
            last = value
            kinds.append(value)

    entries: list[MapEntry] = []
    raw = bytearray()
    offset = first_offset
    last_self = 0
    last_parent = 0
    units_per_hunk = header.hunk_bytes // header.unit_bytes
    for hunk, kind in enumerate(kinds):
        entry_offset, length, crc = offset, 0, 0
        if COMPRESSION_TYPE_0 <= kind <= COMPRESSION_TYPE_3:
            length = bits.read(length_bits)
            offset += length
            crc = bits.read(16)
        elif kind == COMPRESSION_NONE:
            length = header.hunk_bytes
            offset += length
            crc = bits.read(16)
        elif kind == COMPRESSION_SELF:
            entry_offset = last_self = bits.read(self_bits)
        elif kind == COMPRESSION_PARENT:
            entry_offset = last_parent = bits.read(parent_bits)
        elif kind in (_SELF_0, _SELF_1):
            if kind == _SELF_1:
                last_self += 1
            kind, entry_offset = COMPRESSION_SELF, last_self
        elif kind == _PARENT_SELF:
            kind = COMPRESSION_PARENT
            entry_offset = last_parent = (hunk * header.hunk_bytes) // header.unit_bytes
        elif kind in (_PARENT_0, _PARENT_1):
            if kind == _PARENT_1:
                last_parent += units_per_hunk
            kind, entry_offset = COMPRESSION_PARENT, last_parent
        else:
            raise ChdFormatError(f"unknown map entry type {kind}")
        raw += bytes([kind]) + length.to_bytes(3, "big") + entry_offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
        has_crc = kind <= COMPRESSION_NONE
        entries.append(MapEntry(kind, length, entry_offset, crc if has_crc else None))
    if crc16(bytes(raw)) != map_crc:
        raise ChdFormatError("map CRC mismatch")
    return entries


# -- CD codecs + sectors (libchdr_cdrom.c) ------------------------------------------


@dataclass(frozen=True)
class CdCodecPayload:
    """One CD-codec hunk split into its parts, before the two streams are inflated."""

    frames: int
    ecc_bitmap: bytes
    base: bytes
    subcode: bytes


def split_cd_codec_payload(src: bytes, hunk_bytes: int) -> CdCodecPayload:
    """libchdr ``cd_codec_decompress``'s header: ECC bitmap, base length, then the two streams."""
    frames = hunk_bytes // CD_FRAME_SIZE
    length_bytes = 2 if hunk_bytes < 65536 else 3
    ecc_bytes = (frames + 7) // 8
    header_bytes = ecc_bytes + length_bytes
    if len(src) < header_bytes:
        raise ChdFormatError("truncated CD hunk")
    base_len = int.from_bytes(src[ecc_bytes:header_bytes], "big")
    if len(src) < header_bytes + base_len:
        raise ChdFormatError("truncated CD hunk")
    return CdCodecPayload(
        frames=frames,
        ecc_bitmap=src[:ecc_bytes],
        base=src[header_bytes : header_bytes + base_len],
        subcode=src[header_bytes + base_len :],
    )


def assemble_cd_frames(payload: CdCodecPayload, sectors: bytes, subcode: bytes) -> bytes:
    """Interleave inflated sector data and subcode into 2448-byte frames, regenerating stripped ECC."""
    frames = payload.frames
    if len(sectors) != frames * CD_MAX_SECTOR_DATA or len(subcode) != frames * CD_MAX_SUBCODE_DATA:
        raise ChdFormatError("CD hunk inflated to the wrong size")
    out = bytearray()
    for frame in range(frames):
        sector = bytearray(sectors[frame * CD_MAX_SECTOR_DATA : (frame + 1) * CD_MAX_SECTOR_DATA])
        if payload.ecc_bitmap[frame // 8] & (1 << (frame % 8)):
            sector[0:12] = _CD_SYNC_HEADER
            ecc_generate(sector)
        out += sector
        out += subcode[frame * CD_MAX_SUBCODE_DATA : (frame + 1) * CD_MAX_SUBCODE_DATA]
    return bytes(out)


def _ecc_tables() -> tuple[list[int], list[int]]:
    low = [((i << 1) ^ (0x11D if i & 0x80 else 0)) & 0xFF for i in range(256)]
    high = [0] * 256
    for i in range(256):
        high[low[i] ^ i] = i
    return low, high


_ECC_LOW, _ECC_HIGH = _ecc_tables()
_ECC_P_OFFSET, _ECC_P_ROWS, _ECC_P_COMPONENTS = 0x81C, 86, 24
_ECC_Q_OFFSET, _ECC_Q_ROWS, _ECC_Q_COMPONENTS = 0x81C + 2 * 86, 52, 43
_P_OFFSETS = [[row + 86 * comp for comp in range(_ECC_P_COMPONENTS)] for row in range(_ECC_P_ROWS)]
_Q_OFFSETS = [
    [(86 * (row >> 1) + (row & 1) + 88 * comp) % 2236 for comp in range(_ECC_Q_COMPONENTS)]
    for row in range(_ECC_Q_ROWS)
]


def ecc_generate(sector: bytearray) -> None:
    """Write a raw sector's ECC P and Q parity in place (libchdr ``ecc_generate``)."""
    mode2 = sector[15] == 2
    for offsets, rows, base in ((_P_OFFSETS, _ECC_P_ROWS, _ECC_P_OFFSET), (_Q_OFFSETS, _ECC_Q_ROWS, _ECC_Q_OFFSET)):
        for row in range(rows):
            v1 = v2 = 0
            for offset in offsets[row]:
                byte = 0 if mode2 and offset < 4 else sector[12 + offset]
                v1 = _ECC_LOW[v1 ^ byte]
                v2 ^= byte
            v1 = _ECC_HIGH[_ECC_LOW[v1] ^ v2]
            sector[base + row] = v1
            sector[base + rows + row] = v2 ^ v1


@dataclass(frozen=True)
class CdTrack:
    """One CD track from CHD metadata."""

    number: int
    track_type: str
    frames: int
    pregap: int
    pregap_type: str


_TRACK_FIELD_RE = re.compile(r"([A-Z]+):(\S*)")

_USER_DATA = {
    "MODE1": (0, None),
    "MODE1_RAW": (16, 1),
    "MODE2": (8, None),
    "MODE2_FORM1": (0, None),
    "MODE2_FORM_MIX": (8, None),
    "MODE2_RAW": (24, 2),
}


def parse_metadata_header(data: bytes) -> tuple[int, int, int]:
    """``(tag, length, next offset)`` of one 16-byte metadata entry header."""
    if len(data) < METADATA_HEADER_SIZE:
        raise ChdFormatError("truncated metadata entry")
    tag, flags_length, next_offset = struct.unpack(">IIQ", data[:16])
    return tag, flags_length & 0x00FFFFFF, next_offset


def parse_cd_track(text: bytes) -> CdTrack:
    """A ``CHT2`` / ``CHTR`` track description (``TRACK:1 TYPE:MODE2_RAW SUBTYPE:NONE FRAMES:...``)."""
    fields = dict(_TRACK_FIELD_RE.findall(text.split(b"\x00", 1)[0].decode("ascii", errors="replace")))
    try:
        return CdTrack(
            number=int(fields["TRACK"]),
            track_type=fields["TYPE"],
            frames=int(fields["FRAMES"]),
            pregap=int(fields.get("PREGAP", "0")),
            pregap_type=fields.get("PGTYPE", ""),
        )
    except (KeyError, ValueError) as exc:
        raise ChdFormatError(f"unreadable CD track metadata: {text[:80]!r}") from exc


def first_data_frame(track: CdTrack) -> int:
    """The CHD frame holding the first track's sector 0: its pregap when stored (``PGTYPE:V...``)."""
    return track.pregap if track.pregap_type.startswith("V") else 0


def cd_user_data(frame: bytes, track_type: str) -> bytes:
    """The 2048 user-data bytes of one frame of a data track; raises for audio or an unknown type.

    For the raw track types the sync header and mode byte are checked, so a
    frame that is not the data sector it claims to be never yields bytes.
    """
    layout = _USER_DATA.get(track_type)
    if layout is None:
        raise ChdFormatError(f"unsupported CD track type {track_type!r}")
    offset, mode = layout
    if mode is not None and (frame[:12] != _CD_SYNC_HEADER or frame[15] != mode):
        raise ChdFormatError("raw sector without a valid sync header")
    return frame[offset : offset + 2048]
