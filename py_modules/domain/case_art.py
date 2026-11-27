"""Pure rules for "game case" cover art from SteamGridDB.

Owns the stateless compute behind the Game case cover style: the setting's
vocabulary, the ``/grids`` query that asks SteamGridDB for portrait and square
grids, the ranking that picks one grid per ROM, the letterbox geometry that fits
any grid into Steam's 2:3 portrait capsule without stretching it, and the parse
of the curated author list (``defaults/case_art_authors.json``) and of the
per-ROM sidecar the service keeps beside the cached case image.

SteamGridDB has no "case" style or tag a query could filter on, so a case grid
is recognised by who made it (the curated list) and by its shape (how close its
aspect is to the platform's real case front). Everything here is a pure
function; the service owns every request and file.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any, Final

COVER_STYLE_SETTING: Final = "cover_style"
COVER_STYLE_CASE: Final = "case"
COVER_STYLE_PLAIN: Final = "plain"
COVER_STYLES: Final = (COVER_STYLE_CASE, COVER_STYLE_PLAIN)

# Steam's portrait library capsule. A case image is letterboxed into this box.
CAPSULE_WIDTH: Final = 600
CAPSULE_HEIGHT: Final = 900

# The portrait sizes SteamGridDB accepts for grids, plus its square sizes (a DS
# or jewel-case front is close to square). The landscape sizes are the wide
# capsule, which the plugin already fetches separately.
CASE_GRID_DIMENSIONS: Final = ("600x900", "342x482", "660x930", "512x512", "1024x1024")

# The front of each platform's retail case, width / height, keyed by RomM
# platform slug. Approximate retail measurements; a platform not listed is
# ranked against Steam's own 2:3.
_DVD: Final = 135 / 190
_JEWEL: Final = 1.0
CASE_ASPECT: Final[dict[str, float]] = {
    "ps2": _DVD,
    "ps3": _DVD,
    "xbox": _DVD,
    "xbox360": _DVD,
    "wii": _DVD,
    "wiiu": _DVD,
    "ngc": 136 / 188,
    "gamecube": 136 / 188,
    "psp": 104 / 180,
    "psvita": 104 / 170,
    "switch": 105 / 170,
    "nds": 125 / 137,
    "3ds": 125 / 137,
    "n3ds": 125 / 137,
    "psx": _JEWEL,
    "ps": _JEWEL,
    "saturn": _JEWEL,
    "segacd": _JEWEL,
    "dc": _JEWEL,
    "dreamcast": _JEWEL,
    "3do": _JEWEL,
    "gb": _JEWEL,
    "gbc": _JEWEL,
    "gba": _JEWEL,
    "genesis-slash-megadrive": 130 / 185,
    "nes": 127 / 178,
}
_DEFAULT_ASPECT: Final = CAPSULE_WIDTH / CAPSULE_HEIGHT

# Aspect distances closer than this are treated as equal, so score decides
# between 342x482 and 660x930 (both about 0.71).
_ASPECT_STEP: Final = 0.02

# MIME types a static image can carry; an animated grid (APNG / animated WebP)
# is asked away by ``types=static`` and rejected here if it slips through.
_STATIC_MIMES: Final = frozenset({"image/png", "image/jpeg", "image/webp"})


def cover_style(settings: dict[str, Any]) -> str:
    """Return the configured cover style; anything unrecognised reads as Game case."""
    value = settings.get(COVER_STYLE_SETTING)
    return value if value in COVER_STYLES else COVER_STYLE_CASE


_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def case_art_filenames(rom_id: int | str) -> tuple[str, str, str]:
    """``(image, sidecar, source)`` cache filenames of a ROM's case art.

    The image is the letterboxed 2:3 PNG; the source is the raw SGDB grid held
    only between download and the letterboxed save.
    """
    return (f"{rom_id}_case.png", f"{rom_id}_case.json", f"{rom_id}_case_source.img")


def png_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG's IHDR chunk, or ``None`` when *data* is not a PNG."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height)


def case_grids_path(sgdb_game_id: int) -> str:
    """The SGDB ``/grids`` path for a game's portrait and square static grids.

    ``nsfw=false`` and ``humor=false`` are SteamGridDB's own filters; the ranking
    drops any grid still flagged either way.
    """
    dims = ",".join(CASE_GRID_DIMENSIONS)
    return f"/grids/game/{int(sgdb_game_id)}?dimensions={dims}&types=static&nsfw=false&humor=false"


@dataclass(frozen=True, slots=True)
class CaseAuthor:
    """One curated case-template author: matched by Steam id, else by name."""

    name: str
    steam64: str | None


@dataclass(frozen=True, slots=True)
class CaseGrid:
    """One SGDB grid that may stand as a ROM's case cover."""

    grid_id: int
    url: str
    thumb: str
    width: int
    height: int
    score: int
    author: str
    curated: bool


def parse_case_authors(raw: bytes | str | None) -> dict[str, tuple[CaseAuthor, ...]]:
    """Parse ``case_art_authors.json`` into ``platform slug → authors``.

    Shape: ``{"platforms": {"<slug>": [{"name": str, "steam64": str|null}, ...]}}``;
    the slug ``"*"`` applies to every platform. Keys starting with ``_`` are
    comments. A missing or malformed file, or a malformed entry, is skipped:
    the list only ever adds preference, so losing it never blocks case art.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    platforms = data.get("platforms") if isinstance(data, dict) else None
    if not isinstance(platforms, dict):
        return {}
    out: dict[str, tuple[CaseAuthor, ...]] = {}
    for slug, entries in platforms.items():
        if not isinstance(slug, str) or slug.startswith("_") or not isinstance(entries, list):
            continue
        authors = tuple(a for a in (_parse_author(e) for e in entries) if a is not None)
        if authors:
            out[slug] = authors
    return out


def _parse_author(entry: object) -> CaseAuthor | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    steam64 = entry.get("steam64")
    name = name.strip() if isinstance(name, str) else ""
    steam64 = steam64.strip() if isinstance(steam64, str) and steam64.strip() else None
    if not name and steam64 is None:
        return None
    return CaseAuthor(name=name, steam64=steam64)


def _is_curated(author: dict[str, Any], curated: tuple[CaseAuthor, ...]) -> bool:
    name = str(author.get("name") or "").strip().casefold()
    steam64 = str(author.get("steam64") or "").strip()
    for entry in curated:
        if entry.steam64 is not None and entry.steam64 == steam64:
            return True
        if entry.name and entry.name.casefold() == name:
            return True
    return False


def _to_grid(entry: object, curated: tuple[CaseAuthor, ...]) -> CaseGrid | None:
    """A usable grid from one SGDB entry, or ``None`` (NSFW, humor, animated, malformed)."""
    if not isinstance(entry, dict):
        return None
    if entry.get("nsfw") is not False or entry.get("humor") is True:
        return None
    mime = entry.get("mime")
    if mime is not None and mime not in _STATIC_MIMES:
        return None
    grid_id, url, width, height = entry.get("id"), entry.get("url"), entry.get("width"), entry.get("height")
    if not isinstance(grid_id, int) or not isinstance(url, str) or not url:
        return None
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return None
    raw_author = entry.get("author")
    author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    thumb = entry.get("thumb")
    score = entry.get("score")
    return CaseGrid(
        grid_id=grid_id,
        url=url,
        thumb=thumb if isinstance(thumb, str) and thumb else url,
        width=width,
        height=height,
        score=score if isinstance(score, int) and not isinstance(score, bool) else 0,
        author=str(author.get("name") or ""),
        curated=_is_curated(author, curated),
    )


def aspect_distance(width: int, height: int, platform_slug: str) -> float:
    """How far a grid's shape is from the platform's case front (0 is a match)."""
    ratio = width / height
    target = CASE_ASPECT.get(platform_slug, _DEFAULT_ASPECT)
    return max(ratio / target, target / ratio) - 1.0


def rank_case_grids(
    payload: dict[str, Any] | None,
    platform_slug: str,
    authors: dict[str, tuple[CaseAuthor, ...]],
) -> list[CaseGrid]:
    """Order a ``/grids`` response best case cover first.

    1. grids by a curated case-template author for this platform (or ``"*"``);
    2. then the shape closest to the platform's real case front;
    3. then the higher SGDB score; the grid id breaks ties so the order is stable.

    NSFW grids are never returned, nor humor or animated ones. A failed or empty
    payload yields ``[]`` — the caller keeps the plain cover.
    """
    if not payload or not payload.get("success"):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    curated = authors.get(platform_slug, ()) + authors.get("*", ())
    grids = [g for g in (_to_grid(e, curated) for e in data) if g is not None]

    def key(g: CaseGrid) -> tuple[int, int, int, int]:
        bucket = round(aspect_distance(g.width, g.height, platform_slug) / _ASPECT_STEP)
        return (0 if g.curated else 1, bucket, -g.score, g.grid_id)

    return sorted(grids, key=key)


def letterbox_rect(
    width: int, height: int, box_width: int = CAPSULE_WIDTH, box_height: int = CAPSULE_HEIGHT
) -> tuple[int, int, int, int]:
    """Fit ``width x height`` inside the box keeping its aspect: ``(x, y, w, h)``.

    The image is scaled until one side meets the box and centred on the other;
    the rest of the box is the black letterbox. Never stretches. The frontend
    draws with the same rule (``src/utils/caseArt.ts``).
    """
    if width <= 0 or height <= 0:
        raise ValueError("image size must be positive")
    scale = min(box_width / width, box_height / height)
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return ((box_width - w) // 2, (box_height - h) // 2, w, h)


@dataclass(frozen=True, slots=True)
class CaseSidecar:
    """What the service records beside a cached case image.

    ``grid_id`` is the SGDB grid the image came from; ``manual`` is ``True`` when
    the user chose it, so an automatic pass never replaces it; ``published`` is
    the cover style last put on the Steam tile (``"case"`` / ``"plain"``), which
    lets a sync re-apply covers after the setting changes.
    """

    grid_id: int
    manual: bool
    published: str


def parse_case_sidecar(raw: bytes | str | None) -> CaseSidecar | None:
    """Parse a ``{rom_id}_case.json`` sidecar; a missing or malformed one is ``None``."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("grid_id"), int):
        return None
    published = data.get("published")
    return CaseSidecar(
        grid_id=data["grid_id"],
        manual=data.get("manual") is True,
        published=published if published in COVER_STYLES else COVER_STYLE_CASE,
    )


def dump_case_sidecar(sidecar: CaseSidecar) -> str:
    """Serialise a sidecar for the atomic write."""
    return json.dumps({"grid_id": sidecar.grid_id, "manual": sidecar.manual, "published": sidecar.published})
