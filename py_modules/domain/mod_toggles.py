"""Entries an emulator already has for a game — built-in cheats and patches — and switching one on or off.

Each format here is read the way its emulator reads it, and an edit changes
only the lines that carry the one entry's enabled state, keeping every other
line, the line endings and the order as they were. A file whose layout the
emulator would read differently from this module (a repeated section, a
cheat with no code lines, an entry switched in a file this module does not
write) is reported read-only with the reason, never edited.

- Dolphin Gecko and Action Replay codes (``Source/Core/Core/GeckoCodeConfig.cpp``
  ``LoadCodes`` / ``SaveCodes``, ``ActionReplay.cpp``, ``CheatCodes.h``
  ``ReadEnabledAndDisabled``, ``Common/IniFile.cpp``): codes come from the
  shipped ``Sys/GameSettings`` inis, then the user's ``GameSettings`` inis; a
  code differing from its shipped default is listed by ``$name`` in the
  user's ``[<Section>_Enabled]`` or ``[<Section>_Disabled]``.
- PCSX2 patches and cheats (``pcsx2/Patch.cpp``): labelled ``[name]`` groups of
  a ``.pnach``; the enabled ones are ``Enable = name`` lines of ``[Patches]`` /
  ``[Cheats]`` in the game's settings ini (``INISettingsInterface`` string
  lists, one key repeated). Unlabelled groups are always on.
- Azahar (Citra) cheats (``src/core/cheats/gateway_cheat.cpp``): ``[name]``
  blocks of ``cheats/<TitleID>.txt``, enabled by a ``*citra_enabled`` line.

No I/O. Pure functions only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ORIGIN_BUILTIN = "built-in"
ORIGIN_USER = "user"

_SECTION_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f]")


@dataclass(frozen=True)
class ToggleEntry:
    """One entry the user can see and, when ``can_toggle``, switch.

    ``entry_id`` is what a switch names (the entry's own name in its format);
    ``origin`` says where it comes from — :data:`ORIGIN_BUILTIN`, :data:`ORIGIN_USER`,
    or the file it was read from.
    """

    entry_id: str
    name: str
    description: str
    enabled: bool
    can_toggle: bool
    origin: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToggleList:
    """The entries of one built-in-toggle target, and whether any switch may be written (``reason`` when not)."""

    entries: tuple[ToggleEntry, ...]
    editable: bool
    reason: str | None = None


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _join(lines: list[str], newline: str, original: str | None) -> str:
    joined = newline.join(lines)
    return joined + newline if original is None or original.endswith(("\n", "\r")) or not original else joined


def plain_entry_name(name: str) -> bool:
    """Whether *name* can stand on a line of its own unchanged: no control character, no surrounding space."""
    return bool(name) and not _CONTROL_RE.search(name) and name == name.strip()


# -- Dolphin ---------------------------------------------------------------------

DOLPHIN_GECKO = "Gecko"
DOLPHIN_ACTION_REPLAY = "ActionReplay"


def dolphin_game_ini_names(id6: str, revision: int | None) -> tuple[str, ...]:
    """The game ini file names Dolphin merges for a disc, in load order (``ConfigLoaders::GetGameIniFilenames``)."""
    names = [f"{id6[:1]}.ini", f"{id6[:3]}.ini", f"{id6}.ini"] if len(id6) == 6 else [f"{id6}.ini"]
    if revision is not None:
        names.append(f"{id6}r{revision}.ini")
    return tuple(names)


def dolphin_sections(text: str) -> dict[str, list[str]] | None:
    """Every section's lines, stripped, as Dolphin's ``IniFile`` keeps them; ``None`` when a section header repeats.

    Dolphin itself merges a repeated header into one section; a file with one
    is refused here so an edit can never touch the wrong copy.
    """
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for raw in text.splitlines():
        header = _SECTION_RE.match(raw)
        if header:
            current = header.group(1)
            if current in sections:
                return None
            sections[current] = []
            continue
        sections[current].append(raw.strip())
    return sections


def _dolphin_code_names(lines: list[str], section: str) -> list[tuple[str, bool]]:
    """``(name, enabled-by-prefix)`` of every code a ``[Gecko]`` / ``[ActionReplay]`` section defines, in order."""
    found: list[tuple[str, bool]] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if section == DOLPHIN_GECKO and line.startswith(("+$", "$")):
            plus = line.startswith("+")
            name = line[2:] if plus else line[1:]
            found.append((name.split("[", 1)[0].strip(), plus))
        elif section == DOLPHIN_ACTION_REPLAY and line.startswith("$"):
            found.append((line[1:], False))
    return found


def _dolphin_listed(lines: list[str]) -> set[str]:
    return {line[1:] for line in lines if line.startswith("$")}


def dolphin_codes(
    section: str,
    shipped: list[str | None],
    user: list[tuple[str, str | None]],
    edited_file: str,
) -> ToggleList:
    """The Gecko or Action Replay codes Dolphin would list for a game, with their enabled state.

    *shipped* is the text of each ``Sys/GameSettings`` ini in load order
    (``None`` when absent); *user* pairs each user ``GameSettings`` ini's file
    name with its text, in the same order. *edited_file* is the one user file
    a switch writes (``<ID6>.ini``). Read-only when any ini has a repeated
    section, or when a user file other than *edited_file* enables or disables
    a code (Dolphin merges them, so a switch in one file could be overridden by
    another).
    """
    enabled_key, disabled_key = f"{section}_Enabled", f"{section}_Disabled"
    codes: dict[str, tuple[bool, str]] = {}
    shipped_on: set[str] = set()
    shipped_off: set[str] = set()
    for text in shipped:
        parsed = dolphin_sections(text) if text is not None else {}
        if parsed is None:
            return ToggleList((), False, "A Dolphin Sys game ini repeats a section.")
        for name, plus in _dolphin_code_names(parsed.get(section, []), section):
            codes.setdefault(name, (plus, ORIGIN_BUILTIN))
        shipped_on |= _dolphin_listed(parsed.get(enabled_key, []))
        shipped_off |= _dolphin_listed(parsed.get(disabled_key, []))
    defaults = {name: (plus or name in shipped_on) and name not in shipped_off for name, (plus, _o) in codes.items()}
    user_on: set[str] = set()
    user_off: set[str] = set()
    reason = None
    for file_name, text in user:
        parsed = dolphin_sections(text) if text is not None else {}
        if parsed is None:
            return ToggleList((), False, f"Dolphin's GameSettings\\{file_name} repeats a section.")
        for name, _plus in _dolphin_code_names(parsed.get(section, []), section):
            if name not in codes:
                codes[name] = (False, ORIGIN_USER)
                defaults[name] = False
        on, off = _dolphin_listed(parsed.get(enabled_key, [])), _dolphin_listed(parsed.get(disabled_key, []))
        if (on or off) and file_name != edited_file:
            reason = f"Dolphin's GameSettings\\{file_name} also switches codes; change them in Dolphin."
        user_on |= on
        user_off |= off
    entries = []
    for name, (_plus, origin) in codes.items():
        enabled = (defaults[name] or name in user_on) and name not in user_off
        entries.append(ToggleEntry(name, name, "", enabled, reason is None and plain_entry_name(name), origin))
    return ToggleList(tuple(entries), reason is None, reason)


def dolphin_set_code(text: str | None, section: str, name: str, enabled: bool, default_enabled: bool) -> str | None:
    """The user game ini *text* with code *name* switched, or ``None`` when that cannot be done safely.

    ``$name`` is taken out of both ``[<Section>_Enabled]`` and
    ``[<Section>_Disabled]``, then listed in the one that differs from
    *default_enabled*, as Dolphin's ``SaveCodes`` would. A missing section is
    appended at the end; *text* ``None`` is a file that does not exist yet.
    """
    if not plain_entry_name(name):
        return None
    if text is not None and dolphin_sections(text) is None:
        return None
    newline = _newline(text) if text else "\r\n"
    lines = text.splitlines() if text else []
    wanted = {
        f"{section}_Enabled": enabled and not default_enabled,
        f"{section}_Disabled": default_enabled and not enabled,
    }
    marker = f"${name}"
    for key, add in wanted.items():
        start = next((i for i, line in enumerate(lines) if _section_name(line) == key), None)
        if start is None:
            if add:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend([f"[{key}]", marker])
            continue
        end = next((i for i in range(start + 1, len(lines)) if _section_name(lines[i]) is not None), len(lines))
        body = [line for line in lines[start + 1 : end] if line.strip() != marker]
        if add:
            last = max((i for i, line in enumerate(body) if line.strip()), default=-1)
            body.insert(last + 1, marker)
        lines[start + 1 : end] = body
    return _join(lines, newline, text)


def _section_name(line: str) -> str | None:
    match = _SECTION_RE.match(line)
    return match.group(1) if match else None


# -- PCSX2 -----------------------------------------------------------------------

PCSX2_PATCHES = "Patches"
PCSX2_CHEATS = "Cheats"
PCSX2_ENABLE_KEY = "Enable"
_PCSX2_LIST_KEYS = frozenset({"enable", "disable"})
_PNACH_RE_KEY = re.compile(r"^\s*([^=]*?)\s*=\s*(.*?)\s*$")


def _pnach_line(raw: str) -> str:
    """A ``.pnach`` line as ``Patch::TrimPatchLine`` leaves it: stripped, then cut at ``//`` (not stripped again)."""
    line = raw.strip()
    cut = line.find("//")
    return line[:cut] if cut >= 0 else line


def pnach_groups(text: str) -> tuple[list[tuple[str, str]], bool]:
    """``([(name, description), ...], has_unlabelled)`` of a ``.pnach``, as ``Patch::ExtractPatchInfo`` reads it.

    A group is a ``[name]`` label; ``description`` (or, failing that,
    ``comment``) describes it. Repeated names keep the first. A ``patch`` line
    before any label is an unlabelled patch, which PCSX2 always applies.
    """
    groups: list[tuple[str, str]] = []
    names: set[str] = set()
    name: str | None = None
    description = comment = ""
    unlabelled = False

    def close() -> None:
        if name and name not in names:
            names.add(name)
            groups.append((name, description or comment))

    for raw in text.splitlines():
        line = _pnach_line(raw)
        if not line:
            continue
        if len(line) > 2 and line.startswith("[") and line.endswith("]"):
            close()
            name, description, comment = line[1:-1], "", ""
            continue
        pair = _PNACH_RE_KEY.match(line)
        if pair is None:
            continue
        key, value = pair.group(1), pair.group(2)
        if key == "description":
            description = value
        elif key == "comment" and not comment:
            comment = value
        elif key == "patch" and name is None:
            unlabelled = True
    close()
    return groups, unlabelled


def _pcsx2_lines(text: str) -> list[tuple[str, str, str]] | None:
    """``(kind, section, key-or-value)`` per line of a PCSX2 settings ini, or ``None`` when it is not one we edit.

    Allowed: blank and ``;``/``#`` comment lines, unique section headers,
    ``key = value`` lines with no key repeated in a section except the
    ``Enable`` / ``Disable`` string lists.
    """
    out: list[tuple[str, str, str]] = []
    sections: set[str] = set()
    keys: set[tuple[str, str]] = set()
    section = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        header = _SECTION_RE.match(raw)
        if header:
            section = header.group(1).strip()
            if section.lower() in sections:
                return None
            sections.add(section.lower())
            out.append(("section", section, ""))
        elif not stripped or stripped.startswith((";", "#")):
            out.append(("blank", section, ""))
        elif "=" in stripped:
            key, value = (part.strip() for part in stripped.split("=", 1))
            ident = (section.lower(), key.lower())
            if ident in keys and key.lower() not in _PCSX2_LIST_KEYS:
                return None
            keys.add(ident)
            out.append(("key", section, f"{key}\x00{value}"))
        else:
            return None
    return out


def pcsx2_enabled(text: str | None, section: str) -> set[str] | None:
    """The ``Enable`` items of ``[section]`` in a PCSX2 game settings ini; empty for no file, ``None`` if unreadable."""
    if text is None:
        return set()
    lines = _pcsx2_lines(text)
    if lines is None:
        return None
    enabled = set()
    for kind, sec, pair in lines:
        if kind == "key" and sec.lower() == section.lower():
            key, value = pair.split("\x00", 1)
            if key.lower() == PCSX2_ENABLE_KEY.lower():
                enabled.add(value)
    return enabled


def pcsx2_set_enabled(text: str | None, section: str, name: str, enabled: bool) -> str | None:
    """The game settings ini with ``Enable = name`` present or absent in ``[section]``; ``None`` when not safe.

    Adding puts the line after the section's last key (or a new section at
    the end, or a new file); removing drops every ``Enable`` line equal to
    *name*, as ``RemoveFromStringList`` does.
    """
    if not plain_entry_name(name) or name.startswith((";", "#")):
        return None
    lines_info = _pcsx2_lines(text) if text else []
    if lines_info is None:
        return None
    newline = _newline(text) if text else "\r\n"
    raw = text.splitlines() if text else []
    keep: list[str] = []
    last_in_section: int | None = None
    present = False
    for (kind, sec, pair), line in zip(lines_info, raw, strict=True):
        in_section = sec.lower() == section.lower()
        if kind == "key" and in_section:
            key, value = pair.split("\x00", 1)
            if key.lower() == PCSX2_ENABLE_KEY.lower() and value == name:
                present = True
                if not enabled:
                    continue
        keep.append(line)
        if in_section and kind in ("key", "section"):
            last_in_section = len(keep) - 1
    if enabled and not present:
        new_line = f"{PCSX2_ENABLE_KEY} = {name}"
        if last_in_section is None:
            if keep and keep[-1].strip():
                keep.append("")
            keep.extend([f"[{section}]", new_line])
        else:
            keep.insert(last_in_section + 1, new_line)
    return _join(keep, newline, text)


def pcsx2_entries(
    files: list[tuple[str, str]], enabled: set[str], *, editable: bool, reason: str | None = None
) -> ToggleList:
    """The labelled groups of *files* (``(origin, pnach text)``, in PCSX2's order) with their state; first name wins."""
    entries: list[ToggleEntry] = []
    seen: set[str] = set()
    unlabelled_in: list[str] = []
    for origin, text in files:
        groups, unlabelled = pnach_groups(text)
        if unlabelled:
            unlabelled_in.append(origin)
        for name, description in groups:
            if name in seen:
                continue
            seen.add(name)
            can = editable and plain_entry_name(name) and not name.startswith((";", "#"))
            entries.append(ToggleEntry(name, name, description, name in enabled, can, origin))
    entries.extend(
        ToggleEntry(
            f"unlabelled:{origin}",
            f"Unlabelled patches in {origin}",
            "",
            True,
            False,
            origin,
            ("PCSX2 always applies patch lines that sit before any [name] label.",),
        )
        for origin in unlabelled_in
    )
    return ToggleList(tuple(entries), editable, reason)


# -- Azahar ----------------------------------------------------------------------

AZAHAR_ENABLED_MARKER = "*citra_enabled"


def _azahar_blocks(text: str) -> list[tuple[int, str, bool, int]] | None:
    """``(header line, name, enabled, code lines)`` per cheat, or ``None`` for a file the emulator would misread.

    Refused: a code line before the first header, a header with no code lines
    (Azahar drops it and carries its enabled flag to the next cheat), and a
    name used twice.
    """
    blocks: list[list] = []
    for index, raw in enumerate(text.replace("\x00", "").splitlines()):
        line = raw.strip()
        if len(line) >= 2 and line.startswith("["):
            blocks.append([index, line[1:-1], False, 0])
        elif line == AZAHAR_ENABLED_MARKER:
            if not blocks:
                return None
            blocks[-1][2] = True
        elif line and not line.startswith("*"):
            if not blocks:
                return None
            blocks[-1][3] += 1
    names = [b[1] for b in blocks]
    if any(b[3] == 0 for b in blocks) or len(set(names)) != len(names):
        return None
    return [(b[0], b[1], b[2], b[3]) for b in blocks]


def azahar_cheats(text: str | None, origin: str) -> ToggleList:
    """The cheats of an Azahar cheat file with their state; an absent file has none."""
    if text is None:
        return ToggleList((), True, None)
    blocks = _azahar_blocks(text)
    if blocks is None:
        return ToggleList((), False, f"{origin} has a cheat Azahar would read differently; edit it in Azahar.")
    entries = tuple(ToggleEntry(name, name, "", on, plain_entry_name(name), origin) for _i, name, on, _n in blocks)
    return ToggleList(entries, True, None)


def azahar_set_cheat(text: str, name: str, enabled: bool) -> str | None:
    """The cheat file with ``*citra_enabled`` right after ``[name]`` (or removed from its block); ``None`` if unsafe."""
    blocks = _azahar_blocks(text)
    if blocks is None:
        return None
    block = next((b for b in blocks if b[1] == name), None)
    if block is None:
        return None
    lines = text.splitlines()
    start = block[0]
    end = next((b[0] for b in blocks if b[0] > start), len(lines))
    body = [line for line in lines[start + 1 : end] if line.strip() != AZAHAR_ENABLED_MARKER]
    if enabled:
        body.insert(0, AZAHAR_ENABLED_MARKER)
    lines[start + 1 : end] = body
    return _join(lines, _newline(text), text)
