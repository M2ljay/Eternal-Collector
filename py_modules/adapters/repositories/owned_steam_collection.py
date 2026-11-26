"""SQLite adapter for the ``OwnedSteamCollection`` aggregate over ``owned_steam_collections``.

One row per Steam collection the plugin owns, keyed by Steam's collection id, with
at most one row per ``(family, source_key)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.repositories._base import BaseRepository
from domain.owned_steam_collection import OwnedSteamCollection

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

_COLUMNS = "collection_id, family, source_name, display_name, yielded_to"


def _row_to_record(row: sqlite3.Row) -> OwnedSteamCollection:
    return OwnedSteamCollection(
        collection_id=row["collection_id"],
        family=row["family"],
        source_name=row["source_name"],
        display_name=row["display_name"],
        yielded_to=row["yielded_to"],
    )


class SqliteOwnedSteamCollectionRepository(BaseRepository):
    """The plugin's own Steam collections on this device."""

    def get(self, collection_id: str) -> OwnedSteamCollection | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM owned_steam_collections WHERE collection_id = ?",
            (collection_id,),
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def iter_all(self) -> Iterator[OwnedSteamCollection]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM owned_steam_collections ORDER BY family, source_key"
        ).fetchall()
        for row in rows:
            yield _row_to_record(row)

    def save(self, record: OwnedSteamCollection) -> None:
        self._conn.execute(
            "DELETE FROM owned_steam_collections WHERE family = ? AND source_key = ? AND collection_id != ?",
            (record.family, record.source_key, record.collection_id),
        )
        self._conn.execute(
            f"INSERT OR REPLACE INTO owned_steam_collections ({_COLUMNS}, source_key) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.collection_id,
                record.family,
                record.source_name,
                record.display_name,
                record.yielded_to,
                record.source_key,
            ),
        )

    def delete(self, collection_id: str) -> None:
        self._conn.execute("DELETE FROM owned_steam_collections WHERE collection_id = ?", (collection_id,))
