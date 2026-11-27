"""The "now playing" record other plugins read while a ROM runs.

While a RomM game launched through its Steam shortcut is running, the plugin
publishes one record per running app: the ROM's name, its console, when the
session started, the shortcut's app id and, when one is safe to show, a cover
URL. Assemble (the Discord plugin) turns it into Rich Presence; any other reader
may use it. The contract is versioned (``v``) and documented in
``docs/architecture/now-playing-presence.md``.

The record leaves the plugin, so nothing in it may point at the RomM server: the
cover is only ever a public metadata-provider URL (``public_cover_url``), never
a RomM asset path, and never a URL carrying a query (ScreenScraper puts its
account credentials there). Pure compute — reading the ROM, fetching the cover
URL and writing the file belong to ``services/now_playing.py`` and its adapter.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
SOURCE = "collector"
MAX_TEXT = 128
MAX_URL = 512

# The public image CDNs of the metadata providers RomM fetches covers from.
PUBLIC_COVER_HOSTS = frozenset(
    {
        "images.igdb.com",
        "cdn2.steamgriddb.com",
        "cdn.steamgriddb.com",
        "cdn.mobygames.com",
        "images.launchbox-app.com",
        "media.retroachievements.org",
    }
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def display_text(value: object) -> str:
    """*value* as a single-line display string of at most ``MAX_TEXT`` characters.

    Control characters (a newline included) become spaces; anything that is not
    a string, or is blank, is ``""``.
    """
    if not isinstance(value, str):
        return ""
    return " ".join(_CONTROL.sub(" ", value).split())[:MAX_TEXT]


def public_cover_url(url: object) -> str | None:
    """*url* when it may be shown publicly, else ``None``.

    Accepted: ``https``, a host in ``PUBLIC_COVER_HOSTS``, a non-empty path, and
    no user info, port, query or fragment.
    """
    if not isinstance(url, str) or len(url) > MAX_URL or _CONTROL.search(url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or port is not None or parts.username or parts.password:
        return None
    if (parts.hostname or "") not in PUBLIC_COVER_HOSTS or parts.query or parts.fragment:
        return None
    if parts.path in ("", "/"):
        return None
    return url


def build_record(
    *,
    app_id: int,
    rom_id: int,
    name: str,
    platform: str,
    started_at_ms: int,
    cover_url: str | None = None,
) -> dict[str, Any]:
    """One running ROM's record. ``started_at_ms`` is Unix time in milliseconds."""
    return {
        "app_id": int(app_id),
        "rom_id": int(rom_id),
        "name": display_text(name),
        "platform": display_text(platform),
        "started_at": int(started_at_ms),
        "cover_url": public_cover_url(cover_url),
    }


def empty_document() -> dict[str, Any]:
    """A document with no running ROM."""
    return {"v": SCHEMA_VERSION, "source": SOURCE, "records": {}}


def normalize_document(raw: object) -> dict[str, Any]:
    """*raw* as a current-version document; anything else reads as empty.

    Records are keyed by the app id as a string; an entry whose key does not
    match its own ``app_id`` is dropped.
    """
    doc = empty_document()
    if not isinstance(raw, dict) or raw.get("v") != SCHEMA_VERSION or not isinstance(raw.get("records"), dict):
        return doc
    for key, record in raw["records"].items():
        if isinstance(record, dict) and str(record.get("app_id")) == key:
            doc["records"][key] = dict(record)
    return doc


def with_record(raw: object, record: dict[str, Any]) -> dict[str, Any]:
    """A copy of document *raw* holding *record*, replacing its app's earlier one."""
    doc = normalize_document(raw)
    doc["records"][str(record["app_id"])] = dict(record)
    return doc


def without_record(raw: object, app_id: int) -> dict[str, Any]:
    """A copy of document *raw* without *app_id*'s record."""
    doc = normalize_document(raw)
    doc["records"].pop(str(app_id), None)
    return doc


def record_for(raw: object, app_id: int) -> dict[str, Any] | None:
    """*app_id*'s record in document *raw*, or ``None``."""
    return normalize_document(raw)["records"].get(str(app_id))
