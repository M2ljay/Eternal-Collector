"""In-memory ``RomSavestateSyncStateRepository`` implementation for service tests."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.rom_savestate_sync_state import RomSavestateSyncState


class FakeRomSavestateSyncStateRepository:
    """Dict-backed ``RomSavestateSyncStateRepository`` keyed by ``rom_id``.

    The real adapter stores one row per slot; the fake stores the whole aggregate
    under one key, deep-copied on ``save``. A ROM saved with no slots reads back as
    ``None``, as the real adapter's empty row set does.
    """

    def __init__(self) -> None:
        self._states: dict[int, RomSavestateSyncState] = {}
        self.save_count = 0

    def get(self, rom_id: int) -> RomSavestateSyncState | None:
        return copy.deepcopy(self._states.get(rom_id))

    def save(self, rom_id: int, state: RomSavestateSyncState) -> None:
        # Mirror the table's CHECK (content_hash <> '') and NOT NULL.
        for slot, record in state.slots.items():
            if not record.content_hash:
                raise ValueError(f"rom_savestate_sync_states.content_hash is required; slot {slot!r} has none")
        self.save_count += 1
        if state.slots:
            self._states[rom_id] = copy.deepcopy(state)
        else:
            self._states.pop(rom_id, None)

    def delete(self, rom_id: int) -> None:
        # Not on the Protocol — SQLite reaps these rows through the roms cascade,
        # which FakeUnitOfWork models by calling this after deleting the parent.
        self._states.pop(rom_id, None)

    def _snapshot(self) -> dict[int, RomSavestateSyncState]:
        return copy.deepcopy(self._states)

    def _restore(self, state: dict[int, RomSavestateSyncState]) -> None:
        self._states = state
