"""Exact game identifiers read from disc images, and the save folders they name.

A standalone emulator files a disc game's save under an identifier the disc
itself carries — Dolphin under the GameCube/Wii disc ID, PPSSPP under the PSP
game ID, PCSX2 under the PS2 boot serial. This module owns reading those
identifiers out of the bytes a disc image yields (the GameCube/Wii disc
header, ISO 9660 directory structures, ``UMD_DATA.BIN``, ``PARAM.SFO``,
``SYSTEM.CNF``) and the emulator-side naming rules that follow from them.
Getting the bytes off a compressed container is the adapter's job; anything
that does not parse exactly answers ``None`` — an unidentified disc has no
save set, never a guessed one.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

GAMECUBE = "gc"
WII = "wii"
PSP = "psp"
PS2 = "ps2"
NINTENDO_OPTICAL = "gc-wii"
"""The disc family a GameCube-or-Wii emulator asks for: the image decides which of the two it is."""

ISO_SECTOR_SIZE = 2048
PRIMARY_VOLUME_DESCRIPTOR_LBA = 16

# Disc header magic words (big-endian), Dolphin Source/Core/DiscIO/VolumeDisc /
# Yet Another GameCube Documentation: a Wii disc carries 0x5D1C9EA3 at 0x18, a
# GameCube disc 0xC2339F3D at 0x1C.
_WII_MAGIC_OFFSET, _WII_MAGIC = 0x18, 0x5D1C9EA3
_GC_MAGIC_OFFSET, _GC_MAGIC = 0x1C, 0xC2339F3D
DISC_HEADER_PREFIX = 0x20
"""Bytes of the GameCube/Wii disc header :func:`parse_nintendo_disc_header` needs."""

_ID6_RE = re.compile(rb"^[0-9A-Z]{6}$")
_PSP_GAME_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")
_PS2_BOOT_RE = re.compile(r"^\s*BOOT2\s*=\s*cdrom0:\\?\\?([A-Z]{4})_(\d{3})\.(\d{2})(?:;\d+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class DiscCode:
    """The identifier a disc image carries, and which console's disc it is.

    ``code`` is the GameCube/Wii ID6 (``GALE01``), the PSP game ID without its
    dash (``ULUS10234``), or the PS2 serial with its dash (``SLUS-20062``).
    """

    platform: str
    code: str
    revision: int = 0


# -- GameCube / Wii ------------------------------------------------------------


def parse_nintendo_disc_header(header: bytes) -> DiscCode | None:
    """The ID6 and console of a GameCube/Wii disc header, or ``None``.

    *header* is the start of the disc (at least :data:`DISC_HEADER_PREFIX`
    bytes). The console is decided by the magic word, never by the ID's first
    letter; a header carrying neither magic, or an ID6 that is not six
    upper-case letters/digits, answers ``None``.
    """
    if len(header) < DISC_HEADER_PREFIX:
        return None
    id6 = header[:6]
    if not _ID6_RE.match(id6):
        return None
    (wii_magic,) = struct.unpack_from(">I", header, _WII_MAGIC_OFFSET)
    (gc_magic,) = struct.unpack_from(">I", header, _GC_MAGIC_OFFSET)
    if wii_magic == _WII_MAGIC:
        return DiscCode(WII, id6.decode("ascii"), header[7])
    if gc_magic == _GC_MAGIC:
        return DiscCode(GAMECUBE, id6.decode("ascii"), header[7])
    return None


# Dolphin DiscIO/Enums.cpp ``CountryCodeToRegion`` for a GameCube disc, mapped
# through ``Config::GetDirectoryForRegion`` (Legacy style, the default GCI path):
# NTSC-J → JAP, NTSC-U → USA, PAL → EUR, and NTSC-K (no GameCube region) → JAP.
# X/Y/Z depend on a region Dolphin reads from bi2.bin, which a compressed image's
# header does not carry, so they are left unidentified rather than guessed.
_GC_REGION_BY_COUNTRY = {
    **dict.fromkeys("JW", "JAP"),
    **dict.fromkeys("KQT", "JAP"),
    **dict.fromkeys("EBN", "USA"),
    **dict.fromkeys("DFHILMPRSUV", "EUR"),
}
# Dolphin treats an 'E' disc whose revision byte is 0x30 or more as a Korean
# release in English (NTSC-J), Enums.cpp ``CountryCodeToRegion``.
_KOREAN_ENGLISH_REVISION = 0x30


def gamecube_region_folder(id6: str, revision: int = 0) -> str | None:
    """Dolphin's GCI region folder (``USA`` / ``EUR`` / ``JAP``) for a GameCube disc, or ``None``.

    Decided by the country byte (``id6[3]``) as Dolphin maps it; *revision* is
    the disc header's version byte (offset 7).
    """
    if len(id6) != 6:
        return None
    country = id6[3]
    if country == "E" and revision >= _KOREAN_ENGLISH_REVISION:
        return "JAP"
    return _GC_REGION_BY_COUNTRY.get(country)


def wii_title_folder(id6: str) -> str | None:
    """The NAND title folder of a Wii disc game: its ID4 as eight lower-case hex digits.

    ``SMOXE8`` → ``534d4f58`` (Dolphin's ``title/00010000/<this>/data`` holds the save).
    """
    if len(id6) < 4 or not id6[:4].isascii():
        return None
    return id6[:4].encode("ascii").hex()


def gci_game_code(header: bytes) -> str | None:
    """The 4-character game code a GCI save file starts with, or ``None``.

    A GCI file opens with the save's 0x40-byte directory entry, whose first
    four bytes are the owning game's code (Dolphin GCMemcard ``DEntry::m_gamecode``).
    """
    if len(header) < 4:
        return None
    code = header[:4]
    if not re.fullmatch(rb"[0-9A-Z]{4}", code):
        return None
    return code.decode("ascii")


# -- ISO 9660 ------------------------------------------------------------------


@dataclass(frozen=True)
class IsoExtent:
    """Where a file or directory lives on an ISO 9660 volume."""

    lba: int
    size: int
    is_dir: bool


def parse_primary_volume_descriptor(sector: bytes) -> IsoExtent | None:
    """The root directory's extent from the primary volume descriptor sector, or ``None``.

    Requires type 1, the ``CD001`` identifier, version 1, and a root directory
    record (at offset 156) that is itself a directory.
    """
    if len(sector) < ISO_SECTOR_SIZE or sector[0] != 1 or sector[1:6] != b"CD001" or sector[6] != 1:
        return None
    return _parse_record(sector[156:190])


def _parse_record(record: bytes) -> IsoExtent | None:
    if len(record) < 34 or record[0] < 34:
        return None
    (lba,) = struct.unpack_from("<I", record, 2)
    (size,) = struct.unpack_from("<I", record, 10)
    return IsoExtent(lba=lba, size=size, is_dir=bool(record[25] & 0x02))


def find_directory_entry(directory: bytes, name: str) -> IsoExtent | None:
    """The extent of *name* inside an ISO 9660 *directory* extent, or ``None``.

    Matching is case-insensitive and ignores a file version suffix (``;1``).
    Directory records never straddle a sector boundary: a zero length byte
    pads to the next sector.
    """
    wanted = name.upper()
    pos = 0
    while pos < len(directory):
        length = directory[pos]
        if length == 0:
            pos = (pos // ISO_SECTOR_SIZE + 1) * ISO_SECTOR_SIZE
            continue
        record = directory[pos : pos + length]
        if len(record) < 34 or length < 33 + record[32]:
            return None
        raw_name = record[33 : 33 + record[32]]
        if raw_name not in (b"\x00", b"\x01"):
            entry_name = raw_name.decode("ascii", errors="replace").split(";", 1)[0].upper()
            if entry_name == wanted:
                return _parse_record(record)
        pos += length
    return None


# -- PSP -----------------------------------------------------------------------


def parse_umd_data(data: bytes) -> str | None:
    """The game ID from a PSP disc's ``UMD_DATA.BIN`` (``ULUS-10234|...`` → ``ULUS10234``)."""
    head = data[:64].split(b"|", 1)[0].decode("ascii", errors="replace").strip()
    return normalize_psp_game_id(head)


def parse_param_sfo_disc_id(data: bytes) -> str | None:
    """The ``DISC_ID`` value of a ``PARAM.SFO``, normalized like :func:`parse_umd_data`, or ``None``."""
    if len(data) < 20 or data[:4] != b"\x00PSF":
        return None
    key_table, data_table, count = struct.unpack_from("<III", data, 8)
    for i in range(count):
        offset = 20 + i * 16
        if offset + 16 > len(data):
            return None
        key_offset, _fmt, value_len, _max_len, value_offset = struct.unpack_from("<HHIII", data, offset)
        key_start = key_table + key_offset
        key_end = data.find(b"\x00", key_start)
        if key_end < 0 or data[key_start:key_end] != b"DISC_ID":
            continue
        value_start = data_table + value_offset
        value = data[value_start : value_start + value_len].split(b"\x00", 1)[0]
        return normalize_psp_game_id(value.decode("ascii", errors="replace"))
    return None


def normalize_psp_game_id(raw: str) -> str | None:
    """``ULUS-10234`` / ``ULUS10234`` → ``ULUS10234``; anything else → ``None``."""
    candidate = raw.strip().replace("-", "")
    return candidate if _PSP_GAME_ID_RE.match(candidate) else None


# -- PS2 -----------------------------------------------------------------------


def parse_system_cnf_serial(data: bytes) -> str | None:
    """The boot serial named by a PS2 ``SYSTEM.CNF`` (``BOOT2 = cdrom0:\\SLUS_200.62;1`` → ``SLUS-20062``).

    Only a ``BOOT2`` line (a PS2 executable) counts; a PS1 disc's ``BOOT``
    line answers ``None``.
    """
    text = data[:4096].decode("ascii", errors="replace")
    for line in text.splitlines():
        match = _PS2_BOOT_RE.match(line)
        if match:
            prefix, head, tail = match.groups()
            return f"{prefix.upper()}-{head}{tail}"
    return None
