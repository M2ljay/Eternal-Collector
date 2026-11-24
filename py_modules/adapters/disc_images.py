"""Random access to the 2048-byte data sectors of compressed and plain disc images.

Each source reads only the blocks a requested sector lives in — never the
whole image. Container structure is decoded by :mod:`domain.chd_format` (CHD)
or here (CSO v1, a header plus a block index); anything a source cannot read
exactly raises :class:`DiscImageError`, so a caller never acts on bytes that
merely look right.
"""

from __future__ import annotations

import lzma
import struct
import zlib
from typing import TYPE_CHECKING, BinaryIO

from domain import chd_format as chd
from domain.disc_ids import ISO_SECTOR_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable


class DiscImageError(ValueError):
    """An image, or the part of it a read needs, this module cannot decode exactly."""


class PlainIsoSource:
    """An uncompressed ISO: sector *n* is the 2048 bytes at ``n * 2048``."""

    def __init__(self, f: BinaryIO) -> None:
        self._f = f

    def read_sector(self, lba: int) -> bytes:
        self._f.seek(lba * ISO_SECTOR_SIZE)
        data = self._f.read(ISO_SECTOR_SIZE)
        if len(data) != ISO_SECTOR_SIZE:
            raise DiscImageError(f"sector {lba} is past the end of the image")
        return data


# CSO v1 (PPSSPP Core/FileSystems/BlockDevices.cpp ``CISOFileBlockDevice``):
# "CISO", u32 header size (most tools write 0), u64 total bytes, u32 block size,
# u8 version, u8 index alignment, 2 reserved; then one u32 index entry per block
# plus one. Bit 31 marks a block stored plain; the rest, shifted left by the
# alignment, is the block's file offset. Compressed blocks are raw deflate.
_CSO_HEADER = struct.Struct("<4sIQIBB2x")
_CSO_PLAIN_FLAG = 0x80000000


class CsoSource:
    """A CSO v1 image, read one block at a time."""

    def __init__(self, f: BinaryIO) -> None:
        raw = f.read(_CSO_HEADER.size)
        if len(raw) != _CSO_HEADER.size:
            raise DiscImageError("truncated CSO header")
        magic, _header_size, total, block_size, version, align = _CSO_HEADER.unpack(raw)
        if magic != b"CISO" or version > 1:
            raise DiscImageError(f"unsupported CSO (version {version})")
        if block_size < ISO_SECTOR_SIZE or block_size & (block_size - 1) or block_size > 1 << 24 or align > 20:
            raise DiscImageError("unsupported CSO geometry")
        self._f = f
        self._total = total
        self._block_size = block_size
        self._align = align

    def read_sector(self, lba: int) -> bytes:
        offset = lba * ISO_SECTOR_SIZE
        if offset + ISO_SECTOR_SIZE > self._total:
            raise DiscImageError(f"sector {lba} is past the end of the image")
        block, within = divmod(offset, self._block_size)
        self._f.seek(_CSO_HEADER.size + block * 4)
        index = self._f.read(8)
        if len(index) != 8:
            raise DiscImageError("truncated CSO index")
        this, following = struct.unpack("<II", index)
        start = (this & ~_CSO_PLAIN_FLAG) << self._align
        end = (following & ~_CSO_PLAIN_FLAG) << self._align
        if end < start:
            raise DiscImageError("CSO index runs backwards")
        self._f.seek(start)
        stored = self._f.read(end - start)
        if this & _CSO_PLAIN_FLAG:
            data = stored[: self._block_size]
        else:
            try:
                data = zlib.decompressobj(-15).decompress(stored, self._block_size)
            except zlib.error as exc:
                raise DiscImageError(f"CSO block {block} does not inflate") from exc
        if len(data) != self._block_size:
            raise DiscImageError(f"CSO block {block} has the wrong size")
        return data[within : within + ISO_SECTOR_SIZE]


def _vendored_zstd_decompress(data: bytes) -> bytes:
    """One-shot zstd via the vendored ``backports_zstd``; raises :class:`DiscImageError` where it cannot load.

    The vendored package ships a compiled module for one CPython ABI and
    platform only (``py_modules/_vendor/README.md``), so on any other runtime a
    zstd-compressed hunk is simply unreadable.
    """
    try:
        from _vendor import backports_zstd
    except (ImportError, OSError) as exc:
        raise DiscImageError("zstd is not available on this runtime") from exc
    try:
        return backports_zstd.decompress(data)
    except Exception as exc:  # the backport raises its own ZstdError type
        raise DiscImageError("zstd payload does not decompress") from exc


def lzma_dictionary_size(hunk_bytes: int) -> int:
    """The LZMA dictionary size MAME's ``chdman`` encodes a hunk of *hunk_bytes* with.

    libchdr ``lzma_compute_aligned_dictionary_size``: level 6's 64 MiB default
    reduced toward the hunk size (never below 4 KiB), then rounded the way
    ``LzmaEnc_WriteProperties`` rounds it.
    """
    dict_size = 1 << 26
    if dict_size > hunk_bytes:
        dict_size = min(dict_size, max(hunk_bytes, 1 << 12))
    if dict_size >= 1 << 21:
        mask = (1 << 20) - 1
        return max((dict_size + mask) & ~mask, dict_size)
    i = 22
    while True:
        aligned = (2 + (i & 1)) << (i >> 1)
        i += 1
        if aligned >= dict_size:
            return aligned


def _inflate(src: bytes, size: int) -> bytes:
    try:
        out = zlib.decompressobj(-15).decompress(src, size)
    except zlib.error as exc:
        raise DiscImageError("deflate payload does not inflate") from exc
    if len(out) != size:
        raise DiscImageError("deflate payload has the wrong size")
    return out


def _unlzma(src: bytes, size: int, dict_basis: int) -> bytes:
    # Properties byte 93 = lc 3, lp 0, pb 2 (libchdr ``lzma_codec_init``).
    # chdman writes no end marker, so the output size is the only terminator.
    filters = [{"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2, "dict_size": lzma_dictionary_size(dict_basis)}]
    try:
        out = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters).decompress(src, size)
    except lzma.LZMAError as exc:
        raise DiscImageError("LZMA payload does not decompress") from exc
    if len(out) != size:
        raise DiscImageError("LZMA payload has the wrong size")
    return out


class ChdReader:
    """Hunk-level access to a CHD v5 file: map decoding, codecs, CRC checks."""

    def __init__(self, f: BinaryIO, *, zstd_decompress: Callable[[bytes], bytes] = _vendored_zstd_decompress) -> None:
        self._f = f
        self._zstd = zstd_decompress
        try:
            self.header = chd.parse_v5_header(self._read_at(0, chd.V5_HEADER_SIZE))
            self._map = self._read_map()
        except chd.ChdFormatError as exc:
            raise DiscImageError(str(exc)) from exc
        self._cache: dict[int, bytes] = {}

    def _read_at(self, offset: int, size: int) -> bytes:
        self._f.seek(offset)
        data = self._f.read(size)
        if len(data) != size:
            raise DiscImageError("CHD is truncated")
        return data

    def _read_map(self) -> list[chd.MapEntry]:
        header = self.header
        if not header.is_compressed:
            return chd.decode_raw_map(self._read_at(header.map_offset, header.hunk_count * 4), header)
        map_header = self._read_at(header.map_offset, chd.MAP_HEADER_SIZE)
        coded = self._read_at(header.map_offset + chd.MAP_HEADER_SIZE, chd.compressed_map_size(map_header))
        return chd.decode_compressed_map(map_header, coded, header)

    def metadata(self) -> list[tuple[int, bytes]]:
        """Every metadata entry as ``(tag, data)``, in file order."""
        entries: list[tuple[int, bytes]] = []
        offset = self.header.meta_offset
        seen: set[int] = set()
        while offset and offset not in seen and len(entries) < 256:
            seen.add(offset)
            try:
                tag, length, following = chd.parse_metadata_header(self._read_at(offset, chd.METADATA_HEADER_SIZE))
            except chd.ChdFormatError as exc:
                raise DiscImageError(str(exc)) from exc
            entries.append((tag, self._read_at(offset + chd.METADATA_HEADER_SIZE, length)))
            offset = following
        return entries

    def read_hunk(self, hunk: int) -> bytes:
        cached = self._cache.get(hunk)
        if cached is not None:
            return cached
        if not 0 <= hunk < len(self._map):
            raise DiscImageError(f"hunk {hunk} is past the end of the image")
        entry = self._map[hunk]
        size = self.header.hunk_bytes
        if entry.kind == chd.COMPRESSION_ZERO:
            data = bytes(size)
        elif entry.kind == chd.COMPRESSION_NONE:
            data = self._read_at(entry.offset, size)
        elif entry.kind == chd.COMPRESSION_SELF:
            if entry.offset >= hunk:
                raise DiscImageError("self reference to a later hunk")
            data = self.read_hunk(entry.offset)
        elif entry.kind == chd.COMPRESSION_PARENT:
            raise DiscImageError("CHD needs a parent image")
        else:
            data = self._decompress(self.header.compressors[entry.kind], self._read_at(entry.offset, entry.length))
        if entry.crc is not None and chd.crc16(data) != entry.crc:
            raise DiscImageError(f"hunk {hunk} fails its CRC")
        self._cache[hunk] = data
        return data

    def _decompress(self, codec: int, src: bytes) -> bytes:
        size = self.header.hunk_bytes
        try:
            if codec == chd.CODEC_ZLIB:
                return _inflate(src, size)
            if codec == chd.CODEC_LZMA:
                return _unlzma(src, size, size)
            if codec == chd.CODEC_ZSTD:
                return self._sized(self._zstd(src), size)
            if codec == chd.CODEC_HUFF:
                return chd.decode_huff_codec(src, size)
            if codec in (chd.CODEC_CD_ZLIB, chd.CODEC_CD_LZMA, chd.CODEC_CD_ZSTD):
                return self._decompress_cd(codec, src)
        except chd.ChdFormatError as exc:
            raise DiscImageError(str(exc)) from exc
        raise DiscImageError(f"unsupported CHD codec {codec.to_bytes(4, 'big')!r}")

    def _decompress_cd(self, codec: int, src: bytes) -> bytes:
        payload = chd.split_cd_codec_payload(src, self.header.hunk_bytes)
        sector_bytes = payload.frames * chd.CD_MAX_SECTOR_DATA
        subcode_bytes = payload.frames * chd.CD_MAX_SUBCODE_DATA
        if codec == chd.CODEC_CD_ZSTD:
            sectors = self._sized(self._zstd(payload.base), sector_bytes)
            subcode = self._sized(self._zstd(payload.subcode), subcode_bytes)
        else:
            if codec == chd.CODEC_CD_LZMA:
                sectors = _unlzma(payload.base, sector_bytes, sector_bytes)
            else:
                sectors = _inflate(payload.base, sector_bytes)
            subcode = _inflate(payload.subcode, subcode_bytes)
        return chd.assemble_cd_frames(payload, sectors, subcode)

    @staticmethod
    def _sized(data: bytes, size: int) -> bytes:
        if len(data) != size:
            raise DiscImageError("payload has the wrong size")
        return data

    def read_bytes(self, offset: int, size: int) -> bytes:
        """*size* logical bytes starting at *offset*, across hunk boundaries."""
        out = bytearray()
        hunk_bytes = self.header.hunk_bytes
        while size > 0:
            hunk, within = divmod(offset, hunk_bytes)
            piece = self.read_hunk(hunk)[within : within + size]
            out += piece
            offset += len(piece)
            size -= len(piece)
        return bytes(out)


class ChdSource:
    """The data sectors of a CHD: a DVD's 2048-byte units, or a CD's first data track."""

    def __init__(self, reader: ChdReader) -> None:
        self._reader = reader
        self._track: chd.CdTrack | None = None
        tracks = []
        for tag, data in reader.metadata():
            if tag in (chd.CDROM_TRACK_METADATA_TAG, chd.CDROM_TRACK_METADATA2_TAG):
                try:
                    tracks.append(chd.parse_cd_track(data))
                except chd.ChdFormatError as exc:
                    raise DiscImageError(str(exc)) from exc
        header = reader.header
        if tracks:
            first = min(tracks, key=lambda t: t.number)
            if first.number != 1 or header.unit_bytes != chd.CD_FRAME_SIZE or header.hunk_bytes % chd.CD_FRAME_SIZE:
                raise DiscImageError("unsupported CD layout")
            self._track = first
        elif header.unit_bytes != ISO_SECTOR_SIZE or header.hunk_bytes % ISO_SECTOR_SIZE:
            raise DiscImageError("CHD is neither a DVD nor a CD image")

    def read_sector(self, lba: int) -> bytes:
        if self._track is None:
            return self._reader.read_bytes(lba * ISO_SECTOR_SIZE, ISO_SECTOR_SIZE)
        if lba >= self._track.frames:
            raise DiscImageError(f"sector {lba} is past the first track")
        frame_index = chd.first_data_frame(self._track) + lba
        frame = self._reader.read_bytes(frame_index * chd.CD_FRAME_SIZE, chd.CD_FRAME_SIZE)
        try:
            return chd.cd_user_data(frame, self._track.track_type)
        except chd.ChdFormatError as exc:
            raise DiscImageError(str(exc)) from exc
