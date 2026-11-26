"""Tests for ``SqliteRomSavestateSyncStateRepository`` over ``rom_savestate_sync_states``."""

from __future__ import annotations

import sqlite3

import pytest

from adapters.repositories.unit_of_work import SqliteUnitOfWork
from domain.rom import Rom
from domain.rom_savestate_sync_state import RomSavestateSyncState


def _rom(rom_id: int) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug="snes",
        name=f"Game {rom_id}",
        fs_name=f"game_{rom_id}.sfc",
        shortcut_app_id=1000 + rom_id,
        last_synced_at="2026-01-01T00:00:00Z",
    )


def _state() -> RomSavestateSyncState:
    state = RomSavestateSyncState()
    state.record_upload(
        "auto",
        local_name="Game.state.auto",
        content_hash="h1",
        uploaded_at="2026-11-26T10:00:00+00:00",
        server_state_id=7,
        server_file_name="Game [aaaa1111].state.auto",
        emulator="snes9x",
        core="snes9x",
        core_version=None,
    )
    state.adopt_baseline("3", local_name="Game.state3", content_hash="h3", observed_at="2026-11-26T09:00:00+00:00")
    return state


class TestRoundTrip:
    def test_saved_state_reads_back_equal(self, uow: SqliteUnitOfWork):
        uow.roms.save(_rom(1))
        state = _state()
        uow.rom_savestate_sync_states.save(1, state)
        assert uow.rom_savestate_sync_states.get(1) == state

    def test_no_rows_reads_none(self, uow: SqliteUnitOfWork):
        assert uow.rom_savestate_sync_states.get(1) is None

    def test_save_replaces_every_slot_of_the_rom_only(self, uow: SqliteUnitOfWork):
        uow.roms.save(_rom(1))
        uow.roms.save(_rom(2))
        uow.rom_savestate_sync_states.save(1, _state())
        uow.rom_savestate_sync_states.save(2, _state())
        smaller = RomSavestateSyncState()
        smaller.adopt_baseline("0", local_name="Game.state", content_hash="h0", observed_at="t")
        uow.rom_savestate_sync_states.save(1, smaller)

        assert uow.rom_savestate_sync_states.get(1) == smaller
        assert uow.rom_savestate_sync_states.get(2) == _state()

    def test_survives_commit(self, db: str):
        with SqliteUnitOfWork(db) as unit:
            unit.roms.save(_rom(1))
            unit.rom_savestate_sync_states.save(1, _state())
        with SqliteUnitOfWork(db) as unit:
            assert unit.rom_savestate_sync_states.get(1) == _state()


class TestForeignKey:
    def test_orphan_row_is_refused(self, db: str):
        with pytest.raises(sqlite3.IntegrityError), SqliteUnitOfWork(db) as unit:
            unit.rom_savestate_sync_states.save(99, _state())

    def test_rom_delete_cascades(self, db: str):
        with SqliteUnitOfWork(db) as unit:
            unit.roms.save(_rom(1))
            unit.rom_savestate_sync_states.save(1, _state())
        with SqliteUnitOfWork(db) as unit:
            unit.roms.delete(1)
        with SqliteUnitOfWork(db) as unit:
            assert unit.rom_savestate_sync_states.get(1) is None
