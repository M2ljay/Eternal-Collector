"""Reads the game identifier out of a disc or cartridge image file. Implements ``DiscCodeReader``.

Opens the image, reads only the handful of sectors that identify it — the
GameCube/Wii disc header, an ISO 9660 walk to ``UMD_DATA.BIN`` /
``PSP_GAME/PARAM.SFO`` / ``SYSTEM.CNF``, or a 3DS image's NCSD/NCCH header or
CIA title metadata — and hands the bytes to
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
    CIA_TMD_READ_SIZE,
    DISC_HEADER_PREFIX,
    ELF_MAGIC,
    ISO_SECTOR_SIZE,
    N3DS,
    N3DS_HEADER_SIZE,
    NINTENDO_OPTICAL,
    PRIMARY_VOLUME_DESCRIPTOR_LBA,
    PS2,
    PS2_ELF_MAX_BYTES,
    PSP,
    DiscCode,
    Ps2ElfCrc,
    cia_tmd_offset,
    find_directory_entry,
    ncch_program_id,
    ncsd_partition0_offset,
    parse_nintendo_disc_header,
    parse_param_sfo_disc_id,
    parse_primary_volume_descriptor,
    parse_system_cnf_boot_path,
    parse_system_cnf_serial,
    parse_umd_data,
    ps2_elf_crc,
    tmd_title_id,
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
    """Identifies GameCube/Wii (RVZ, WIA, ISO, GCM), PSP (ISO, CSO, CHD), PS2 (ISO, CHD) and 3DS images."""

    def __init__(self, *, logger: logging.Logger, zstd_decompress: Callable[[bytes], bytes] | None = None) -> None:
        self._logger = logger
        self._zstd = zstd_decompress
        self._cache: dict[tuple[str, int, int, str], DiscCode | None] = {}
        self._problems: dict[tuple[str, str], tuple[str, str]] = {}
        self._elf_crcs: dict[tuple[str, int, int], Ps2ElfCrc] = {}

    def read_disc_code(self, path: str, family: str) -> DiscCode | None:
        """The identifier of the image at *path*, read as a *family* disc, or ``None``.

        *family* is :data:`domain.disc_ids.NINTENDO_OPTICAL`, ``PSP``, ``PS2`` or ``N3DS``.
        ``None`` for an unsupported format, an unreadable file, or an image
        that does not decode exactly.
        """
        try:
            st = os.stat(path)
        except OSError as exc:
            self._problems[(path, family)] = ("unreadable", exc.strerror or str(exc))
            return None
        key = (path, st.st_size, st.st_mtime_ns, family)
        if key in self._cache:
            return self._cache[key]
        ext = os.path.splitext(path)[1].lower()
        problem: tuple[str, str] | None = None
        try:
            with open(path, "rb") as f:
                code = self._read(f, ext, family)
        except OSError as exc:
            self._logger.info("disc code: cannot identify %s: %s", path, exc)
            code, problem = None, ("unreadable", exc.strerror or str(exc))
        except (DiscImageError, struct.error) as exc:
            self._logger.info("disc code: cannot identify %s: %s", path, exc)
            code, problem = None, ("unsupported_image", str(exc))
        if code is None and problem is None:
            problem = ("no_disc_id", "") if self._handles(ext, family) else ("unsupported_format", ext)
        self._cache[key] = code
        if problem is None:
            self._problems.pop((path, family), None)
        else:
            self._problems[(path, family)] = problem
        return code

    def read_ps2_elf_crc(self, path: str) -> Ps2ElfCrc:
        """PCSX2's CRC of the boot ELF ``SYSTEM.CNF`` names in the PS2 image at *path* (ISO, CSO or CHD).

        Reads the whole ELF through the same sector sources the serial is read
        with. Any other format, a CHD codec this build cannot decode, or an
        image whose ``BOOT2`` file is missing or not an ELF answers the reason.
        """
        try:
            st = os.stat(path)
        except OSError as exc:
            return Ps2ElfCrc(None, f"the game file could not be read: {exc.strerror or exc}")
        key = (path, st.st_size, st.st_mtime_ns)
        if key not in self._elf_crcs:
            self._elf_crcs[key] = self._read_ps2_elf_crc(path)
        return self._elf_crcs[key]

    def _read_ps2_elf_crc(self, path: str) -> Ps2ElfCrc:
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".iso", ".cso", ".chd"):
            return Ps2ElfCrc(None, f"PCSX2 game files of type {ext or 'none'} are not read here")
        try:
            with open(path, "rb") as f:
                source = self._sector_source(f, ext)
                if source is None:
                    return Ps2ElfCrc(None, f"{ext} images are not read here")
                cnf = _read_iso_file(source, ("SYSTEM.CNF",), _MAX_ID_FILE_BYTES)
                boot = parse_system_cnf_boot_path(cnf) if cnf is not None else None
                if boot is None:
                    return Ps2ElfCrc(None, "the disc's SYSTEM.CNF names no PS2 boot executable")
                elf = _read_iso_file(source, boot, PS2_ELF_MAX_BYTES)
        except OSError as exc:
            return Ps2ElfCrc(None, f"the game file could not be read: {exc.strerror or exc}")
        except (DiscImageError, struct.error) as exc:
            return Ps2ElfCrc(None, f"the image could not be decoded: {exc}")
        if elf is None or not elf.startswith(ELF_MAGIC):
            return Ps2ElfCrc(None, "the boot executable SYSTEM.CNF names is missing or not an ELF")
        return Ps2ElfCrc(ps2_elf_crc(elf))

    def disc_code_problem(self, path: str, family: str) -> tuple[str, str] | None:
        """Why the last :meth:`read_disc_code` of *path* as *family* found no identifier, or ``None``."""
        return self._problems.get((path, family))

    @staticmethod
    def _handles(ext: str, family: str) -> bool:
        if family == NINTENDO_OPTICAL:
            return ext in (".rvz", ".wia", ".iso", ".gcm")
        if family == N3DS:
            return ext in (".3ds", ".cci", ".cxi", ".app", ".cia")
        return ext in (".iso", ".cso", ".chd")

    def _read(self, f: BinaryIO, ext: str, family: str) -> DiscCode | None:
        if family == NINTENDO_OPTICAL:
            if ext in (".rvz", ".wia"):
                return _read_wia(f)
            if ext in (".iso", ".gcm"):
                return parse_nintendo_disc_header(f.read(DISC_HEADER_PREFIX))
            return None
        if family == N3DS:
            return _read_3ds(f, ext)
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


def _read_3ds(f: BinaryIO, ext: str) -> DiscCode | None:
    head = f.read(N3DS_HEADER_SIZE)
    if ext in (".3ds", ".cci"):
        offset = ncsd_partition0_offset(head)
        if offset is None:
            return None
        f.seek(offset)
        title_id = ncch_program_id(f.read(N3DS_HEADER_SIZE))
    elif ext in (".cxi", ".app"):
        title_id = ncch_program_id(head)
    elif ext == ".cia":
        offset = cia_tmd_offset(head)
        if offset is None:
            return None
        f.seek(offset)
        title_id = tmd_title_id(f.read(CIA_TMD_READ_SIZE))
    else:
        return None
    return DiscCode(N3DS, title_id) if title_id else None


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
