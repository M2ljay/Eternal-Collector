"""Exact game identifiers read from disc and cartridge images, and the save folders they name.

A standalone emulator files a disc game's save under an identifier the disc
itself carries — Dolphin under the GameCube/Wii disc ID, PPSSPP under the PSP
game ID, PCSX2 under the PS2 boot serial; Citra/Azahar key a 3DS game's mods
by its title ID. This module owns reading those
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
N3DS = "3ds"
"""The Nintendo 3DS family: a cartridge or package image whose identifier is its 16-hex-digit title ID."""
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
    dash (``ULUS10234``), the PS2 serial with its dash (``SLUS-20062``), or a
    3DS title ID as sixteen upper-case hex digits (``0004000000055D00``).
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


_PS2_BOOT_PATH_RE = re.compile(r"^\s*BOOT2\s*=\s*cdrom0?:\\?([^;\s]+)(?:;\d+)?\s*$", re.IGNORECASE)
_ISO_NAME_RE = re.compile(r"^[A-Z0-9_.\-]{1,64}$")

PS2_ELF_MAX_BYTES = 64 * 1024 * 1024
"""Largest boot ELF read for its CRC: PS2 main RAM is 32 MiB, so a real one is far below this."""
ELF_MAGIC = b"\x7fELF"


def parse_system_cnf_boot_path(data: bytes) -> tuple[str, ...] | None:
    """The path components of the executable a PS2 ``SYSTEM.CNF`` boots (``cdrom0:\\SLUS_209.46;1`` → ``SLUS_209.46``).

    Only ``BOOT2`` (a PS2 executable) counts. Components are upper-cased, as
    ISO 9660 names are, and each must be a plain ISO name; anything else is
    ``None``.
    """
    text = data[:4096].decode("ascii", errors="replace")
    for line in text.splitlines():
        match = _PS2_BOOT_PATH_RE.match(line)
        if match is None:
            continue
        parts = tuple(p.upper() for p in match.group(1).split("\\") if p)
        if parts and all(_ISO_NAME_RE.match(p) and p not in (".", "..") for p in parts):
            return parts
        return None
    return None


def ps2_elf_crc(elf: bytes) -> int:
    """PCSX2's CRC of a boot ELF: the XOR of every little-endian 32-bit word, a trailing partial word ignored.

    ``ElfObject::GetCRC`` / ``ReadAndGetCRC`` (``pcsx2/Elfheader.cpp``); not a
    CRC-32. PCSX2 names per-game patches, cheats and game settings by it
    (``Patch::GetPnachTemplate``: ``<SERIAL>_<CRC:08X>.pnach``).
    """
    words = len(elf) // 4
    if words == 0:
        return 0
    value = int.from_bytes(elf[: words * 4], "little")
    width = 1 << (words - 1).bit_length()
    while width > 1:
        width //= 2
        value = (value >> (width * 32)) ^ (value & ((1 << (width * 32)) - 1))
    return value


@dataclass(frozen=True)
class Ps2ElfCrc:
    """The boot ELF CRC of a PS2 image, or why it could not be read (``crc`` ``None``, ``reason`` set)."""

    crc: int | None
    reason: str | None = None

    @property
    def text(self) -> str | None:
        """The CRC as PCSX2 writes it in file names (``{:08X}``)."""
        return f"{self.crc:08X}" if self.crc is not None else None


# -- Nintendo 3DS ---------------------------------------------------------------
#
# Layouts per 3dbrew (NCSD, NCCH, CIA, Title metadata). The NCSD and NCCH
# headers are never encrypted, even on an encrypted dump; a CIA's TMD is not
# encrypted either. Citra/Azahar key a game's mods and textures by the NCCH
# program ID, rendered ``{:016X}`` (the ``load/mods/{:016X}/`` template the
# vendored atlas cites from the shipped binary).

N3DS_HEADER_SIZE = 0x200
"""Bytes of an NCSD/NCCH header (and enough of a CIA's archive header) the parsers below need."""
N3DS_MEDIA_UNIT = 0x200
CIA_TMD_READ_SIZE = 0x300
"""Bytes of a CIA's TMD that hold every signature form's header up to the title ID."""

_NCSD_MAGIC_OFFSET = 0x100
_NCSD_PARTITION0_OFFSET = 0x120
_NCCH_PROGRAM_ID_OFFSET = 0x118
_CIA_HEADER_SIZE = 0x2020
_CIA_ALIGN = 64
# Signature type → (signature size, padding) for a TMD's signature block.
_TMD_SIGNATURES = {
    0x010000: (0x200, 0x3C),
    0x010001: (0x100, 0x3C),
    0x010002: (0x3C, 0x40),
    0x010003: (0x200, 0x3C),
    0x010004: (0x100, 0x3C),
    0x010005: (0x3C, 0x40),
}
_TMD_TITLE_ID_OFFSET = 0x4C


def _title_id_text(value: int) -> str | None:
    return f"{value:016X}" if value else None


def ncsd_partition0_offset(header: bytes) -> int | None:
    """The byte offset of the first NCCH partition of an NCSD (``.3ds`` / ``.cci``) image, or ``None``."""
    if len(header) < N3DS_HEADER_SIZE or header[_NCSD_MAGIC_OFFSET : _NCSD_MAGIC_OFFSET + 4] != b"NCSD":
        return None
    offset, size = struct.unpack_from("<II", header, _NCSD_PARTITION0_OFFSET)
    if offset == 0 or size == 0:
        return None
    return offset * N3DS_MEDIA_UNIT


def ncch_program_id(header: bytes) -> str | None:
    """The program ID of an NCCH header (``.cxi`` / ``.app``, or an NCSD's partition), or ``None``."""
    if len(header) < N3DS_HEADER_SIZE or header[0x100:0x104] != b"NCCH":
        return None
    (program_id,) = struct.unpack_from("<Q", header, _NCCH_PROGRAM_ID_OFFSET)
    return _title_id_text(program_id)


def cia_tmd_offset(header: bytes) -> int | None:
    """Where a CIA's title metadata starts, from its archive header, or ``None``.

    The certificate chain, ticket and TMD follow the header, each aligned to
    64 bytes. Only the standard ``0x2020``-byte header is accepted.
    """
    if len(header) < 0x20:
        return None
    header_size, _type, _version, cert_size, ticket_size, tmd_size = struct.unpack_from("<IHHIII", header, 0)
    if header_size != _CIA_HEADER_SIZE or tmd_size == 0:
        return None
    return _align(header_size) + _align(cert_size) + _align(ticket_size)


def _align(size: int) -> int:
    return (size + _CIA_ALIGN - 1) // _CIA_ALIGN * _CIA_ALIGN


def tmd_title_id(tmd: bytes) -> str | None:
    """The title ID of a TMD (its signature block, then the header's title ID), or ``None``."""
    if len(tmd) < 4:
        return None
    (sig_type,) = struct.unpack_from(">I", tmd, 0)
    signature = _TMD_SIGNATURES.get(sig_type)
    if signature is None:
        return None
    start = 4 + signature[0] + signature[1] + _TMD_TITLE_ID_OFFSET
    if len(tmd) < start + 8:
        return None
    (title_id,) = struct.unpack_from(">Q", tmd, start)
    return _title_id_text(title_id)
