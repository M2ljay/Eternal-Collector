"""SQLite adapter for the ``RomSavestateSyncState`` aggregate over ``rom_savestate_sync_states``.

One row per ``(rom_id, slot)``; the aggregate is every row of one ``rom_id``. ``get``
rebuilds it (``None`` when the ROM has no rows), ``save`` replaces the ROM's rows
inside the unit of work's open transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.repositories._base import BaseRepository
from domain.rom_savestate_sync_state import RomSavestateSyncState, SavestateSlotRecord

if TYPE_CHECKING:
    import sqlite3

_COLUMNS = (
    "rom_id, slot, local_name, content_hash, observed_at, uploaded_hash, uploaded_at, "
    "server_state_id, server_file_name, emulator, core, core_version"
)


def _row_to_record(row: sqlite3.Row) -> SavestateSlotRecord:
    return SavestateSlotRecord(
        local_name=row["local_name"],
        content_hash=row["content_hash"],
        observed_at=row["observed_at"],
        uploaded_hash=row["uploaded_hash"],
        uploaded_at=row["uploaded_at"],
        server_state_id=row["server_state_id"],
        server_file_name=row["server_file_name"],
        emulator=row["emulator"],
        core=row["core"],
        core_version=row["core_version"],
    )


class SqliteRomSavestateSyncStateRepository(BaseRepository):
    """Per-ROM savestate backup records keyed by ``(rom_id, slot)``."""

    def get(self, rom_id: int) -> RomSavestateSyncState | None:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM rom_savestate_sync_states WHERE rom_id = ? ORDER BY slot",
            (rom_id,),
        ).fetchall()
        if not rows:
            return None
        return RomSavestateSyncState(slots={row["slot"]: _row_to_record(row) for row in rows})

    def save(self, rom_id: int, state: RomSavestateSyncState) -> None:
        self._conn.execute("DELETE FROM rom_savestate_sync_states WHERE rom_id = ?", (rom_id,))
        self._conn.executemany(
            f"INSERT INTO rom_savestate_sync_states ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    rom_id,
                    slot,
                    record.local_name,
                    record.content_hash,
                    record.observed_at,
                    record.uploaded_hash,
                    record.uploaded_at,
                    record.server_state_id,
                    record.server_file_name,
                    record.emulator,
                    record.core,
                    record.core_version,
                )
                for slot, record in state.slots.items()
            ],
        )
