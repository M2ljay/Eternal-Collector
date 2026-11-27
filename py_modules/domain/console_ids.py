"""Identifiers of PS3, PS4, Xbox 360 and Wii U games, read from the bytes or text of the game's own files.

The companion of :mod:`domain.disc_ids` for the consoles whose mods, patches
and updates are named by a title ID: a PS3 or PS4 ``PARAM.SFO`` (serial and
application version), an Xbox 360 executable's header (title ID, from
``default.xex`` inside an XDVDFS disc image), and a Wii U ``meta.xml`` (title
ID). Reading the files is the adapters' job; everything here takes bytes or
text and answers exactly, or ``None``.

No I/O. Pure functions only.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

# -- PARAM.SFO (PS3, PS4) ----------------------------------------------------------

_SFO_MAGIC = b"\x00PSF"
_SFO_UTF8 = (0x0204, 0x0004)
_SFO_INT32 = 0x0404
_PS3_SERIAL_RE = re.compile(r"^[A-Z]{4}\d{5}$")
_PS4_SERIAL_RE = re.compile(r"^[A-Z]{4}\d{5}$")
_APP_VER_RE = re.compile(r"^\d{2}\.\d{2}$")


def parse_param_sfo(data: bytes) -> dict[str, str] | None:
    """Every key of a ``PARAM.SFO`` with its value as text (integers in decimal), or ``None`` when it is not one.

    Layout per psdevwiki (PARAM.SFO): a 20-byte header (magic, version, key
    table offset, data table offset, entry count), then 16-byte index entries.
    """
    if len(data) < 20 or data[:4] != _SFO_MAGIC:
        return None
    key_table, data_table, count = struct.unpack_from("<III", data, 8)
    out: dict[str, str] = {}
    for i in range(count):
        offset = 20 + i * 16
        if offset + 16 > len(data):
            return None
        key_offset, fmt, value_len, _max_len, value_offset = struct.unpack_from("<HHIII", data, offset)
        key_start = key_table + key_offset
        key_end = data.find(b"\x00", key_start)
        start = data_table + value_offset
        if key_end < 0 or start + value_len > len(data):
            return None
        key = data[key_start:key_end].decode("ascii", errors="replace")
        raw = data[start : start + value_len]
        if fmt == _SFO_INT32 and value_len >= 4:
            out[key] = str(struct.unpack_from("<I", raw)[0])
        elif fmt in _SFO_UTF8:
            out[key] = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    return out


@dataclass(frozen=True)
class SfoGame:
    """A PS3 or PS4 game's serial (``BLUS30443`` / ``CUSA00001``) and application version (``01.04``)."""

    serial: str
    app_version: str | None


def ps3_game(sfo: dict[str, str] | None) -> SfoGame | None:
    """The serial and ``APP_VER`` a PS3 ``PARAM.SFO`` names (``TITLE_ID``), or ``None``."""
    return _sfo_game(sfo, _PS3_SERIAL_RE)


def ps4_game(sfo: dict[str, str] | None) -> SfoGame | None:
    """The serial and ``APP_VER`` a PS4 ``param.sfo`` names (``TITLE_ID``), or ``None``."""
    return _sfo_game(sfo, _PS4_SERIAL_RE)


def _sfo_game(sfo: dict[str, str] | None, pattern: re.Pattern[str]) -> SfoGame | None:
    if sfo is None:
        return None
    serial = sfo.get("TITLE_ID", "").strip()
    if not pattern.match(serial):
        return None
    version = sfo.get("APP_VER", "").strip()
    return SfoGame(serial, version if _APP_VER_RE.match(version) else None)


# -- Xbox 360: XDVDFS and XEX ------------------------------------------------------

XDVDFS_SECTOR = 2048
XDVDFS_MAGIC = b"MICROSOFT*XBOX*MEDIA"
XDVDFS_DESCRIPTOR_SECTOR = 32
XDVDFS_PARTITION_OFFSETS: tuple[int, ...] = (0, 0x18300000, 0xFD90000, 0x2080000)
"""Where the game partition starts in an image: an extracted ``xiso`` (0), and the XGD1, XGD2 and XGD3 offsets of a full
disc dump (extract-xiso / xenia ``disc_image_device``)."""

_XEX2_MAGIC = b"XEX2"
_XEX_EXECUTION_INFO = 0x00040006
_XEX_MAX_HEADERS = 256
_DIR_ATTRIBUTE = 0x10
_TITLE_ID_RE = re.compile(r"^[0-9A-F]{8}$")


@dataclass(frozen=True)
class XdvdfsEntry:
    """A file or folder of an XDVDFS volume: first sector (from the partition start), size, and whether a folder."""

    sector: int
    size: int
    is_dir: bool


def parse_xdvdfs_descriptor(sector: bytes) -> XdvdfsEntry | None:
    """The root folder from the volume descriptor sector (magic at 0 and 0x7EC), or ``None``."""
    if len(sector) < XDVDFS_SECTOR or sector[:20] != XDVDFS_MAGIC or sector[0x7EC : 0x7EC + 20] != XDVDFS_MAGIC:
        return None
    root_sector, root_size = struct.unpack_from("<II", sector, 0x14)
    if root_size == 0:
        return None
    return XdvdfsEntry(root_sector, root_size, True)


def find_xdvdfs_entry(directory: bytes, name: str) -> XdvdfsEntry | None:
    """The entry *name* (case-insensitive) of an XDVDFS folder table, walking its binary tree; ``None`` if absent.

    Each node: left and right child offsets (16-bit, in 4-byte units from the
    table start), first sector, size, attributes, name length, name. Every
    node is visited at most once, so a corrupt table cannot loop.
    """
    wanted = name.lower()
    stack = [0]
    seen: set[int] = set()
    while stack:
        offset = stack.pop()
        if offset in seen or offset + 14 > len(directory):
            continue
        seen.add(offset)
        left, right, sector, size, attributes, length = struct.unpack_from("<HHIIBB", directory, offset)
        if left == 0xFFFF and right == 0xFFFF and length == 0xFF:
            continue
        raw = directory[offset + 14 : offset + 14 + length]
        if len(raw) == length and raw.decode("latin-1").lower() == wanted:
            return XdvdfsEntry(sector, size, bool(attributes & _DIR_ATTRIBUTE))
        stack.extend(child * 4 for child in (left, right) if child not in (0, 0xFFFF))
    return None


def xex_title_id(header: bytes) -> str | None:
    """The title ID in an ``XEX2`` executable's execution-info optional header (``{:08X}``), or ``None``.

    Layout per Free60 (XEX): magic, flags, PE data offset, reserved, security
    info offset, optional-header count (all big-endian), then (key, value)
    pairs; key ``0x00040006`` points at the execution info, whose title ID is
    the fourth 32-bit field.
    """
    if len(header) < 0x18 or header[:4] != _XEX2_MAGIC:
        return None
    (count,) = struct.unpack_from(">I", header, 0x14)
    if count > _XEX_MAX_HEADERS:
        return None
    for i in range(count):
        at = 0x18 + i * 8
        if at + 8 > len(header):
            return None
        key, value = struct.unpack_from(">II", header, at)
        if key == _XEX_EXECUTION_INFO:
            if value + 16 > len(header):
                return None
            (title_id,) = struct.unpack_from(">I", header, value + 12)
            text = f"{title_id:08X}"
            return text if title_id and _TITLE_ID_RE.match(text) else None
    return None


@dataclass(frozen=True)
class TitleIdAnswer:
    """A title ID read from a game file, or why it could not be (``title_id`` ``None``, ``reason`` set)."""

    title_id: str | None
    reason: str | None = None


# -- Wii U -------------------------------------------------------------------------

_META_TITLE_ID_RE = re.compile(r"<title_id\b[^>]*>\s*([0-9A-Fa-f]{16})\s*</title_id>")


def wiiu_title_id(meta_xml: str | None) -> str | None:
    """The 16-digit title ID of a Wii U ``meta/meta.xml`` (upper-case), or ``None``."""
    if meta_xml is None:
        return None
    match = _META_TITLE_ID_RE.search(meta_xml)
    return match.group(1).upper() if match else None
