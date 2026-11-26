"""Tests for the ``RomSavestateSyncState`` aggregate."""

from __future__ import annotations

import pytest

from domain.rom_savestate_sync_state import RomSavestateSyncState, SavestateSlotRecord


def _upload(state: RomSavestateSyncState, slot: str = "auto", **overrides) -> None:
    kwargs = {
        "local_name": "Game.state.auto",
        "content_hash": "h1",
        "uploaded_at": "2026-11-26T10:00:00+00:00",
        "server_state_id": 7,
        "server_file_name": "Game [aaaa1111].state.auto",
        "emulator": "snes9x",
        "core": "snes9x",
        "core_version": "1.62",
    }
    kwargs.update(overrides)
    state.record_upload(slot, **kwargs)


class TestRecordUpload:
    def test_records_content_upload_and_provenance(self):
        state = RomSavestateSyncState()
        _upload(state)
        assert state.slots["auto"] == SavestateSlotRecord(
            local_name="Game.state.auto",
            content_hash="h1",
            observed_at="2026-11-26T10:00:00+00:00",
            uploaded_hash="h1",
            uploaded_at="2026-11-26T10:00:00+00:00",
            server_state_id=7,
            server_file_name="Game [aaaa1111].state.auto",
            emulator="snes9x",
            core="snes9x",
            core_version="1.62",
        )
        assert state.recorded_hash("auto") == "h1"

    def test_replaces_the_previous_upload(self):
        state = RomSavestateSyncState()
        _upload(state)
        _upload(state, content_hash="h2", server_state_id=7, uploaded_at="2026-11-27T10:00:00+00:00")
        assert state.recorded_hash("auto") == "h2"
        assert state.slots["auto"].uploaded_at == "2026-11-27T10:00:00+00:00"

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"content_hash": ""}, "content_hash"),
            ({"server_state_id": 0}, "server_state_id"),
            ({"server_file_name": ""}, "server_file_name"),
        ],
    )
    def test_invariants(self, overrides, match):
        state = RomSavestateSyncState()
        with pytest.raises(ValueError, match=match):
            _upload(state, **overrides)
        assert state.slots == {}

    def test_unknown_slot_raises(self):
        with pytest.raises(ValueError, match="unknown savestate slot"):
            _upload(RomSavestateSyncState(), slot="10")


class TestAdoptBaseline:
    def test_baseline_records_content_without_an_upload(self):
        state = RomSavestateSyncState()
        state.adopt_baseline("0", local_name="Game.state", content_hash="h0", observed_at="t0")
        record = state.slots["0"]
        assert record.content_hash == "h0"
        assert record.uploaded_hash is None
        assert record.server_state_id is None

    def test_baseline_over_an_upload_keeps_the_upload_fields(self):
        state = RomSavestateSyncState()
        _upload(state)
        state.adopt_baseline("auto", local_name="Game.state.auto", content_hash="h9", observed_at="t9")
        record = state.slots["auto"]
        assert record.content_hash == "h9"
        assert record.observed_at == "t9"
        assert record.uploaded_hash == "h1"
        assert record.server_state_id == 7

    def test_empty_hash_raises(self):
        with pytest.raises(ValueError, match="content_hash"):
            RomSavestateSyncState().adopt_baseline("auto", local_name="x", content_hash="", observed_at="t")

    def test_unknown_slot_raises(self):
        with pytest.raises(ValueError, match="unknown savestate slot"):
            RomSavestateSyncState().adopt_baseline("auto2", local_name="x", content_hash="h", observed_at="t")


def test_unrecorded_slot_has_no_hash():
    assert RomSavestateSyncState().recorded_hash("auto") is None
