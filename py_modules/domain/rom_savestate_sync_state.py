"""RomSavestateSyncState — what this device has backed up of one ROM's savestates.

The savestate twin of :class:`domain.rom_save_sync_state.RomSaveSyncState`, kept
apart from it on purpose: savestates are backed up, never synced, so nothing here
takes part in a save-sync decision. References its Rom by id (the registry key) and
holds one :class:`SavestateSlotRecord` per slot in the ``auto`` / ``0``…``9``
vocabulary of :mod:`domain.savestate_names`.

Invariants enforced here:

1. A slot key is always one of :data:`domain.savestate_names.ALL_SLOTS`.
2. A recorded slot always carries a non-empty content hash: the content this device
   last accounted for, by uploading it or by recording it as a baseline.
3. An upload always carries the server's positive savestate id and the file name
   the server stored it under; a baseline never invents either.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from domain._aggregate import cosmic_aggregate
from domain.savestate_names import ALL_SLOTS


@dataclass(frozen=True, slots=True)
class SavestateSlotRecord:
    """One slot's record: the content last accounted for, and the latest upload of it.

    ``content_hash`` / ``observed_at`` describe the local savestate this device last
    accounted for. The ``uploaded_*`` / ``server_*`` / provenance fields describe the
    latest upload and stay as they were when a later savestate is only recorded as a
    baseline — that server copy still exists, it is just older than the local file.
    ``core`` / ``core_version`` are kept locally because servers before RomM 5.5 do
    not store them, and a restore has to warn on a core mismatch.
    """

    local_name: str
    content_hash: str
    observed_at: str
    uploaded_hash: str | None = None
    uploaded_at: str | None = None
    server_state_id: int | None = None
    server_file_name: str | None = None
    emulator: str | None = None
    core: str | None = None
    core_version: str | None = None


def _check_slot(slot: str) -> None:
    if slot not in ALL_SLOTS:
        raise ValueError(f"unknown savestate slot {slot!r}")


@cosmic_aggregate
class RomSavestateSyncState:
    """Savestate backup state for one ROM — one record per slot."""

    slots: dict[str, SavestateSlotRecord] = field(default_factory=dict)

    def recorded_hash(self, slot: str) -> str | None:
        """The content hash this device last accounted for in *slot*, or ``None``."""
        record = self.slots.get(slot)
        return record.content_hash if record is not None else None

    def record_upload(
        self,
        slot: str,
        *,
        local_name: str,
        content_hash: str,
        uploaded_at: str,
        server_state_id: int,
        server_file_name: str,
        emulator: str | None,
        core: str | None,
        core_version: str | None,
    ) -> None:
        """Record that *slot*'s savestate with *content_hash* reached the server.

        Replaces the slot's record whole. Raises ``ValueError`` for an unknown slot,
        an empty hash, a non-positive server id or an empty server file name.
        """
        _check_slot(slot)
        if not content_hash:
            raise ValueError("content_hash is required to record an upload")
        if server_state_id <= 0:
            raise ValueError("server_state_id must be positive")
        if not server_file_name:
            raise ValueError("server_file_name is required to record an upload")
        self.slots[slot] = SavestateSlotRecord(
            local_name=local_name,
            content_hash=content_hash,
            observed_at=uploaded_at,
            uploaded_hash=content_hash,
            uploaded_at=uploaded_at,
            server_state_id=server_state_id,
            server_file_name=server_file_name,
            emulator=emulator,
            core=core,
            core_version=core_version,
        )

    def adopt_baseline(self, slot: str, *, local_name: str, content_hash: str, observed_at: str) -> None:
        """Record *slot*'s savestate as accounted for without uploading it.

        Keeps the slot's latest-upload fields when there are any. Raises
        ``ValueError`` for an unknown slot or an empty hash.
        """
        _check_slot(slot)
        if not content_hash:
            raise ValueError("content_hash is required to adopt a baseline")
        existing = self.slots.get(slot)
        if existing is None:
            self.slots[slot] = SavestateSlotRecord(
                local_name=local_name, content_hash=content_hash, observed_at=observed_at
            )
            return
        self.slots[slot] = replace(existing, local_name=local_name, content_hash=content_hash, observed_at=observed_at)
