"""PS Vita installed-app layout: find the app root and read its title ID.

A Vita game stored in RomM as a folder is the content of an installed app
(``ux0:app/<TITLE_ID>``): ``eboot.bin`` beside ``sce_sys/param.sfo``. Vita3K
runs it by title ID, so the install step needs both the folder that holds that
layout and the ID from ``param.sfo``. Pure compute; the caller reads the files.
"""

from __future__ import annotations

import re
import struct

_TITLE_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")
_PARAM_SFO = ("sce_sys", "param.sfo")


def find_app_roots(relative_paths: list[str]) -> list[str]:
    """Directories (relative, ``/``-separated, ``""`` for the top) holding ``sce_sys/param.sfo``.

    Shallowest first, so a folder whose app sits at the top wins over any
    nested copy.
    """
    roots: set[str] = set()
    for raw in relative_paths:
        parts = [p for p in raw.replace("\\", "/").split("/") if p]
        if len(parts) >= 2 and [p.lower() for p in parts[-2:]] == list(_PARAM_SFO):
            roots.add("/".join(parts[:-2]))
    return sorted(roots, key=lambda r: (r.count("/") + (1 if r else 0), r))


def is_title_id(value: str) -> bool:
    """True for a Vita title ID such as ``PCSE01274``."""
    return bool(_TITLE_ID_RE.match(value))


def parse_sfo_title_id(data: bytes) -> str | None:
    """The ``TITLE_ID`` value of a ``param.sfo``, or ``None`` when absent or malformed."""
    if len(data) < 20 or data[:4] != b"\x00PSF":
        return None
    key_table, data_table, count = struct.unpack_from("<III", data, 8)
    for i in range(count):
        offset = 20 + i * 16
        if offset + 16 > len(data):
            return None
        key_off, _fmt, length, _max_len, data_off = struct.unpack_from("<HHIII", data, offset)
        key_start = key_table + key_off
        key_end = data.find(b"\x00", key_start)
        if key_end < 0 or data[key_start:key_end] != b"TITLE_ID":
            continue
        start = data_table + data_off
        value = data[start : start + length].split(b"\x00", 1)[0].decode("ascii", "replace")
        return value if is_title_id(value) else None
    return None
