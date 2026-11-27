"""In-memory ``RaGameJournalRepository`` implementation for service tests."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain.ra_game_journal import RaGameJournal


class FakeRaGameJournalRepository:
    """Dict-backed ``RaGameJournalRepository`` keyed by RetroAchievements game id."""

    def __init__(self) -> None:
        self._journals: dict[int, RaGameJournal] = {}

    def get(self, ra_game_id: int) -> RaGameJournal | None:
        return copy.deepcopy(self._journals.get(ra_game_id))

    def iter_all(self) -> Iterator[RaGameJournal]:
        for ra_game_id in sorted(self._journals):
            yield copy.deepcopy(self._journals[ra_game_id])

    def save(self, journal: RaGameJournal) -> None:
        self._journals[journal.ra_game_id] = copy.deepcopy(journal)

    def delete(self, ra_game_id: int) -> None:
        self._journals.pop(ra_game_id, None)

    def _snapshot(self) -> dict[int, RaGameJournal]:
        return copy.deepcopy(self._journals)

    def _restore(self, state: dict[int, RaGameJournal]) -> None:
        self._journals = state
