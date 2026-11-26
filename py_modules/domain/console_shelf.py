"""The console shelf's pure rules: which console counts as most played, which game is "Continue", and badges.

Everything here works on values the service has already read: per-game play time and
last-played instants, the achievement snapshot, and the caller's ``now``. Nothing reads
a clock, the database or the network.

"Most played" is recency-weighted play time: each game's play time counts half as much
for every :data:`HALF_LIFE_DAYS` days since it was last played, so a console binged years
ago sinks below one played this week.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from domain.iso_time import parse_iso_to_epoch

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from domain.rom_achievement_progress import RomAchievementProgress

HALF_LIFE_DAYS = 90.0
_SECONDS_PER_DAY = 86_400.0

AwardKind = Literal["mastered", "completed", "beaten"]


@dataclass(frozen=True, slots=True)
class ShelfGame:
    """One game as the shelf sees it: a bound shortcut with its folded play record."""

    rom_id: int
    app_id: int
    name: str
    platform_slug: str
    play_seconds: int
    last_played: str | None


@dataclass(frozen=True, slots=True)
class ConsoleShelfEntry:
    """One tile: a console with at least one game in Steam."""

    platform_slug: str
    name: str
    game_count: int
    last_played: str | None
    play_seconds: int
    score: float


@dataclass(frozen=True, slots=True)
class AchievementBadge:
    """What a game's RetroAchievements chip shows."""

    earned: int
    total: int
    earned_hardcore: int
    hardcore: bool
    award: AwardKind | None
    fetched_at: str


def recency_weight(last_played: str | None, now_epoch: float) -> float:
    """Weight in ``(0, 1]`` for play time last played at *last_played*.

    Halves every :data:`HALF_LIFE_DAYS` days. An unknown or unparseable instant weighs
    0, so play time nobody can date never lifts a console. A future instant (another
    device's clock ahead of this one) weighs 1.
    """
    played = parse_iso_to_epoch(last_played)
    if played is None:
        return 0.0
    days = max(0.0, (now_epoch - played) / _SECONDS_PER_DAY)
    return 0.5 ** (days / HALF_LIFE_DAYS)


def newest_instant(instants: Iterable[str | None]) -> str | None:
    """The latest parseable ISO-8601 instant of *instants*, as given, or ``None``."""
    best: tuple[float, str] | None = None
    for instant in instants:
        epoch = parse_iso_to_epoch(instant)
        if epoch is not None and instant is not None and (best is None or epoch > best[0]):
            best = (epoch, instant)
    return best[1] if best else None


def rank_consoles(
    games: Iterable[ShelfGame],
    platform_names: Mapping[str, str],
    now_epoch: float,
) -> list[ConsoleShelfEntry]:
    """Group *games* by console and order the tiles most played first.

    Order: score (recency-weighted play seconds) descending; ties by the newest
    last-played instant, then by game count, then by name. Consoles whose score is 0
    come after every played one, by game count then name. The display name falls back
    to the slug when the platform-name cache does not know it.
    """
    grouped: dict[str, list[ShelfGame]] = {}
    for game in games:
        grouped.setdefault(game.platform_slug, []).append(game)

    entries = [
        ConsoleShelfEntry(
            platform_slug=slug,
            name=platform_names.get(slug) or slug,
            game_count=len(members),
            last_played=newest_instant(g.last_played for g in members),
            play_seconds=sum(g.play_seconds for g in members),
            score=sum(g.play_seconds * recency_weight(g.last_played, now_epoch) for g in members),
        )
        for slug, members in grouped.items()
    ]

    def order(entry: ConsoleShelfEntry) -> tuple[bool, float, float, int, str]:
        last = parse_iso_to_epoch(entry.last_played) or 0.0
        return (entry.score <= 0, -entry.score, -last, -entry.game_count, entry.name.casefold())

    return sorted(entries, key=order)


def continue_game(games: Iterable[ShelfGame]) -> ShelfGame | None:
    """The most recently played of *games*, or ``None`` when none has a last-played instant."""
    best: tuple[float, ShelfGame] | None = None
    for game in games:
        epoch = parse_iso_to_epoch(game.last_played)
        if epoch is not None and (best is None or epoch > best[0]):
            best = (epoch, game)
    return best[1] if best else None


def order_console_games(games: Iterable[ShelfGame]) -> list[ShelfGame]:
    """A console page's order: the "Continue" game first, then every other game by name."""
    members = list(games)
    first = continue_game(members)
    rest = sorted(
        (g for g in members if first is None or g.rom_id != first.rom_id),
        key=lambda g: (g.name.casefold(), g.rom_id),
    )
    return [first, *rest] if first is not None else rest


def _award(kind: str | None) -> AwardKind | None:
    if not kind:
        return None
    if kind == "mastered":
        return "mastered"
    if kind == "completed":
        return "completed"
    if kind.startswith("beaten"):
        return "beaten"
    return None


def achievement_badge(progress: RomAchievementProgress | None) -> AchievementBadge | None:
    """The chip for one game's recorded progress, or ``None`` when there is none.

    ``hardcore`` marks a set where every unlock so far was earned in hardcore mode.
    ``award`` reduces RetroAchievements' highest award kind (``mastered``,
    ``completed``, ``beaten-hardcore``, ``beaten-softcore``) to three marks.
    """
    if progress is None:
        return None
    return AchievementBadge(
        earned=progress.earned,
        total=progress.total,
        earned_hardcore=progress.earned_hardcore,
        hardcore=progress.earned > 0 and progress.earned_hardcore == progress.earned,
        award=_award(progress.highest_award_kind),
        fetched_at=progress.fetched_at,
    )
