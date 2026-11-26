"""In-memory ``RomAchievementProgressRepository`` implementation for service tests."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from domain.rom_achievement_progress import RomAchievementProgress


class FakeRomAchievementProgressRepository:
    """Dict-backed ``RomAchievementProgressRepository`` keyed by ``rom_id``."""

    def __init__(self) -> None:
        self._progress: dict[int, RomAchievementProgress] = {}
        self.replace_count = 0

    def get(self, rom_id: int) -> RomAchievementProgress | None:
        return copy.deepcopy(self._progress.get(rom_id))

    def iter_all(self) -> Iterator[tuple[int, RomAchievementProgress]]:
        for rom_id in sorted(self._progress):
            yield (rom_id, copy.deepcopy(self._progress[rom_id]))

    def replace_all(self, snapshot: dict[int, RomAchievementProgress]) -> None:
        self.replace_count += 1
        self._progress = copy.deepcopy(snapshot)

    def delete(self, rom_id: int) -> None:
        # Not on the Protocol — SQLite reaps these rows through the roms cascade,
        # which FakeUnitOfWork models by calling this after deleting the parent.
        self._progress.pop(rom_id, None)

    def _snapshot(self) -> dict[int, RomAchievementProgress]:
        return copy.deepcopy(self._progress)

    def _restore(self, state: dict[int, RomAchievementProgress]) -> None:
        self._progress = state
