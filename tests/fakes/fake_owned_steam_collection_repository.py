"""In-memory ``OwnedSteamCollectionRepository`` implementation for service tests."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain.owned_steam_collection import OwnedSteamCollection


class FakeOwnedSteamCollectionRepository:
    """Dict-backed ``OwnedSteamCollectionRepository`` keyed by Steam collection id."""

    def __init__(self) -> None:
        self._records: dict[str, OwnedSteamCollection] = {}

    def get(self, collection_id: str) -> OwnedSteamCollection | None:
        return copy.deepcopy(self._records.get(collection_id))

    def iter_all(self) -> Iterator[OwnedSteamCollection]:
        for record in sorted(self._records.values(), key=lambda r: (r.family, r.source_key)):
            yield copy.deepcopy(record)

    def save(self, record: OwnedSteamCollection) -> None:
        for collection_id, existing in list(self._records.items()):
            if (
                collection_id != record.collection_id
                and existing.family == record.family
                and existing.source_key == record.source_key
            ):
                del self._records[collection_id]
        self._records[record.collection_id] = copy.deepcopy(record)

    def delete(self, collection_id: str) -> None:
        self._records.pop(collection_id, None)

    def _snapshot(self) -> dict[str, OwnedSteamCollection]:
        return copy.deepcopy(self._records)

    def _restore(self, state: dict[str, OwnedSteamCollection]) -> None:
        self._records = state
