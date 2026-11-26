"""Tests for ``SqliteOwnedSteamCollectionRepository`` over ``owned_steam_collections``."""

from __future__ import annotations

import pytest

from adapters.repositories.unit_of_work import SqliteUnitOfWork
from adapters.sqlite_migrations import apply_migrations
from domain.owned_steam_collection import OwnedSteamCollection


def _record(collection_id: str, source: str, *, family: str = "platform", name: str | None = None, yielded_to=None):
    return OwnedSteamCollection.claim(
        collection_id=collection_id,
        family=family,
        source_name=source,
        display_name=name or source,
        yielded_to=yielded_to,
    )


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "romm_sync.db")
    apply_migrations(path)
    return path


def test_round_trip(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(
            _record("uc-1", "PlayStation 2", name="PlayStation 2 (RomM)", yielded_to="PlayStation 2")
        )
    with SqliteUnitOfWork(db_path) as uow:
        assert uow.owned_steam_collections.get("uc-1") == _record(
            "uc-1", "PlayStation 2", name="PlayStation 2 (RomM)", yielded_to="PlayStation 2"
        )
        assert uow.owned_steam_collections.get("uc-unknown") is None


def test_iter_all_orders_by_family_then_source(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(_record("uc-3", "Favourites", family="romm"))
        uow.owned_steam_collections.save(_record("uc-2", "Super Nintendo"))
        uow.owned_steam_collections.save(_record("uc-1", "Nintendo 64"))
    with SqliteUnitOfWork(db_path) as uow:
        assert [r.collection_id for r in uow.owned_steam_collections.iter_all()] == ["uc-1", "uc-2", "uc-3"]


def test_recording_a_source_against_a_new_collection_replaces_the_old_record(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(_record("uc-old", "Nintendo 64"))
        uow.owned_steam_collections.save(_record("uc-new", "NINTENDO 64"))
    with SqliteUnitOfWork(db_path) as uow:
        assert [r.collection_id for r in uow.owned_steam_collections.iter_all()] == ["uc-new"]


def test_the_same_name_in_two_families_is_two_records(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(_record("uc-1", "Arcade"))
        uow.owned_steam_collections.save(_record("uc-2", "Arcade", family="romm", name="Arcade (RomM)"))
    with SqliteUnitOfWork(db_path) as uow:
        assert len(list(uow.owned_steam_collections.iter_all())) == 2


def test_resaving_a_record_renames_it_in_place(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(_record("uc-1", "Nintendo 64", name="RomM: Nintendo 64 (htpc)"))
        uow.owned_steam_collections.save(_record("uc-1", "Nintendo 64"))
    with SqliteUnitOfWork(db_path) as uow:
        record = uow.owned_steam_collections.get("uc-1")
        assert record is not None
        assert record.display_name == "Nintendo 64"


def test_delete_is_idempotent(db_path):
    with SqliteUnitOfWork(db_path) as uow:
        uow.owned_steam_collections.save(_record("uc-1", "Nintendo 64"))
        uow.owned_steam_collections.delete("uc-1")
        uow.owned_steam_collections.delete("uc-1")
    with SqliteUnitOfWork(db_path) as uow:
        assert list(uow.owned_steam_collections.iter_all()) == []
