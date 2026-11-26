"""Tests for ``SqliteRomAchievementProgressRepository`` over ``rom_achievement_progress``."""

from __future__ import annotations

import sqlite3

import pytest

from adapters.repositories.unit_of_work import SqliteUnitOfWork
from domain.rom import Rom
from domain.rom_achievement_progress import RomAchievementProgress


def _rom(rom_id: int) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug="snes",
        name=f"Game {rom_id}",
        fs_name=f"game_{rom_id}.sfc",
        shortcut_app_id=1000 + rom_id,
        last_synced_at="2026-01-01T00:00:00Z",
    )


def _progress(earned: int = 3, kind: str | None = "mastered") -> RomAchievementProgress:
    return RomAchievementProgress.observed(
        earned=earned, earned_hardcore=1, total=10, highest_award_kind=kind, fetched_at="2026-11-26T12:00:00+00:00"
    )


class TestRoundTrip:
    def test_replace_all_then_read(self, uow: SqliteUnitOfWork):
        uow.roms.save(_rom(1))
        uow.roms.save(_rom(2))
        uow.rom_achievement_progress.replace_all({2: _progress(kind=None), 1: _progress()})
        assert uow.rom_achievement_progress.get(1) == _progress()
        assert uow.rom_achievement_progress.get(2) == _progress(kind=None)
        assert [rom_id for rom_id, _ in uow.rom_achievement_progress.iter_all()] == [1, 2]

    def test_absent_reads_none(self, uow: SqliteUnitOfWork):
        assert uow.rom_achievement_progress.get(1) is None
        assert list(uow.rom_achievement_progress.iter_all()) == []

    def test_replace_all_drops_rows_not_in_the_new_snapshot(self, uow: SqliteUnitOfWork):
        uow.roms.save(_rom(1))
        uow.roms.save(_rom(2))
        uow.rom_achievement_progress.replace_all({1: _progress(), 2: _progress()})
        uow.rom_achievement_progress.replace_all({2: _progress(earned=7)})
        assert uow.rom_achievement_progress.get(1) is None
        assert uow.rom_achievement_progress.get(2) == _progress(earned=7)
        uow.rom_achievement_progress.replace_all({})
        assert list(uow.rom_achievement_progress.iter_all()) == []


class TestConstraints:
    def test_orphan_row_is_refused(self, db: str):
        with pytest.raises(sqlite3.IntegrityError), SqliteUnitOfWork(db) as unit:
            unit.rom_achievement_progress.replace_all({99: _progress()})

    def test_rom_delete_cascades(self, db: str):
        with SqliteUnitOfWork(db) as unit:
            unit.roms.save(_rom(1))
            unit.rom_achievement_progress.replace_all({1: _progress()})
        with SqliteUnitOfWork(db) as unit:
            unit.roms.delete(1)
        with SqliteUnitOfWork(db) as unit:
            assert unit.rom_achievement_progress.get(1) is None
