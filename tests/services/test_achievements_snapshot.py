"""Tests for the persisted achievement snapshot written by ``AchievementsService``."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from domain.rom import Rom
from domain.rom_achievement_progress import SNAPSHOT_FETCHED_AT_KEY, RomAchievementProgress
from lib.errors import RommApiError, RommConnectionError, RommNotFoundError
from services.achievements import AchievementsService, AchievementsServiceConfig

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
NOW_ISO = "2026-11-26T12:00:00+00:00"


class _Api:
    def __init__(self, user=None, error: Exception | None = None):
        self.user = user or {}
        self.error = error
        self.calls = 0

    def get_current_user(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.user)

    def get_rom(self, rom_id):
        return {"ra_metadata": {"achievements": [{"ra_id": i} for i in range(20)]}}


def _rom(rom_id: int, ra_id: int | None) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug="snes",
        name=f"G{rom_id}",
        fs_name=f"g{rom_id}",
        shortcut_app_id=5000 + rom_id,
        last_synced_at="2026-01-01T00:00:00",
        ra_id=ra_id,
    )


@pytest.fixture
def uow() -> FakeUnitOfWork:
    uow = FakeUnitOfWork()
    with uow:
        for rom in (_rom(1, 100), _rom(2, 100), _rom(3, 200), _rom(4, None)):
            uow.roms.save(rom)
    return uow


def _service(uow: FakeUnitOfWork, api: _Api, logs: list[str] | None = None) -> AchievementsService:
    def log_debug(msg: str) -> None:
        if logs is not None:
            logs.append(msg)

    return AchievementsService(
        config=AchievementsServiceConfig(
            romm_api=api,  # type: ignore[arg-type]
            uow_factory=FakeUnitOfWorkFactory(uow=uow),
            loop=asyncio.get_running_loop(),
            logger=logging.getLogger("test"),
            clock=FakeClock(now=NOW),
            log_debug=log_debug,
        )
    )


_USER = {
    "ra_username": "player",
    "ra_progression": {
        "results": [
            {
                "rom_ra_id": 100,
                "num_awarded": 4,
                "num_awarded_hardcore": 4,
                "max_possible": 20,
                "highest_award_kind": None,
            },
            {"rom_ra_id": 999, "num_awarded": 1, "num_awarded_hardcore": 0, "max_possible": 5},
        ]
    },
}


class TestRefreshProgressSnapshot:
    async def test_one_call_writes_rows_keyed_by_ra_id(self, uow):
        api = _Api(_USER)
        logs: list[str] = []
        result = await _service(uow, api, logs).refresh_progress_snapshot()

        assert result == {"success": True, "refreshed_at": NOW_ISO}
        assert api.calls == 1
        rows = dict(uow.rom_achievement_progress.iter_all())
        assert set(rows) == {1, 2}
        assert rows[1] == RomAchievementProgress.observed(
            earned=4, earned_hardcore=4, total=20, highest_award_kind=None, fetched_at=NOW_ISO
        )
        assert uow.kv_config.get(SNAPSHOT_FETCHED_AT_KEY) == NOW_ISO
        assert logs == ["Achievement snapshot: 2 of 3 ROMs with a set have progress"]

    async def test_replaces_rather_than_merges(self, uow):
        with uow:
            uow.rom_achievement_progress.replace_all(
                {
                    3: RomAchievementProgress.observed(
                        earned=1, earned_hardcore=0, total=9, highest_award_kind=None, fetched_at="old"
                    )
                }
            )
        await _service(uow, _Api(_USER)).refresh_progress_snapshot()
        assert set(dict(uow.rom_achievement_progress.iter_all())) == {1, 2}

    async def test_no_ra_username_empties_the_snapshot(self, uow):
        await _service(uow, _Api(_USER)).refresh_progress_snapshot()
        result = await _service(uow, _Api({"ra_username": ""})).refresh_progress_snapshot()
        assert result["success"] is True
        assert list(uow.rom_achievement_progress.iter_all()) == []

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (RommConnectionError("down"), "server_unreachable"),
            (RommNotFoundError("gone"), "not_found"),
        ],
    )
    async def test_failure_keeps_the_previous_snapshot(self, uow, error, reason):
        await _service(uow, _Api(_USER)).refresh_progress_snapshot()
        result = await _service(uow, _Api(error=error)).refresh_progress_snapshot()
        assert set(result) == {"success", "reason", "message"}
        assert result["success"] is False
        assert result["reason"] == reason
        assert set(dict(uow.rom_achievement_progress.iter_all())) == {1, 2}

    async def test_a_store_failure_is_reported(self, uow, monkeypatch):
        service = _service(uow, _Api(_USER))

        def boom(_user):
            raise RuntimeError("disk full")

        monkeypatch.setattr(service, "do_store_progress_snapshot", boom)
        result = await service.refresh_progress_snapshot()
        assert result == {"success": False, "reason": "snapshot_failed", "message": "disk full"}


class TestProgressReadStoresTheSnapshot:
    async def test_per_rom_progress_read_also_stores_the_snapshot(self, uow):
        api = _Api(_USER)
        result = await _service(uow, api).get_achievement_progress(1)
        assert result["success"] is True
        assert set(dict(uow.rom_achievement_progress.iter_all())) == {1, 2}

    async def test_store_failure_does_not_break_the_progress_read(self, uow, monkeypatch, caplog):
        service = _service(uow, _Api(_USER))

        def boom(_user):
            raise RommApiError("locked")

        monkeypatch.setattr(service, "do_store_progress_snapshot", boom)
        with caplog.at_level(logging.WARNING, logger="test"):
            result = await service.get_achievement_progress(1)
        assert result["success"] is True
        assert result["earned"] == 4
        assert "Failed to store the achievement snapshot: locked" in caplog.text
