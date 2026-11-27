"""Tests for ``SqliteRaGameJournalRepository`` over ``ra_game_journals`` + ``ra_achievement_goals``."""

from __future__ import annotations

import sqlite3

import pytest

from adapters.repositories.unit_of_work import SqliteUnitOfWork
from adapters.sqlite_migrations import apply_migrations
from domain.ra_game_journal import AchievementGoal, RaGameJournal

AT = "2026-11-26T10:00:00+00:00"


def _goal(achievement_id: int, pinned_at: str = AT) -> AchievementGoal:
    return AchievementGoal.pinned(
        achievement_id=achievement_id, title=f"Goal {achievement_id}", description="d", points=5, pinned_at=pinned_at
    )


def _journal(ra_game_id: int = 77) -> RaGameJournal:
    journal = RaGameJournal.opened(ra_game_id=ra_game_id, game_title="Sonic")
    journal.write_notes("spin dash", at=AT)
    journal.pin_goal(_goal(2, "2026-11-26T11:00:00+00:00"))
    journal.pin_goal(_goal(1))
    journal.record_unlock(1, unlocked_at="2026-11-27T00:00:00Z", hardcore=True)
    return journal


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "romm_sync.db")
    apply_migrations(path)
    return path


def test_round_trip_orders_goals_by_pin_time(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.ra_game_journals.save(_journal())
    with SqliteUnitOfWork(db_path) as uow:
        loaded = uow.ra_game_journals.get(77)
        assert loaded is not None
        assert [g.achievement_id for g in loaded.goals] == [1, 2]
        assert loaded.notes == "spin dash"
        assert loaded.goals[0].unlocked_hardcore is True
        assert loaded.goals[1].done is False
        assert uow.ra_game_journals.get(78) is None


def test_save_replaces_goals_and_keeps_the_row(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.ra_game_journals.save(_journal())
    with SqliteUnitOfWork(db_path) as uow:
        journal = uow.ra_game_journals.get(77)
        assert journal is not None
        journal.unpin_goal(2)
        journal.retitle("Sonic 1")
        uow.ra_game_journals.save(journal)
    with SqliteUnitOfWork(db_path) as uow:
        journal = uow.ra_game_journals.get(77)
        assert journal is not None
        assert [g.achievement_id for g in journal.goals] == [1]
        assert journal.game_title == "Sonic 1"


def test_iter_all_and_delete_cascades_goals(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.ra_game_journals.save(_journal(78))
        uow.ra_game_journals.save(_journal(77))
    with SqliteUnitOfWork(db_path) as uow:
        assert [j.ra_game_id for j in uow.ra_game_journals.iter_all()] == [77, 78]
        uow.ra_game_journals.delete(77)
        uow.ra_game_journals.delete(77)
    with SqliteUnitOfWork(db_path) as uow:
        assert [j.ra_game_id for j in uow.ra_game_journals.iter_all()] == [78]
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM ra_achievement_goals WHERE ra_game_id = 77").fetchone()[0] == 0
    finally:
        conn.close()
