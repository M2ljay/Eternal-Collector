"""RPCS3 game patches: the entries its patch lists hold for a game, and switching one in ``patch_config.yml``.

RPCS3 reads its patch lists (``patches\\patch.yml``, ``imported_patch.yml``,
``<SERIAL>_patch.yml``) as ``hash → description → {Games: {title: {serial:
[versions]}}, ...}`` and the user's choices from ``config\\patch_config.yml`` as
``hash → description → title → serial → app version → {Enabled: true}``,
written by ``patch_engine::save_config`` only for entries that are on
(``Utilities/bin_patch.cpp``). A patch applies to the running executable whose
hash keys it; switching it on here writes the same keys RPCS3's own Game Patches
window writes, so no executable hash is computed.

Trees here are the YAML read with every scalar as text (a ``01.00`` stays
``"01.00"``); :func:`config_for_dump` turns ``Enabled`` back into a boolean and
numeric configurable values into numbers before the file is written.

No I/O. Pure functions only.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from domain.mod_toggles import ToggleEntry, ToggleList, plain_entry_name

PATCH_ENGINE_VERSION = "1.2"
_RESERVED = frozenset({"Version", "Anchors"})
_TOP_KEY_RE = re.compile(r"""^(?:"([^"]*)"|'([^']*)'|([^\s#'"\-][^:]*?))\s*:(\s|$)""")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
ALL = "All"
ENABLED = "Enabled"


def patch_list_subset(text: str, serial: str) -> str:
    """The part of a patch list RPCS3 needs for *serial*: ``Version``, ``Anchors`` and the hash blocks naming it.

    The full list is several megabytes; parsing only the blocks whose text
    names the serial keeps a read fast. Anchors are kept whole, so the aliases
    those blocks use still resolve.
    """
    out: list[str] = []
    block: list[str] = []
    keep = False

    def flush() -> None:
        if keep and block:
            out.extend(block)

    for line in text.splitlines():
        top = _TOP_KEY_RE.match(line) if line and not line[0].isspace() else None
        if top is not None:
            flush()
            key = next(g for g in top.groups()[:3] if g is not None)
            block, keep = [line], key in _RESERVED
            continue
        block.append(line)
        if not keep and serial in line:
            keep = True
    flush()
    return "\n".join(out) + "\n"


def entry_id(hash_key: str, description: str, title: str) -> str:
    """A stable id for one (executable, patch, game title): the hash plus a digest of the other two."""
    digest = hashlib.sha256(f"{description}\x00{title}".encode()).hexdigest()[:12]
    return f"{hash_key}:{digest}"


def _versions(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if isinstance(value, str) else []


def _matches(doc: dict[str, Any], serial: str) -> list[tuple[str, str, str, list[str], dict[str, Any]]]:
    """``(hash, description, title, versions, info)`` for every patch of *doc* naming *serial*."""
    found = []
    for hash_key, patches in doc.items():
        if hash_key in _RESERVED or not isinstance(patches, dict):
            continue
        for description, info in patches.items():
            games = info.get("Games") if isinstance(info, dict) else None
            if not isinstance(games, dict):
                continue
            for title, serials in games.items():
                if isinstance(serials, dict) and serial in serials:
                    found.append((hash_key, description, title, _versions(serials[serial]), info))
    return found


def _chosen_version(versions: list[str], app_version: str | None) -> str | None:
    if app_version is not None and app_version in versions:
        return app_version
    return ALL if ALL in versions else None


def _enabled(config: dict[str, Any], key: tuple[str, str, str, str, str]) -> bool:
    node: Any = config
    for part in key:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, dict) and str(node.get(ENABLED, "")).lower() == "true"


def rpcs3_patches(
    docs: list[tuple[str, dict[str, Any]]],
    config: dict[str, Any],
    serial: str,
    app_version: str | None,
    *,
    editable: bool = True,
    reason: str | None = None,
) -> ToggleList:
    """Every patch the lists in *docs* (``(file name, tree)``, RPCS3's load order) hold for *serial*, with its state.

    A patch is switched for the game's own application version, or for
    ``All`` when its list says so; one listed only for other versions is shown
    and cannot be switched. The first list naming a (hash, description) wins,
    as RPCS3's ``append_patches`` keeps the first.
    """
    entries: list[ToggleEntry] = []
    seen: set[str] = set()
    for origin, doc in docs:
        for hash_key, description, title, versions, info in _matches(doc, serial):
            ident = entry_id(hash_key, description, title)
            if ident in seen:
                continue
            seen.add(ident)
            version = _chosen_version(versions, app_version)
            notes = [str(info["Notes"])] if isinstance(info.get("Notes"), str) and info["Notes"] else []
            if version is None:
                shown = app_version or "unknown"
                notes.append(f"Listed for version {', '.join(versions)}; this game is version {shown}.")
            enabled = version is not None and _enabled(config, (hash_key, description, title, serial, version))
            can = editable and version is not None and plain_entry_name(description)
            entries.append(ToggleEntry(ident, description, title, enabled, can, origin, tuple(notes)))
    return ToggleList(tuple(entries), editable, reason)


def rpcs3_target(
    docs: list[tuple[str, dict[str, Any]]], ident: str, serial: str, app_version: str | None
) -> tuple[str, str, str, str] | None:
    """``(hash, description, title, app version key)`` the entry *ident* is switched under, or ``None``."""
    for _origin, doc in docs:
        for hash_key, description, title, versions, _info in _matches(doc, serial):
            if entry_id(hash_key, description, title) == ident:
                version = _chosen_version(versions, app_version)
                return (hash_key, description, title, version) if version is not None else None
    return None


def rpcs3_set(config: dict[str, Any], key: tuple[str, str, str, str, str], enabled: bool) -> dict[str, Any]:
    """A copy of *config* with ``Enabled`` set or removed at *key* (hash, description, title, serial, version).

    Switching off drops ``Enabled`` and every map left empty, as
    ``save_config`` writes only entries that are on or carry their own values.
    """
    out = _deep_copy(config)
    path: list[dict[str, Any]] = [out]
    node: dict[str, Any] = out
    for part in key:
        child = node.get(part)
        if not isinstance(child, dict):
            if not enabled:
                return out
            child = {}
            node[part] = child
        node = child
        path.append(node)
    if enabled:
        node[ENABLED] = "true"
        return out
    node.pop(ENABLED, None)
    for depth in range(len(key), 0, -1):
        if not path[depth]:
            path[depth - 1].pop(key[depth - 1], None)
    return out


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def config_for_dump(config: dict[str, Any]) -> dict[str, Any]:
    """*config* with ``Enabled`` as a boolean and numeric configurable values as numbers, ready to write."""

    def convert(value: Any, key: str | None) -> Any:
        if isinstance(value, dict):
            return {k: convert(v, k) for k, v in value.items()}
        if key == ENABLED:
            return str(value).lower() == "true"
        if isinstance(value, str) and _NUMBER_RE.match(value):
            return float(value) if "." in value else int(value)
        return value

    return convert(config, None)


def config_is_tree(config: Any) -> bool:
    """Whether a parsed ``patch_config.yml`` has the shape RPCS3 writes (an empty file is an empty map)."""
    return config is None or isinstance(config, dict)
