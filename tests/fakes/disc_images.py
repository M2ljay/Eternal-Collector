"""Builders for synthetic disc images: ISO 9660, CSO v1, WIA/RVZ headers and CHD v5.

The CHD writer follows MAME's v5 layout as libchdr decodes it — header, CD
track metadata, hunks compressed per hunk with a chosen codec (``zlib``,
``lzma``, ``huff``, ``cdzl``, ``cdlz``), stored uncompressed or as a
self-reference, and either the raw map of an uncompressed CHD or the
Huffman/RLE-coded map ``chdman`` writes by default (with the pseudo types
SELF_0/SELF_1 and both RLE runs exercised). It was cross-checked against
libchdr itself when written; nothing here is used at runtime.
"""

from __future__ import annotations

import hashlib
import lzma
import struct
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from domain import chd_format as chd

if TYPE_CHECKING:
    from collections.abc import Sequence

SECTOR = 2048


# -- ISO 9660 ------------------------------------------------------------------


def _dir_record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    length = 33 + len(name)
    length += length % 2
    rec = bytearray(length)
    rec[0] = length
    struct.pack_into("<I", rec, 2, lba)
    struct.pack_into(">I", rec, 6, lba)
    struct.pack_into("<I", rec, 10, size)
    struct.pack_into(">I", rec, 14, size)
    rec[25] = 0x02 if is_dir else 0
    rec[32] = len(name)
    rec[33 : 33 + len(name)] = name
    return bytes(rec)


def build_iso(files: dict[str, bytes], *, pad_sectors: int = 0) -> bytes:
    """A minimal ISO 9660 image holding *files* (``"DIR/NAME"`` paths, one directory level at most)."""
    dirs: dict[str, dict[str, bytes]] = {"": {}}
    for path, data in files.items():
        parts = path.split("/")
        if len(parts) == 2:
            dirs.setdefault(parts[0], {})[parts[1]] = data
            dirs[""].setdefault(parts[0], b"")
        else:
            dirs[""][parts[0]] = data
    lba = 18
    dir_lba = {}
    for d in dirs:
        dir_lba[d] = lba
        lba += 1
    file_lba: dict[str, int] = {}
    for path, data in files.items():
        file_lba[path] = lba
        lba += max(1, (len(data) + SECTOR - 1) // SECTOR)
    total = lba + pad_sectors
    image = bytearray(total * SECTOR)
    for d, entries in dirs.items():
        rec = _dir_record(b"\x00", dir_lba[d], SECTOR, True) + _dir_record(b"\x01", dir_lba[""], SECTOR, True)
        for name in sorted(entries):
            is_dir = d == "" and name in dirs and name != ""
            if is_dir:
                rec += _dir_record(name.encode(), dir_lba[name], SECTOR, True)
            else:
                path = f"{d}/{name}" if d else name
                rec += _dir_record(f"{name};1".encode(), file_lba[path], len(files[path]), False)
        image[dir_lba[d] * SECTOR : dir_lba[d] * SECTOR + len(rec)] = rec
    for path, data in files.items():
        image[file_lba[path] * SECTOR : file_lba[path] * SECTOR + len(data)] = data
    pvd = bytearray(SECTOR)
    pvd[0], pvd[1:6], pvd[6] = 1, b"CD001", 1
    pvd[156:190] = _dir_record(b"\x00", dir_lba[""], SECTOR, True)
    image[16 * SECTOR : 17 * SECTOR] = pvd
    image[17 * SECTOR] = 255
    image[17 * SECTOR + 1 : 17 * SECTOR + 6] = b"CD001"
    return bytes(image)


def param_sfo(entries: dict[str, str]) -> bytes:
    """A PARAM.SFO with UTF-8 string values."""
    keys = b""
    values = b""
    index = b""
    for key, value in entries.items():
        raw = value.encode() + b"\x00"
        index += struct.pack("<HHIII", len(keys), 0x0204, len(raw), len(raw), len(values))
        keys += key.encode() + b"\x00"
        values += raw
    key_start = 20 + len(index)
    data_start = key_start + len(keys)
    return struct.pack("<4sIIII", b"\x00PSF", 0x101, key_start, data_start, len(entries)) + index + keys + values


def gamecube_header(id6: bytes, *, wii: bool = False, revision: int = 0) -> bytes:
    header = bytearray(0x440)
    header[:6] = id6
    header[7] = revision
    if wii:
        struct.pack_into(">I", header, 0x18, 0x5D1C9EA3)
    else:
        struct.pack_into(">I", header, 0x1C, 0xC2339F3D)
    return bytes(header)


# -- CSO -----------------------------------------------------------------------


def build_cso(
    iso: bytes, *, block_size: int = SECTOR, align: int = 0, plain_blocks: frozenset[int] = frozenset()
) -> bytes:
    blocks = [iso[i : i + block_size].ljust(block_size, b"\x00") for i in range(0, len(iso), block_size)]
    header = struct.pack("<4sIQIBB2x", b"CISO", 0, len(iso), block_size, 1, align)
    index_size = (len(blocks) + 1) * 4
    pos = len(header) + index_size
    pos = (pos + (1 << align) - 1) >> align << align
    body = bytearray()
    entries = []
    start = pos
    for n, block in enumerate(blocks):
        cur = start + len(body)
        if n in plain_blocks:
            entries.append((cur >> align) | 0x80000000)
            body += block
        else:
            entries.append(cur >> align)
            comp = zlib.compressobj(9, zlib.DEFLATED, -15)
            body += comp.compress(block) + comp.flush()
        pad = (-len(body) - start) % (1 << align)
        body += b"\x00" * pad
    entries.append((start + len(body)) >> align)
    index = b"".join(struct.pack("<I", e) for e in entries)
    gap = b"\x00" * (start - len(header) - len(index))
    return header + index + gap + bytes(body)


# -- WIA / RVZ -----------------------------------------------------------------


def build_wia_header(disc_header: bytes, *, magic: bytes = b"RVZ\x01", disc_type: int = 1) -> bytes:
    disc = bytearray(0xDC)
    struct.pack_into(">IIiI", disc, 0, disc_type, 5, 22, 0x20000)
    disc[0x10:0x90] = disc_header[:0x80].ljust(0x80, b"\x00")
    head = bytearray(0x48)
    head[:4] = magic
    struct.pack_into(">III", head, 4, 0x01000000, 0x00030000, len(disc))
    head[16:36] = hashlib.sha1(disc).digest()
    struct.pack_into(">QQ", head, 0x24, 1459978240, 0x48 + len(disc))
    head[0x34:0x48] = hashlib.sha1(bytes(head[:0x34])).digest()
    return bytes(head) + bytes(disc)


# -- CHD -----------------------------------------------------------------------


def _tag(name: str) -> int:
    return int.from_bytes(name.encode(), "big")


def _lzma_raw(data: bytes, dict_basis: int) -> bytes:
    from adapters.disc_images import lzma_dictionary_size

    filters = [{"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2, "dict_size": lzma_dictionary_size(dict_basis)}]
    return lzma.compress(data, format=lzma.FORMAT_RAW, filters=filters)


def _deflate(data: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    return comp.compress(data) + comp.flush()


class _BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def write(self, value: int, count: int) -> None:
        for i in range(count - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def getvalue(self) -> bytes:
        padded = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, padded[i : i + 8])), 2) for i in range(0, len(padded), 8))


def _canonical(lengths: list[int]) -> list[int]:
    return chd._assign_canonical_codes(lengths, 32)


def huff_encode(data: bytes) -> bytes:
    """Encode one hunk with CHD's ``huff`` codec; every byte must be 0-3 (each gets a 2-bit code)."""
    assert max(data, default=0) < 4
    small_lengths = [2, 2, 0, 1] + [0] * 20  # symbol 0: RLE, 1: "length 0", 3: "length 2"
    small_codes = _canonical(small_lengths)
    w = _BitWriter()
    w.write(2, 3)  # small[0] length
    w.write(0, 3)  # start = 1
    for length in (2, 0, 1):
        w.write(length, 3)
    w.write(7, 3)  # every later small symbol: unused

    def small(symbol: int) -> None:
        w.write(small_codes[symbol], small_lengths[symbol])

    small(3)  # symbol 0 has length 2 ...
    small(0)
    w.write(1, 3)  # ... and so do the next 3
    small(1)  # symbol 4 has length 0 ...
    small(0)
    w.write(7, 3)
    w.write(251 - 9, 8)  # ... and so do the other 251
    for byte in data:
        w.write(byte, 2)
    return w.getvalue()


def _cd_payload(hunk: bytes, codec: str, ecc_frames: frozenset[int]) -> bytes:
    frames = len(hunk) // chd.CD_FRAME_SIZE
    sectors = bytearray()
    subcode = bytearray()
    bitmap = bytearray((frames + 7) // 8)
    for f in range(frames):
        frame = hunk[f * chd.CD_FRAME_SIZE : (f + 1) * chd.CD_FRAME_SIZE]
        sector = bytearray(frame[: chd.CD_MAX_SECTOR_DATA])
        if f in ecc_frames:
            bitmap[f // 8] |= 1 << (f % 8)
            sector[0:12] = bytes(12)
            sector[0x81C : 0x81C + 2 * 86 + 2 * 52] = bytes(2 * 86 + 2 * 52)
        sectors += sector
        subcode += frame[chd.CD_MAX_SECTOR_DATA :]
    base = _lzma_raw(bytes(sectors), len(sectors)) if codec == "cdlz" else _deflate(bytes(sectors))
    length_bytes = 2 if len(hunk) < 65536 else 3
    return bytes(bitmap) + len(base).to_bytes(length_bytes, "big") + base + _deflate(bytes(subcode))


@dataclass
class HunkSpec:
    """How the writer stores one hunk: ``codec`` (an index into the codec list), ``none``, or ``self``."""

    mode: str = "codec"
    codec: int = 0
    target: int = 0
    ecc_frames: frozenset[int] = field(default_factory=frozenset)


def build_chd(
    data: bytes,
    *,
    hunk_bytes: int,
    unit_bytes: int,
    codecs: tuple[str, ...] = ("zlib",),
    hunks: list[HunkSpec] | None = None,
    metadata: Sequence[tuple[str, bytes]] = (),
    uniform_tree: bool = False,
) -> bytes:
    """A CHD v5 of *data*. ``codecs == ()`` writes an uncompressed CHD (raw map)."""
    logical = len(data)
    count = (logical + hunk_bytes - 1) // hunk_bytes
    padded = data.ljust(count * hunk_bytes, b"\x00")
    hunk_data = [padded[i * hunk_bytes : (i + 1) * hunk_bytes] for i in range(count)]
    meta = bytearray()
    meta_offset = chd.V5_HEADER_SIZE if metadata else 0
    for n, (tag, payload) in enumerate(metadata):
        nxt = 0 if n == len(metadata) - 1 else meta_offset + len(meta) + 16 + len(payload)
        meta += struct.pack(">II", _tag(tag), 0x01000000 | len(payload)) + struct.pack(">Q", nxt) + payload
    head_len = chd.V5_HEADER_SIZE + len(meta)
    if not codecs:
        map_offset = head_len
        first = (map_offset + count * 4 + hunk_bytes - 1) // hunk_bytes * hunk_bytes
        body = bytearray(first - head_len - count * 4)
        raw_map = b"".join(struct.pack(">I", first // hunk_bytes + i) for i in range(count))
        image = bytes(meta) + raw_map + bytes(body) + b"".join(hunk_data)
        return _header((0, 0, 0, 0), logical, map_offset, meta_offset, hunk_bytes, unit_bytes) + image
    specs = hunks or [HunkSpec() for _ in range(count)]
    first_offset = head_len
    stored = bytearray()
    entries = []  # (pass-1 symbol, kind, length, offset, crc)
    last_self = None
    for i, spec in enumerate(specs):
        crc = chd.crc16(hunk_data[i])
        if spec.mode == "self":
            if last_self is not None and spec.target == last_self:
                symbol = 9  # SELF_0
            elif last_self is not None and spec.target == last_self + 1:
                symbol = 10  # SELF_1
            else:
                symbol = chd.COMPRESSION_SELF
            last_self = spec.target
            entries.append((symbol, chd.COMPRESSION_SELF, 0, spec.target, 0))
            continue
        offset = first_offset + len(stored)
        if spec.mode == "none":
            stored += hunk_data[i]
            entries.append((chd.COMPRESSION_NONE, chd.COMPRESSION_NONE, hunk_bytes, offset, crc))
            continue
        name = codecs[spec.codec]
        if name == "zlib":
            blob = _deflate(hunk_data[i])
        elif name == "lzma":
            blob = _lzma_raw(hunk_data[i], hunk_bytes)
        elif name == "huff":
            blob = huff_encode(hunk_data[i])
        else:
            blob = _cd_payload(hunk_data[i], name, spec.ecc_frames)
        stored += blob
        entries.append((spec.codec, spec.codec, len(blob), offset, crc))
    compressors = tuple(_tag(c) for c in codecs) + (0,) * (4 - len(codecs))
    map_offset = first_offset + len(stored)
    map_blob = _encode_map(entries, first_offset, uniform_tree)
    image = bytes(meta) + bytes(stored) + map_blob + b"\x00" * 16
    return _header(compressors, logical, map_offset, meta_offset, hunk_bytes, unit_bytes) + image


def _header(compressors, logical, map_offset, meta_offset, hunk_bytes, unit_bytes) -> bytes:
    head = bytearray(chd.V5_HEADER_SIZE)
    head[:8] = chd.CHD_MAGIC
    struct.pack_into(">II", head, 8, chd.V5_HEADER_SIZE, 5)
    struct.pack_into(">4I", head, 16, *compressors)
    struct.pack_into(">QQQII", head, 32, logical, map_offset, meta_offset, hunk_bytes, unit_bytes)
    return bytes(head)


def _rle_symbols(symbols: list[int]) -> list[tuple[int, ...]]:
    out: list[tuple[int, ...]] = []
    i = 0
    while i < len(symbols):
        s = symbols[i]
        out.append((s,))
        j = i + 1
        while j < len(symbols) and symbols[j] == s:
            j += 1
        remaining = j - i - 1
        while remaining >= 3:
            if remaining >= 19:
                n = min(remaining, 274)
                hi, lo = divmod(n - 19, 16)
                out.append((8, hi, lo))
            else:
                n = remaining
                out.append((7, n - 3))
            remaining -= n
        out.extend((s,) for _ in range(remaining))
        i = j
    return out


def _encode_map(entries, first_offset: int, uniform_tree: bool) -> bytes:
    stream = _rle_symbols([e[0] for e in entries])
    if uniform_tree:
        lengths = [4] * 16
    else:
        lengths = [3, 2, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 6, 6]
        assert sum(2.0**-n for n in lengths if n) == 1.0
    codes = _canonical(lengths)
    w = _BitWriter()
    i = 0
    while i < 16:
        n = lengths[i]
        j = i
        while j < 16 and lengths[j] == n:
            j += 1
        run = j - i
        if run >= 3 and n != 1:
            w.write(1, 4)
            w.write(n, 4)
            w.write(run - 3, 4)
            i = j
            continue
        if n == 1:
            w.write(1, 4)
            w.write(1, 4)
        else:
            w.write(n, 4)
        i += 1
    for group in stream:
        for sym in group[:1]:
            w.write(codes[sym], lengths[sym])
        for value in group[1:]:
            w.write(codes[value], lengths[value])
    max_len = max((e[2] for e in entries if e[1] <= 3), default=0)
    length_bits = max(max_len.bit_length(), 1)
    self_bits = max(max((e[3] for e in entries if e[1] == chd.COMPRESSION_SELF), default=0).bit_length(), 1)
    raw = bytearray()
    for symbol, kind, length, offset, crc in entries:
        if kind <= 3:
            w.write(length, length_bits)
            w.write(crc, 16)
        elif kind == chd.COMPRESSION_NONE:
            w.write(crc, 16)
        elif symbol == chd.COMPRESSION_SELF:
            w.write(offset, self_bits)
        raw += bytes([kind]) + length.to_bytes(3, "big") + offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
    coded = w.getvalue()
    header = struct.pack(">I", len(coded)) + first_offset.to_bytes(6, "big")
    header += struct.pack(">HBBBB", chd.crc16(bytes(raw)), length_bits, self_bits, 0, 0)
    return header + coded


def cd_frames_from_iso(iso: bytes, *, mode: int = 1) -> bytes:
    """Wrap 2048-byte sectors into raw 2448-byte CD frames (MODE1_RAW or MODE2_RAW form 1) with valid ECC."""
    out = bytearray()
    for lba in range(len(iso) // SECTOR):
        sector = bytearray(chd.CD_MAX_SECTOR_DATA)
        sector[0:12] = b"\x00" + b"\xff" * 10 + b"\x00"
        sector[12:15] = bytes([0, 2, lba % 75])
        sector[15] = mode
        start = 16 if mode == 1 else 24
        sector[start : start + SECTOR] = iso[lba * SECTOR : (lba + 1) * SECTOR]
        chd.ecc_generate(sector)
        out += sector + bytes((lba * 7 + i) % 256 for i in range(chd.CD_MAX_SUBCODE_DATA))
    return bytes(out)


def cht2(frames: int, track_type: str = "MODE1_RAW", pregap: int = 0, pgtype: str = "MODE1") -> bytes:
    return (
        f"TRACK:1 TYPE:{track_type} SUBTYPE:RW FRAMES:{frames} PREGAP:{pregap} PGTYPE:{pgtype} PGSUB:RW POSTGAP:0"
    ).encode() + b"\x00"
