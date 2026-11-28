"""Pure rules for what The Collector takes from, and links to on, RetroAchievements.org.

What belongs here: the public page addresses the plugin links out to, which guide
addresses it is willing to open, turning RetroAchievements' date strings into
ISO-8601 instants, and reducing RetroAchievements Web API answers to the plain
shapes the services keep. Fetching is ``adapters/retroachievements_web.py``'s job;
the Web API key never reaches anything here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlsplit

RA_SITE: Final = "https://retroachievements.org"
RA_MEDIA: Final = "https://media.retroachievements.org"

# The windows the unlock timeline offers, in days.
TIMELINE_RANGES_DAYS: Final[tuple[int, ...]] = (30, 90, 365)

# Hosts a game's guide link may point at. RetroAchievements' own guides live in the
# RetroAchievements organisation on GitHub (the GuideURL field of
# API_GetGameInfoAndUserProgress); anything else is not opened.
_GUIDE_HOSTS: Final = frozenset({"retroachievements.org", "www.retroachievements.org", "docs.retroachievements.org"})
_GITHUB_HOSTS: Final = frozenset({"github.com", "www.github.com"})
_GITHUB_GUIDE_PREFIX: Final = "/retroachievements/"


def achievement_page_url(achievement_id: int) -> str:
    """The public RetroAchievements page of one achievement (comments and tips live there)."""
    return f"{RA_SITE}/achievement/{int(achievement_id)}"


def game_page_url(game_id: int) -> str:
    """The public RetroAchievements page of one game."""
    return f"{RA_SITE}/game/{int(game_id)}"


def safe_guide_url(raw: object) -> str | None:
    """Return *raw* when it is an https guide link on RetroAchievements' own sites, else ``None``.

    Accepted: ``retroachievements.org`` (and its ``www`` / ``docs`` hosts), or a page in
    the RetroAchievements organisation on GitHub. No user info, no port.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or port is not None:
        return None
    if host in _GUIDE_HOSTS:
        return raw.strip()
    if host in _GITHUB_HOSTS and parts.path.lower().startswith(_GITHUB_GUIDE_PREFIX):
        return raw.strip()
    return None


_MEDIA_HOST: Final = "media.retroachievements.org"


def public_badge_url(raw: object) -> str | None:
    """Return *raw* when it is a plain https image URL on RetroAchievements' media host, else ``None``.

    Plain means no user info, no port, no query and no fragment, so the URL cannot carry
    a credential or point anywhere but the public badge file.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or (parts.hostname or "").lower() != _MEDIA_HOST:
        return None
    if parts.username or parts.password or port is not None or parts.query or parts.fragment:
        return None
    if not parts.path.startswith("/") or "?" in raw or "#" in raw:
        return None
    return raw


def normalize_ra_date(value: object) -> str | None:
    """Turn a RetroAchievements or RomM date into ``YYYY-MM-DDTHH:MM:SSZ``, or ``None``.

    RetroAchievements writes ``"2022-01-01 22:41:48"`` in UTC with no zone; an ISO-8601
    string with a ``Z`` or an offset is converted to UTC. Anything else is ``None``.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        number = int(value)
        return number if number > 0 else None
    return None


def _as_points(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _as_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip() in ("1", "true", "True")
    return False


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _media_url(path: object) -> str:
    text = _text(path)
    if not text.startswith("/") or text.startswith("//"):
        return ""
    return RA_MEDIA + text


def _field(entry: dict[str, Any], pascal: str, camel: str) -> object:
    return entry[pascal] if pascal in entry else entry.get(camel)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One unlock as the timeline shows it."""

    unlocked_at: str
    achievement_id: int
    title: str
    description: str
    points: int
    hardcore: bool
    game_id: int
    game_title: str
    console_name: str
    badge_url: str

    def to_wire(self) -> dict[str, Any]:
        """The JSON shape the frontend reads."""
        return {
            "unlocked_at": self.unlocked_at,
            "achievement_id": self.achievement_id,
            "title": self.title,
            "description": self.description,
            "points": self.points,
            "hardcore": self.hardcore,
            "game_id": self.game_id,
            "game_title": self.game_title,
            "console_name": self.console_name,
            "badge_url": self.badge_url,
        }


def parse_timeline(payload: object) -> list[TimelineEntry]:
    """Reduce an ``API_GetAchievementsEarnedBetween`` answer to timeline entries, newest first.

    Accepts the PascalCase keys the Web API sends and the camelCase ones its client
    library uses. An entry without a date, an achievement id, a game id or a title is
    dropped rather than shown half-empty. An achievement unlocked both ways appears once,
    as its hardcore unlock when there is one.
    """
    entries: dict[int, TimelineEntry] = {}
    for raw in payload if isinstance(payload, list) else []:
        if not isinstance(raw, dict):
            continue
        unlocked_at = normalize_ra_date(_field(raw, "Date", "date"))
        achievement_id = _as_id(_field(raw, "AchievementID", "achievementId"))
        game_id = _as_id(_field(raw, "GameID", "gameId"))
        title = _text(_field(raw, "Title", "title"))
        if unlocked_at is None or achievement_id is None or game_id is None or not title:
            continue
        entry = TimelineEntry(
            unlocked_at=unlocked_at,
            achievement_id=achievement_id,
            title=title,
            description=_text(_field(raw, "Description", "description")),
            points=_as_points(_field(raw, "Points", "points")),
            hardcore=_as_flag(_field(raw, "HardcoreMode", "hardcoreMode")),
            game_id=game_id,
            game_title=_text(_field(raw, "GameTitle", "gameTitle")),
            console_name=_text(_field(raw, "ConsoleName", "consoleName")),
            badge_url=_media_url(_field(raw, "BadgeURL", "badgeUrl")),
        )
        previous = entries.get(achievement_id)
        if previous is None or (entry.hardcore and not previous.hardcore):
            entries[achievement_id] = entry
    return sorted(entries.values(), key=lambda e: (e.unlocked_at, e.achievement_id), reverse=True)


@dataclass(frozen=True, slots=True)
class GameUnlock:
    """One unlocked achievement of one game: when, and whether in hardcore."""

    achievement_id: int
    unlocked_at: str
    hardcore: bool


@dataclass(frozen=True, slots=True)
class GameProgress:
    """What ``API_GetGameInfoAndUserProgress`` says about one game for one user."""

    unlocks: tuple[GameUnlock, ...]
    guide_url: str | None


def parse_game_progress(payload: object) -> GameProgress:
    """Reduce an ``API_GetGameInfoAndUserProgress`` answer to its unlocks and guide link.

    An achievement's hardcore date wins over its softcore one. The guide link passes
    :func:`safe_guide_url` or is dropped.
    """
    if not isinstance(payload, dict):
        return GameProgress(unlocks=(), guide_url=None)
    achievements = _field(payload, "Achievements", "achievements")
    items = achievements.values() if isinstance(achievements, dict) else []
    unlocks: list[GameUnlock] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        achievement_id = _as_id(_field(raw, "ID", "id"))
        if achievement_id is None:
            continue
        hardcore_at = normalize_ra_date(_field(raw, "DateEarnedHardcore", "dateEarnedHardcore"))
        softcore_at = normalize_ra_date(_field(raw, "DateEarned", "dateEarned"))
        if hardcore_at is not None:
            unlocks.append(GameUnlock(achievement_id=achievement_id, unlocked_at=hardcore_at, hardcore=True))
        elif softcore_at is not None:
            unlocks.append(GameUnlock(achievement_id=achievement_id, unlocked_at=softcore_at, hardcore=False))
    unlocks.sort(key=lambda u: u.achievement_id)
    return GameProgress(unlocks=tuple(unlocks), guide_url=safe_guide_url(_field(payload, "GuideURL", "guideUrl")))


def web_api_failure(status_code: int | None) -> tuple[str, str]:
    """Return ``(reason, message)`` for a failed RetroAchievements Web API request.

    401/403 mean the key (or the username it was used with) was refused; 404 that the
    username is unknown; 429 that RetroAchievements is rate-limiting; anything else,
    including no answer at all, that it could not be reached.
    """
    if status_code in (401, 403):
        return "auth_failed", "RetroAchievements refused the Web API key. Check the key and username in Settings."
    if status_code == 404:
        return "not_found", "RetroAchievements has no user with that username."
    if status_code == 429:
        return "rate_limited", "RetroAchievements is limiting requests. Try again in a minute."
    return "server_unreachable", "RetroAchievements could not be reached. Check your connection."
