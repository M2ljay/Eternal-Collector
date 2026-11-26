"""Settings-derived savestate backup knobs, read from the live ``settings.json`` dict.

Config-shaped toggles live in ``settings.json`` (ADR-0003). These pure readers give
every reader in the package one interpretation of the keys; persistence flows
through ``SettingsPersister``.
"""

from __future__ import annotations

from typing import Any

from domain.savestate_names import SCOPE_ALL, SCOPE_AUTO, SCOPES

ENABLED_KEY = "savestate_backup_enabled"
SCOPE_KEY = "savestate_backup_scope"
ENABLED_AT_KEY = "savestate_backup_enabled_at"


def backup_enabled(settings: dict[str, Any]) -> bool:
    """Whether the backup runs: its own toggle, under the save-sync master toggle it sits beneath."""
    return bool(settings.get("save_sync_enabled", False)) and bool(settings.get(ENABLED_KEY, False))


def backup_scope(settings: dict[str, Any]) -> str:
    """``"all"`` only when stored as such; anything else is the auto-state only."""
    return SCOPE_ALL if settings.get(SCOPE_KEY) == SCOPE_ALL else SCOPE_AUTO


def enabled_at(settings: dict[str, Any]) -> float | None:
    """When the backup was last turned on (Unix seconds), or ``None`` if never stamped."""
    raw = settings.get(ENABLED_AT_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def settings_view(settings: dict[str, Any]) -> dict[str, Any]:
    """The frontend-facing pair: the toggle as stored and the scope."""
    return {"enabled": bool(settings.get(ENABLED_KEY, False)), "scope": backup_scope(settings)}


def is_valid_scope(value: object) -> bool:
    """Whether *value* names a backup scope."""
    return value in SCOPES
