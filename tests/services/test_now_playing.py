"""Tests for NowPlayingService — the shared "now playing" file."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fakes.fake_now_playing_store import FakeNowPlayingStore
from fakes.fake_romm_api import FakeRommApi
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory

from domain.rom import Rom
from lib.errors import RommNotFoundError
from services.now_playing import NowPlayingService, NowPlayingServiceConfig

APP = 3_000_000_123
IGDB = "https://images.igdb.com/igdb/image/upload/t_cover_big/co3nnx.jpg"


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _no_debug(msg: str) -> None:
    del msg


def _make(event_loop, *, store=None, api=None, platform_names=None):
    uow = FakeUnitOfWork()
    uow.roms.save(
        Rom(
            rom_id=7,
            platform_slug="n64",
            name="The Legend of Zelda: Ocarina of Time",
            fs_name="zelda.z64",
            shortcut_app_id=APP,
            last_synced_at="2026-01-01T00:00:00+00:00",
        )
    )
    uow.kv_config.set(
        "platform_names", json.dumps(platform_names if platform_names is not None else {"n64": "Nintendo 64"})
    )
    store = store if store is not None else FakeNowPlayingStore()
    api = api if api is not None else FakeRommApi()
    logger = MagicMock(spec=logging.Logger)
    service = NowPlayingService(
        config=NowPlayingServiceConfig(
            loop=event_loop,
            uow_factory=FakeUnitOfWorkFactory(uow),
            romm_api=api,
            store=store,
            logger=logger,
            log_debug=_no_debug,
        )
    )
    return service, store, api, logger


def _records(store: FakeNowPlayingStore) -> dict[str, Any]:
    assert isinstance(store.document, dict)
    return cast("dict[str, Any]", store.document["records"])


def _run(loop, coro):
    return loop.run_until_complete(coro)


class TestPublish:
    def test_writes_the_record_without_a_cover(self, event_loop):
        service, store, _, _ = _make(event_loop)
        answer = _run(event_loop, service.publish(7, APP, 1_764_190_000_000))
        expected = {
            "app_id": APP,
            "rom_id": 7,
            "name": "The Legend of Zelda: Ocarina of Time",
            "platform": "Nintendo 64",
            "started_at": 1_764_190_000_000,
            "cover_url": None,
        }
        assert answer == {"success": True, "record": expected}
        assert store.document == {"v": 1, "source": "collector", "records": {str(APP): expected}}

    def test_platform_falls_back_to_the_slug(self, event_loop):
        service, _, _, _ = _make(event_loop, platform_names={})
        assert _run(event_loop, service.publish(7, APP, 1))["record"]["platform"] == "n64"

    def test_unknown_rom_is_not_found_and_writes_nothing(self, event_loop):
        service, store, _, _ = _make(event_loop)
        answer = _run(event_loop, service.publish(99, APP, 1))
        assert answer["success"] is False
        assert answer["reason"] == "not_found"
        assert answer["message"]
        assert store.writes == 0

    def test_a_failed_write_still_answers_the_record(self, event_loop):
        store = FakeNowPlayingStore()
        store.fail_writes = True
        service, _, _, logger = _make(event_loop, store=store)
        assert _run(event_loop, service.publish(7, APP, 1))["record"]["name"] == "The Legend of Zelda: Ocarina of Time"
        assert logger.warning.called


class TestResolveCover:
    def test_adds_a_public_cover(self, event_loop):
        api = FakeRommApi()
        api.roms[7] = {"id": 7, "url_cover": IGDB, "path_cover_large": "/assets/romm/resources/roms/7/cover/big.png"}
        service, store, _, _ = _make(event_loop, api=api)
        _run(event_loop, service.publish(7, APP, 1))
        answer = _run(event_loop, service.resolve_cover(7, APP))
        assert answer["record"]["cover_url"] == IGDB
        assert _records(store)[str(APP)]["cover_url"] == IGDB

    @pytest.mark.parametrize(
        "rom",
        [
            {"id": 7, "url_cover": "https://neoclone.screenscraper.fr/api2/mediaJeu.php?devid=a&devpassword=b"},
            {"id": 7, "url_cover": "", "path_cover_large": "/assets/romm/resources/roms/7/cover/big.png"},
            {"id": 7},
        ],
    )
    def test_never_publishes_a_romm_or_credentialed_address(self, event_loop, rom):
        api = FakeRommApi()
        api.roms[7] = rom
        service, store, _, _ = _make(event_loop, api=api)
        _run(event_loop, service.publish(7, APP, 1))
        assert _run(event_loop, service.resolve_cover(7, APP))["record"]["cover_url"] is None
        assert "romm" not in json.dumps(store.document).lower().replace("rom_id", "")
        assert "devpassword" not in json.dumps(store.document)

    def test_romm_unreachable_means_no_cover(self, event_loop):
        api = FakeRommApi()
        api.get_rom_once_side_effect = RommNotFoundError("gone")
        service, _, _, _ = _make(event_loop, api=api)
        _run(event_loop, service.publish(7, APP, 1))
        answer = _run(event_loop, service.resolve_cover(7, APP))
        assert answer["success"] is True
        assert answer["record"]["cover_url"] is None

    def test_an_ended_session_is_not_brought_back(self, event_loop):
        api = FakeRommApi()
        api.roms[7] = {"id": 7, "url_cover": IGDB}
        service, store, _, _ = _make(event_loop, api=api)
        _run(event_loop, service.publish(7, APP, 1))
        _run(event_loop, service.clear(APP))
        assert _run(event_loop, service.resolve_cover(7, APP)) == {"success": True, "record": None}
        assert store.document is None


class TestClearAndReset:
    def test_clear_keeps_other_games_and_removes_the_file_when_empty(self, event_loop):
        service, store, _, _ = _make(event_loop)
        _run(event_loop, service.publish(7, APP, 1))
        _run(event_loop, service.publish(7, 5, 2))
        assert _run(event_loop, service.clear(APP)) == {"success": True}
        assert list(_records(store)) == ["5"]
        _run(event_loop, service.clear(5))
        assert store.document is None

    def test_a_clear_sent_after_a_publish_wins(self, event_loop):
        service, store, _, _ = _make(event_loop)

        async def both():
            await asyncio.gather(service.publish(7, APP, 1), service.clear(APP))

        _run(event_loop, both())
        assert store.document is None

    def test_reset_deletes_a_leftover_file(self, event_loop):
        store = FakeNowPlayingStore({"v": 1, "records": {"1": {"app_id": 1}}})
        service, _, _, _ = _make(event_loop, store=store)
        service.reset()
        assert store.document is None

    def test_reset_failure_is_only_logged(self, event_loop):
        store = FakeNowPlayingStore()
        store.fail_writes = True
        service, _, _, logger = _make(event_loop, store=store)
        service.reset()
        assert logger.warning.called
