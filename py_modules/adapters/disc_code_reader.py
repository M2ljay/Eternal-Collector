"""Reads the game identifier out of a disc image file. Implements ``DiscCodeReader``.

Opens the image, reads only the handful of sectors that identify it — the
GameCube/Wii disc header, or an ISO 9660 walk to ``UMD_DATA.BIN`` /
``PSP_GAME/PARAM.SFO`` / ``SYSTEM.CNF`` — and hands the bytes to
:mod:`domain.disc_ids`. Results are cached per file (path, size, mtime), so a
sync pass that asks for the same game repeatedly reads it once.
"""

from __future__ import annotations

import hashlib
import os
import struct
from typing import TYPE_CHECKING, BinaryIO

from adapters.disc_images import ChdReader, ChdSource, CsoSource, DiscImageError, PlainIsoSource
from domain.disc_ids import (
    DISC_HEADER_PREFIX,
    ISO_SECTOR_SIZE,
    NINTENDO_OPTICAL,
    PRIMARY_VOLUME_DESCRIPTOR_LBA,
    PS2,
    PSP,
    DiscCode,
    find_directory_entry,
    parse_nintendo_disc_header,
    parse_param_sfo_disc_id,
    parse_primary_volume_descriptor,
    parse_system_cnf_serial,
    parse_umd_data,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable
    from typing import Protocol

    class _SectorSource(Protocol):
        def read_sector(self, lba: int) -> bytes: ...


# WIA/RVZ (Dolphin docs/WiaAndRvz.md): a 0x48-byte file header — magic, two
# versions, the disc struct's size and SHA-1, two sizes, then the SHA-1 of the
# header's first 0x34 bytes — followed by the disc struct, whose bytes
# 0x10..0x90 are the disc's first 0x80 bytes stored uncompressed.
_WIA_MAGICS = (b"WIA\x01", b"RVZ\x01")
_WIA_HEAD_SIZE = 0x48
_WIA_HEAD_HASHED = 0x34
_WIA_DISC_HEADER_OFFSET = 0x10
_WIA_DISC_TYPES = {1: "gc", 2: "wii"}
_WIA_MAX_DISC_STRUCT = 0x1000

_MAX_DIRECTORY_BYTES = 64 * ISO_SECTOR_SIZE
_MAX_ID_FILE_BYTES = 32 * ISO_SECTOR_SIZE


class DiscCodeReaderAdapter:
    """Identifies GameCube/Wii (RVZ, WIA, ISO, GCM), PSP (ISO, CSO, CHD) and PS2 (ISO, CHD) images."""

    def __init__(self, *, logger: logging.Logger, zstd_decompress: Callable[[bytes], bytes] | None = None) -> None:
        self._logger = logger
        self._zstd = zstd_decompress
        self._cache: dict[tuple[str, int, int, str], DiscCode | None] = {}

    def read_disc_code(self, path: str, family: str) -> DiscCode | None:
        """The identifier of the image at *path*, read as a *family* disc, or ``None``.

        *family* is :data:`domain.disc_ids.NINTENDO_OPTICAL`, ``PSP`` or ``PS2``.
        ``None`` for an unsupported format, an unreadable file, or an image
        that does not decode exactly.
        """
        try:
            st = os.stat(path)
        except OSError:
            return None
        key = (path, st.st_size, st.st_mtime_ns, family)
        if key in self._cache:
            return self._cache[key]
        try:
            with open(path, "rb") as f:
                code = self._read(f, os.path.splitext(path)[1].lower(), family)
        except (OSError, DiscImageError, struct.error) as exc:
            self._logger.info("disc code: cannot identify %s: %s", path, exc)
            code = None
        self._cache[key] = code
        return code

    def _read(self, f: BinaryIO, ext: str, family: str) -> DiscCode | None:
        if family == NINTENDO_OPTICAL:
            if ext in (".rvz", ".wia"):
                return _read_wia(f)
            if ext in (".iso", ".gcm"):
                return parse_nintendo_disc_header(f.read(DISC_HEADER_PREFIX))
            return None
        source = self._sector_source(f, ext)
        if source is None:
            return None
        if family == PSP:
            return _psp_code(source)
        if family == PS2:
            return _ps2_code(source)
        return None

    def _sector_source(self, f: BinaryIO, ext: str) -> _SectorSource | None:
        if ext == ".iso":
            return PlainIsoSource(f)
        if ext == ".cso":
            return CsoSource(f)
        if ext == ".chd":
            reader = ChdReader(f) if self._zstd is None else ChdReader(f, zstd_decompress=self._zstd)
            return ChdSource(reader)
        return None


def _read_wia(f: BinaryIO) -> DiscCode | None:
    head = f.read(_WIA_HEAD_SIZE)
    if len(head) != _WIA_HEAD_SIZE or head[:4] not in _WIA_MAGICS:
        return None
    if hashlib.sha1(head[:_WIA_HEAD_HASHED]).digest() != head[_WIA_HEAD_HASHED:]:
        raise DiscImageError("WIA/RVZ header hash mismatch")
    (disc_size,) = struct.unpack_from(">I", head, 12)
    if not _WIA_DISC_HEADER_OFFSET + 0x80 <= disc_size <= _WIA_MAX_DISC_STRUCT:
        raise DiscImageError("WIA/RVZ disc struct has an implausible size")
    disc = f.read(disc_size)
    if len(disc) != disc_size or hashlib.sha1(disc).digest() != head[16:36]:
        raise DiscImageError("WIA/RVZ disc struct hash mismatch")
    code = parse_nintendo_disc_header(disc[_WIA_DISC_HEADER_OFFSET : _WIA_DISC_HEADER_OFFSET + 0x80])
    (disc_type,) = struct.unpack_from(">I", disc, 0)
    if code is None or _WIA_DISC_TYPES.get(disc_type) != code.platform:
        return None
    return code


def _read_iso_file(source: _SectorSource, path: tuple[str, ...], limit: int) -> bytes | None:
    root = parse_primary_volume_descriptor(source.read_sector(PRIMARY_VOLUME_DESCRIPTOR_LBA))
    if root is None:
        return None
    extent = root
    for depth, name in enumerate(path):
        if not extent.is_dir or extent.size > _MAX_DIRECTORY_BYTES:
            return None
        entry = find_directory_entry(_read_extent(source, extent.lba, extent.size), name)
        if entry is None or entry.is_dir != (depth < len(path) - 1):
            return None
        extent = entry
    if extent.size > limit:
        return None
    return _read_extent(source, extent.lba, extent.size)


def _read_extent(source: _SectorSource, lba: int, size: int) -> bytes:
    sectors = (size + ISO_SECTOR_SIZE - 1) // ISO_SECTOR_SIZE
    return b"".join(source.read_sector(lba + i) for i in range(sectors))[:size]


def _psp_code(source: _SectorSource) -> DiscCode | None:
    sfo = _read_iso_file(source, ("PSP_GAME", "PARAM.SFO"), _MAX_ID_FILE_BYTES)
    game_id = parse_param_sfo_disc_id(sfo) if sfo is not None else None
    if game_id is None:
        umd = _read_iso_file(source, ("UMD_DATA.BIN",), _MAX_ID_FILE_BYTES)
        game_id = parse_umd_data(umd) if umd is not None else None
    return DiscCode(PSP, game_id) if game_id else None


def _ps2_code(source: _SectorSource) -> DiscCode | None:
    cnf = _read_iso_file(source, ("SYSTEM.CNF",), _MAX_ID_FILE_BYTES)
    serial = parse_system_cnf_serial(cnf) if cnf is not None else None
    return DiscCode(PS2, serial) if serial else None
