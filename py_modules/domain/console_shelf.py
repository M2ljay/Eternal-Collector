"""The console pages' pure rules: which game is "Continue", page order, and achievement badges.

Everything here works on values the service has already read: per-game play time and
last-played instants, and the achievement snapshot. Nothing reads a clock, the
database or the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from domain.iso_time import parse_iso_to_epoch

if TYPE_CHECKING:
    from collections.abc import Iterable

    from domain.rom_achievement_progress import RomAchievementProgress

AwardKind = Literal["mastered", "completed", "beaten"]


@dataclass(frozen=True, slots=True)
class ShelfGame:
    """One game as a console page sees it: a bound shortcut with its folded play record."""

    rom_id: int
    app_id: int
    name: str
    platform_slug: str
    play_seconds: int
    last_played: str | None


@dataclass(frozen=True, slots=True)
class AchievementBadge:
    """What a game's RetroAchievements chip shows."""

    earned: int
    total: int
    earned_hardcore: int
    hardcore: bool
    award: AwardKind | None
    fetched_at: str


def newest_instant(instants: Iterable[str | None]) -> str | None:
    """The latest parseable ISO-8601 instant of *instants*, as given, or ``None``."""
    best: tuple[float, str] | None = None
    for instant in instants:
        epoch = parse_iso_to_epoch(instant)
        if epoch is not None and instant is not None and (best is None or epoch > best[0]):
            best = (epoch, instant)
    return best[1] if best else None


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
