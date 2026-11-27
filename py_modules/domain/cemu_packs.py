"""Cemu graphic packs: which installed packs are a game's, whether each is on, and switching one in ``settings.xml``.

A pack is a folder below ``graphicPacks`` holding ``rules.txt``; its
``[Definition]`` names the games it applies to (``titleIds``, comma-separated
16-digit title IDs) and whether it is on by default (``default``). Cemu turns a
pack on when ``settings.xml`` has a ``<GraphicPack><Entry filename="…\\rules.txt">``
for it without ``disabled="true"``, and otherwise falls back to the pack's
default (``CemuConfig::Load`` / ``Save``, ``GraphicPack2::LoadGraphicPack``,
``GraphicPack2`` constructor). The filename is the ``rules.txt`` path relative
to Cemu's user data folder.

``settings.xml`` is edited line by line in the shape Cemu writes it: one
``<GraphicPack>`` element whose ``<Entry filename="…" [disabled="true"]>`` start
tags each sit on their own line. Anything else — the legacy
``<Entry><filename>`` form, two ``GraphicPack`` elements — is read-only.

No I/O. Pure functions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.mod_toggles import ToggleEntry, ToggleList

_SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_KEY_RE = re.compile(r"^\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*$")
_TITLE_ID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
_ENTRY_RE = re.compile(r"""^(\s*)<Entry\s+filename="([^"]*)"((?:\s+disabled="(?:true|false|1|0)")?)\s*(/?)>\s*$""")
_DISABLED_RE = re.compile(r"""disabled="(true|1)\"""")
_XML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))


@dataclass(frozen=True)
class PackInfo:
    """One pack's display name, the title IDs it applies to and whether Cemu turns it on by default."""

    name: str
    title_ids: frozenset[str]
    default_enabled: bool


def pack_info(rules: str) -> PackInfo | None:
    """The ``[Definition]`` facts of a ``rules.txt``, or ``None`` when it names no title ID."""
    section = ""
    values: dict[str, str] = {}
    for line in rules.splitlines():
        header = _SECTION_RE.match(line)
        if header:
            section = header.group(1).strip().lower()
            continue
        pair = _KEY_RE.match(line)
        if pair and section == "definition":
            values.setdefault(pair.group(1).lower(), pair.group(2).strip().strip('"'))
    ids = frozenset(t.strip().upper() for t in values.get("titleids", "").split(",") if _TITLE_ID_RE.match(t.strip()))
    if not ids:
        return None
    default = values.get("default", "").lower() in ("true", "1")
    return PackInfo(values.get("name") or "", ids, default)


def normalized(filename: str) -> str:
    """A pack path as compared: backslashes, case-folded (Windows paths)."""
    return filename.replace("/", "\\").lower()


def _unescape(text: str) -> str:
    for raw, escaped in reversed(_XML_ESCAPES):
        text = text.replace(escaped, raw)
    return text


def _escape(text: str) -> str:
    for raw, escaped in _XML_ESCAPES:
        text = text.replace(raw, escaped)
    return text


def _graphic_pack_block(lines: list[str]) -> tuple[int, int] | None:
    """``(open line, close line)`` of the one ``<GraphicPack>`` element; ``(i, i)`` when self-closing; else ``None``."""
    opens = [i for i, line in enumerate(lines) if re.match(r"^\s*<GraphicPack\s*/?>\s*$", line)]
    closes = [i for i, line in enumerate(lines) if re.match(r"^\s*</GraphicPack>\s*$", line)]
    if any("<GraphicPack" in line for i, line in enumerate(lines) if i not in opens):
        return None
    if len(opens) != 1:
        return None
    start = opens[0]
    if lines[start].rstrip().endswith("/>"):
        return (start, start) if not closes else None
    if len(closes) != 1 or closes[0] < start:
        return None
    return (start, closes[0])


def pack_entries(settings: str | None) -> dict[str, bool] | None:
    """Every pack ``settings.xml`` names, normalized path → disabled; ``{}`` for no file, ``None`` if not editable."""
    if settings is None:
        return {}
    lines = settings.splitlines()
    block = _graphic_pack_block(lines)
    if block is None:
        return {} if not any("GraphicPack" in line for line in lines) else None
    out: dict[str, bool] = {}
    for line in lines[block[0] + 1 : block[1]]:
        if re.match(r"^\s*<Entry\b", line):
            match = _ENTRY_RE.match(line)
            if match is None:
                return None
            out[normalized(_unescape(match.group(2)))] = bool(_DISABLED_RE.search(match.group(3)))
        elif re.match(r"^\s*<filename>", line):
            return None
    return out


def cemu_packs(
    packs: list[tuple[str, PackInfo]], settings: str | None, title_id: str, *, settings_file: str
) -> ToggleList:
    """The installed packs (``(relative rules.txt path, info)``) that apply to *title_id*, with their state."""
    entries_map = pack_entries(settings)
    editable = entries_map is not None
    reason = None if editable else f"{settings_file} is laid out in a way not edited here; switch packs in Cemu."
    entries = []
    for rel, info in sorted(packs, key=lambda p: p[0].lower()):
        if title_id.upper() not in info.title_ids:
            continue
        disabled = (entries_map or {}).get(normalized(rel))
        enabled = info.default_enabled if disabled is None else not disabled
        entries.append(ToggleEntry(rel, info.name or rel, rel, enabled, editable, "graphicPacks"))
    return ToggleList(tuple(entries), editable, reason)


def cemu_set_pack(settings: str, rel: str, enabled: bool, default_enabled: bool) -> str | None:
    """``settings.xml`` with the pack at *rel* switched; ``None`` when that is not safe.

    An existing entry gains or loses ``disabled="true"``; a missing one is
    added before ``</GraphicPack>`` (with ``disabled="true"`` when switching off
    a pack that is on by default). Line endings and indentation follow the file.
    """
    if pack_entries(settings) is None or '"' in rel or "\n" in rel:
        return None
    lines = settings.splitlines()
    block = _graphic_pack_block(lines)
    if block is None:
        return None
    target = normalized(rel)
    for index in range(block[0] + 1, block[1]):
        match = _ENTRY_RE.match(lines[index])
        if match and normalized(_unescape(match.group(2))) == target:
            attr = "" if enabled else ' disabled="true"'
            lines[index] = f'{match.group(1)}<Entry filename="{match.group(2)}"{attr}{match.group(4)}>'
            return _join(lines, settings)
    if enabled == default_enabled:
        return settings
    open_line = lines[block[0]]
    indent = re.match(r"^(\s*)", open_line)
    outer = indent.group(1) if indent else ""
    inner = outer + ("\t" if "\t" in outer else "    ")
    disabled = "" if enabled else ' disabled="true"'
    entry = f'{inner}<Entry filename="{_escape(rel.replace("/", chr(92)))}"{disabled}/>'
    if block[0] == block[1]:
        lines[block[0] : block[0] + 1] = [f"{outer}<GraphicPack>", entry, f"{outer}</GraphicPack>"]
    else:
        lines.insert(block[1], entry)
    return _join(lines, settings)


def _join(lines: list[str], original: str) -> str:
    newline = "\r\n" if "\r\n" in original else "\n"
    joined = newline.join(lines)
    return joined + newline if original.endswith(("\n", "\r")) else joined
