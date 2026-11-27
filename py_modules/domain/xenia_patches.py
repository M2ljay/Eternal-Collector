"""Xenia Canary game patches: which ``.patch.toml`` files are a game's, its entries, and switching one.

Xenia loads every file in ``<storage root>\\patches`` whose name is eight hex
digits then anything then ``.patch.toml`` (``PatchDB::patch_filename_regex_``),
keeps those whose ``title_id`` is the running game's, and applies each
``[[patch]]`` whose ``is_enabled`` is true (default false) — and only when one of
the file's ``hash`` values matches the running executable, which this module
does not compute (``xenia/patcher/patch_db.cc``).

The files are TOML, read and edited here line by line in the narrow shape the
patch database uses: top-level ``key = value`` lines, then ``[[patch]]`` blocks
whose own ``name`` / ``desc`` / ``is_enabled`` lines come before any sub-table
(``[[patch.be32]]``). A file using multi-line strings, a block without a name, or
a name twice is reported read-only rather than parsed.

No I/O. Pure functions only.
"""

from __future__ import annotations

import re

from domain.mod_toggles import ToggleEntry, ToggleList, plain_entry_name

PATCH_FILE_RE = re.compile(r"^[A-Fa-f0-9]{8}.*\.patch\.toml$")
_BLOCK_RE = re.compile(r"^\s*\[\[\s*patch\s*\]\]\s*(#.*)?$")
_TABLE_RE = re.compile(r"^\s*\[")
_STRING_KEY_RE = re.compile(r"""^(\s*)(name|desc|title_id)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(#.*)?$""")
_BOOL_KEY_RE = re.compile(r"^(\s*)is_enabled(\s*=\s*)(true|false)(\s*(#.*)?)$")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}


def _unescape(raw: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), raw)


def _string_value(match: re.Match[str]) -> str:
    return _unescape(match.group(3)) if match.group(3) is not None else match.group(4)


def patch_file_title_id(text: str) -> str | None:
    """The top-level ``title_id`` of a patch file (upper-case), or ``None``."""
    for line in text.splitlines():
        if _BLOCK_RE.match(line) or _TABLE_RE.match(line):
            return None
        match = _STRING_KEY_RE.match(line)
        if match and match.group(2) == "title_id":
            return _string_value(match).upper()
    return None


def _blocks(text: str) -> list[dict] | None:
    """Each ``[[patch]]`` block's name, description, enabled state and line numbers; ``None`` when unsafe."""
    if '"""' in text or "'''" in text:
        return None
    blocks: list[dict] = []
    current: dict | None = None
    for index, line in enumerate(text.splitlines()):
        if _BLOCK_RE.match(line):
            current = {
                "header": index,
                "name": None,
                "name_line": None,
                "desc": "",
                "enabled": False,
                "bool_line": None,
            }
            blocks.append(current)
            continue
        if _TABLE_RE.match(line):
            current = None
            continue
        if current is None:
            continue
        string = _STRING_KEY_RE.match(line)
        if string and string.group(2) == "name":
            current["name"], current["name_line"] = _string_value(string), index
        elif string and string.group(2) == "desc":
            current["desc"] = _string_value(string)
        elif (flag := _BOOL_KEY_RE.match(line)) is not None:
            current["enabled"], current["bool_line"] = flag.group(3) == "true", index
        elif re.match(r"^\s*is_enabled\s*=", line):
            return None
    names = [b["name"] for b in blocks]
    if any(n is None for n in names) or len(set(names)) != len(names):
        return None
    return blocks


def xenia_patches(text: str | None, origin: str) -> ToggleList:
    """The patches of one Xenia patch file with their state; read-only when its layout is not one edited here."""
    if text is None:
        return ToggleList((), True, None)
    blocks = _blocks(text)
    if blocks is None:
        return ToggleList((), False, f"{origin} is laid out in a way not edited here; change it in Xenia Manager.")
    note = ("Xenia applies a patch only to the executable version listed in the file (its hash), not checked here.",)
    entries = tuple(
        ToggleEntry(b["name"], b["name"], b["desc"], b["enabled"], plain_entry_name(b["name"]), origin, note)
        for b in blocks
    )
    return ToggleList(entries, True, None)


def xenia_set_patch(text: str, name: str, enabled: bool) -> str | None:
    """The patch file with ``is_enabled`` of the ``[[patch]]`` named *name* set; ``None`` when not safe.

    An existing ``is_enabled`` line keeps its spacing and comment; a block
    without one gets ``is_enabled = <value>`` right after its ``name`` line.
    """
    blocks = _blocks(text)
    block = next((b for b in blocks or [] if b["name"] == name), None)
    if block is None:
        return None
    lines = text.splitlines()
    value = "true" if enabled else "false"
    if block["bool_line"] is not None:
        match = _BOOL_KEY_RE.match(lines[block["bool_line"]])
        if match is None:
            return None
        lines[block["bool_line"]] = f"{match.group(1)}is_enabled{match.group(2)}{value}{match.group(4)}"
    else:
        indent = re.match(r"^(\s*)", lines[block["name_line"]])
        lines.insert(block["name_line"] + 1, f"{indent.group(1) if indent else ''}is_enabled = {value}")
    newline = "\r\n" if "\r\n" in text else "\n"
    joined = newline.join(lines)
    return joined + newline if text.endswith(("\n", "\r")) else joined
