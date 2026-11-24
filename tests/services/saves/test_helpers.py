"""Tests for services.saves._helpers — server save → local target mapping."""

from domain.rom_save_sync_state import FileSyncState
from domain.standalone_saves import standalone_save_set
from services.saves._helpers import newest_server_saves_by_target, save_target

_RETROARCH = {"rom_name": "Tekken 3", "save_set": None}
_DUCKSTATION = {"rom_name": "Tekken 3", "save_set": standalone_save_set("duckstation", "Tekken 3")}


class TestSaveTargetRetroArch:
    def test_canonical_rom_stem_plus_extension(self):
        assert save_target({"file_extension": "srm", "emulator": "retroarch-swanstation"}, _RETROARCH) == "Tekken 3.srm"

    def test_info_without_save_set_key_is_retroarch(self):
        assert save_target({"file_extension": "srm"}, {"rom_name": "Tekken 3"}) == "Tekken 3.srm"

    def test_never_claims_a_standalone_emulators_save(self):
        for tag in ("duckstation", "melonds", "vita3k"):
            assert save_target({"file_extension": "mcd", "emulator": tag}, _RETROARCH) is None


class TestSaveTargetStandalone:
    def test_own_emulator_exact_name(self):
        save = {"id": 1, "emulator": "duckstation", "file_name": "Tekken 3_1 [2026-01-01_00-00-00].mcd"}
        assert save_target(save, _DUCKSTATION) == "Tekken 3_1.mcd"

    def test_retroarch_save_is_not_claimed(self):
        save = {"id": 1, "emulator": "retroarch-swanstation", "file_name": "Tekken 3.srm", "file_extension": "srm"}
        assert save_target(save, _DUCKSTATION) is None

    def test_tracked_id_fallback_comes_from_file_baselines(self):
        save = {"id": 9, "emulator": "duckstation", "file_name": "something else.bin"}
        files = {"Tekken 3_2.mcd": FileSyncState(tracked_save_id=9), "Tekken 3_1.mcd": FileSyncState()}
        assert save_target(save, _DUCKSTATION, files) == "Tekken 3_2.mcd"
        assert save_target(save, _DUCKSTATION) is None


class TestNewestServerSavesByTarget:
    def test_drops_unmapped_and_keeps_newest_per_target(self):
        saves = [
            {"id": 1, "emulator": "duckstation", "file_name": "Tekken 3_1.mcd", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "emulator": "duckstation", "file_name": "Tekken 3_1.mcd", "updated_at": "2026-01-02T00:00:00Z"},
            {"id": 3, "emulator": "duckstation", "file_name": "Tekken 3_2.mcd", "updated_at": "2026-01-01T00:00:00Z"},
            {"id": 4, "emulator": "retroarch-swanstation", "file_name": "Tekken 3.srm", "file_extension": "srm"},
        ]
        result = newest_server_saves_by_target(saves, _DUCKSTATION)
        assert {k: v["id"] for k, v in result.items()} == {"Tekken 3_1.mcd": 2, "Tekken 3_2.mcd": 3}

    def test_retroarch_skips_standalone_records(self):
        saves = [
            {"id": 1, "emulator": "duckstation", "file_name": "Tekken 3_1.mcd", "file_extension": "mcd"},
            {"id": 2, "emulator": "retroarch-swanstation", "file_name": "Tekken 3.srm", "file_extension": "srm"},
        ]
        assert {k: v["id"] for k, v in newest_server_saves_by_target(saves, _RETROARCH).items()} == {"Tekken 3.srm": 2}
