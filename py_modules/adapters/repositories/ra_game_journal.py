"""SQLite adapter for the ``RaGameJournal`` aggregate over ``ra_game_journals`` + ``ra_achievement_goals``.

One journal row per RetroAchievements game, its goals as child rows. ``save`` UPSERTs
the parent (never ``INSERT OR REPLACE``: the parent is a cascade parent, and a
replace would delete it and its goals first) and then replaces the goal rows inside
the unit of work's open transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.repositories._base import BaseRepository
from domain.ra_game_journal import AchievementGoal, RaGameJournal

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

_JOURNAL_COLUMNS = "ra_game_id, game_title, notes, notes_updated_at"
_GOAL_COLUMNS = "achievement_id, title, description, points, pinned_at, unlocked_at, unlocked_hardcore"


class SqliteRaGameJournalRepository(BaseRepository):
    """The user's goals and notes, one journal per RetroAchievements game."""

    def _goals(self, ra_game_id: int) -> list[AchievementGoal]:
        rows = self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM ra_achievement_goals WHERE ra_game_id = ? ORDER BY pinned_at, achievement_id",
            (ra_game_id,),
        ).fetchall()
        return [
            AchievementGoal(
                achievement_id=row["achievement_id"],
                title=row["title"],
                description=row["description"],
                points=row["points"],
                pinned_at=row["pinned_at"],
                unlocked_at=row["unlocked_at"],
                unlocked_hardcore=self._to_bool(row["unlocked_hardcore"]),
            )
            for row in rows
        ]

    def _row_to_journal(self, row: sqlite3.Row) -> RaGameJournal:
        return RaGameJournal(
            ra_game_id=row["ra_game_id"],
            game_title=row["game_title"],
            notes=row["notes"],
            notes_updated_at=row["notes_updated_at"],
            goals=self._goals(row["ra_game_id"]),
        )

    def get(self, ra_game_id: int) -> RaGameJournal | None:
        row = self._conn.execute(
            f"SELECT {_JOURNAL_COLUMNS} FROM ra_game_journals WHERE ra_game_id = ?",
            (ra_game_id,),
        ).fetchone()
        return self._row_to_journal(row) if row is not None else None

    def iter_all(self) -> Iterator[RaGameJournal]:
        rows = self._conn.execute(f"SELECT {_JOURNAL_COLUMNS} FROM ra_game_journals ORDER BY ra_game_id").fetchall()
        for row in rows:
            yield self._row_to_journal(row)

    def save(self, journal: RaGameJournal) -> None:
        self._conn.execute(
            f"INSERT INTO ra_game_journals ({_JOURNAL_COLUMNS}) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ra_game_id) DO UPDATE SET game_title = excluded.game_title, "
            "notes = excluded.notes, notes_updated_at = excluded.notes_updated_at",
            (journal.ra_game_id, journal.game_title, journal.notes, journal.notes_updated_at),
        )
        self._conn.execute("DELETE FROM ra_achievement_goals WHERE ra_game_id = ?", (journal.ra_game_id,))
        self._conn.executemany(
            f"INSERT INTO ra_achievement_goals (ra_game_id, {_GOAL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    journal.ra_game_id,
                    goal.achievement_id,
                    goal.title,
                    goal.description,
                    goal.points,
                    goal.pinned_at,
                    goal.unlocked_at,
                    int(goal.unlocked_hardcore),
                )
                for goal in journal.goals
            ],
        )

    def delete(self, ra_game_id: int) -> None:
        self._conn.execute("DELETE FROM ra_game_journals WHERE ra_game_id = ?", (ra_game_id,))
