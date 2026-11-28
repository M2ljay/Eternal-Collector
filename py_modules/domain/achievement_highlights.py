"""Pure rules behind the achievements bridge: which library game an RA game is, and what is closest to complete.

The bridge (``window.__eternalCollectorAchievements``) hands another plugin two
lists — recent unlocks and the games closest to 100% — naming each game by the
ROM and Steam shortcut it is in The Collector. Everything here works on values
the service has already read; nothing reads a clock, the database or the network,
and no RetroAchievements credential ever reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from domain.rom_achievement_progress import RomAchievementProgress

# The most items one bridge answer carries; a request for more is clamped by the bridge.
MAX_BRIDGE_ITEMS: Final = 50


@dataclass(frozen=True, slots=True)
class LibraryRom:
    """The fields of one ROM the bridge needs: its ids, its name and its console."""

    rom_id: int
    app_id: int | None
    name: str
    platform_slug: str
    ra_game_id: int


@dataclass(frozen=True, slots=True)
class Completion:
    """One game's RetroAchievements completion as the bridge reports it."""

    rom: LibraryRom
    earned: int
    total: int
    percent: float


def library_by_ra_game(roms: Iterable[LibraryRom]) -> dict[int, LibraryRom]:
    """One ROM per RetroAchievements game: the one with a Steam shortcut, else the lowest rom id.

    Every version of a game shares one achievement set, so several ROMs can name one
    RA game; the version in Steam is the one another plugin can open.
    """
    chosen: dict[int, LibraryRom] = {}
    for rom in sorted(roms, key=lambda r: r.rom_id):
        current = chosen.get(rom.ra_game_id)
        if current is None or (current.app_id is None and rom.app_id is not None):
            chosen[rom.ra_game_id] = rom
    return chosen


def completion_percent(earned: int, total: int) -> float:
    """``earned / total`` as a percentage rounded to one decimal; 0 for an empty set."""
    if total <= 0:
        return 0.0
    return round(earned * 100 / total, 1)


def closest_to_complete(
    library: Mapping[int, LibraryRom],
    progress: Mapping[int, RomAchievementProgress],
    limit: int,
) -> list[Completion]:
    """The started, unfinished games of *library*, highest completion first, at most *limit*.

    *progress* is the achievement snapshot keyed by rom id. A game at 0% (not started)
    or at 100% (finished) is left out. Ties go to more achievements earned, then the
    name, then the rom id, so the order is stable between reads.
    """
    items: list[Completion] = []
    for rom in library.values():
        record = progress.get(rom.rom_id)
        if record is None or record.earned <= 0 or record.earned >= record.total:
            continue
        items.append(
            Completion(
                rom=rom,
                earned=record.earned,
                total=record.total,
                percent=completion_percent(record.earned, record.total),
            )
        )
    items.sort(key=lambda c: (-c.earned / c.total, -c.earned, c.rom.name.casefold(), c.rom.rom_id))
    return items[: max(0, limit)]
