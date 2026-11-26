"""SQLite adapter for the ``RomAchievementProgress`` aggregate over ``rom_achievement_progress``.

One row per ROM; ``replace_all`` swaps the whole snapshot inside the unit of work's
open transaction, so readers see either the previous answer or the new one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.repositories._base import BaseRepository
from domain.rom_achievement_progress import RomAchievementProgress

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

_COLUMNS = "rom_id, earned, earned_hardcore, total, highest_award_kind, fetched_at"


def _row_to_progress(row: sqlite3.Row) -> RomAchievementProgress:
    return RomAchievementProgress(
        earned=row["earned"],
        earned_hardcore=row["earned_hardcore"],
        total=row["total"],
        highest_award_kind=row["highest_award_kind"],
        fetched_at=row["fetched_at"],
    )


class SqliteRomAchievementProgressRepository(BaseRepository):
    """The achievement snapshot, one row per ROM with progress."""

    def get(self, rom_id: int) -> RomAchievementProgress | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM rom_achievement_progress WHERE rom_id = ?",
            (rom_id,),
        ).fetchone()
        return _row_to_progress(row) if row is not None else None

    def iter_all(self) -> Iterator[tuple[int, RomAchievementProgress]]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM rom_achievement_progress ORDER BY rom_id").fetchall()
        for row in rows:
            yield (row["rom_id"], _row_to_progress(row))

    def replace_all(self, snapshot: dict[int, RomAchievementProgress]) -> None:
        self._conn.execute("DELETE FROM rom_achievement_progress")
        self._conn.executemany(
            f"INSERT INTO rom_achievement_progress ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (rom_id, p.earned, p.earned_hardcore, p.total, p.highest_award_kind, p.fetched_at)
                for rom_id, p in sorted(snapshot.items())
            ],
        )
