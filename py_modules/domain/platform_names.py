"""Platform names: the ``platform_slug → display_name`` cache and the names the plugin shows.

The cache is a JSON object stored as a single ``kv_config`` TEXT value, refreshed
each sync so offline reads (DangerZone labels, game-detail platform names, the
Console page) show a human platform name rather than the bare
slug. It holds RomM's own names; the name the plugin shows is RomM's name unless
:data:`PLATFORM_NAME_OVERRIDES` names the slug. Anything that turns the stored
string back into a ``slug → name`` mapping belongs here; reading the value out of
``kv_config`` stays in the service.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

PLATFORM_NAME_OVERRIDES: Final[Mapping[str, str]] = MappingProxyType(
    {
        # RomM calls PS1 "PlayStation" under both its IGDB slug (ps) and its
        # universal slug (psx); the PlayStation console family takes that name.
        "ps": "PlayStation 1",
        "psx": "PlayStation 1",
        # RomM calls the original Xbox "Xbox" (slug xbox, IGDB and universal alike;
        # xbox360, xboxone and series-x-s are other platforms); the Xbox console
        # family takes that name.
        "xbox": "Xbox (Original)",
    }
)
"""Slug → the name the plugin shows instead of RomM's. Matched on the slug, never the name."""


def shown_platform_name(slug: str, romm_name: str) -> str:
    """The name the plugin shows for platform *slug*, which RomM calls *romm_name*."""
    return PLATFORM_NAME_OVERRIDES.get(slug, romm_name)


def shown_platform_names(romm_names: Mapping[str, str]) -> dict[str, str]:
    """*romm_names* (``slug → RomM name``) with every override applied."""
    return {slug: shown_platform_name(slug, name) for slug, name in romm_names.items()}


def platform_renames(romm_names: Mapping[str, str]) -> dict[str, str]:
    """``RomM name → shown name`` for each platform in *romm_names* an override renames.

    A platform's Steam collection was once keyed on RomM's name; this is how its
    ownership record follows the platform to the shown name. Overrides that only
    change case are left out, since collection names fold case.
    """
    renames: dict[str, str] = {}
    for slug, romm_name in romm_names.items():
        shown = shown_platform_name(slug, romm_name)
        if romm_name and shown.casefold() != romm_name.casefold():
            renames[romm_name] = shown
    return renames


def decode_romm_platform_names(raw: str | None) -> dict[str, str]:
    """Decode the cached ``platform_slug → RomM name`` mapping, as RomM names them.

    Returns ``{}`` when *raw* is absent, empty, not valid JSON, or decodes to
    anything other than an object — callers degrade to the slug in every such
    case rather than surfacing a corrupt cache.
    """
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(slug): name for slug, name in decoded.items() if isinstance(name, str)}


def decode_platform_names(raw: str | None) -> dict[str, str]:
    """Decode the cache into the ``platform_slug → name`` mapping the plugin shows.

    RomM's names with :data:`PLATFORM_NAME_OVERRIDES` applied; ``{}`` in every
    case :func:`decode_romm_platform_names` answers ``{}``.
    """
    return shown_platform_names(decode_romm_platform_names(raw))
