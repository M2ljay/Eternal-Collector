"""Tests for services/case_art.py — Game case cover art and the cover choice."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import pathlib
import struct
import zlib
from typing import Any

import pytest
from fakes.fake_sgdb_artwork_cache import FakeSgdbArtworkCache
from fakes.fake_steamgrid_db_api import FakeSteamGridDbApi
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory

from domain.case_art import case_grids_path
from domain.rom import Rom
from lib.errors import SgdbApiError
from services.case_art import CaseArtService, CaseArtServiceConfig

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sgdb" / "case_grids_gamecube.json"
_AUTHORS = pathlib.Path(__file__).resolve().parents[2] / "defaults" / "case_art_authors.json"
ART = "/runtime/artwork"
IMAGE, SIDECAR, SOURCE = f"{ART}/41_case.png", f"{ART}/41_case.json", f"{ART}/41_case_source.img"
PLAIN = "/runtime/covers/41.png"


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


class _Harness:
    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        sgdb_id: int | None = 4242,
        platform_slug: str = "ngc",
        seed_rom: bool = True,
        pending: dict[int, dict[str, Any]] | None = None,
    ) -> None:
        self.settings = {"steamgriddb_api_key": "k"} if settings is None else settings
        self.cache = FakeSgdbArtworkCache(cache_root="/runtime")
        self.cache.files["/plugin/case_art_authors.json"] = _AUTHORS.read_bytes()
        self.api = FakeSteamGridDbApi()
        self.api.bind_artwork_cache(self.cache)
        self.uow = FakeUnitOfWork()
        self.debug: list[str] = []
        debug = self.debug
        if seed_rom:
            rom = Rom(
                rom_id=41,
                platform_slug=platform_slug,
                name="Game",
                fs_name="Game.iso",
                shortcut_app_id=0x80000001,
                last_synced_at="2025-01-01T00:00:00",
                sgdb_id=sgdb_id,
            )
            with self.uow:
                self.uow.roms.save(rom)
        self.service = CaseArtService(
            config=CaseArtServiceConfig(
                sgdb_api=self.api,
                sgdb_artwork_cache=self.cache,
                settings=self.settings,
                plugin_dir="/plugin",
                loop=asyncio.get_event_loop(),
                logger=logging.getLogger("test"),
                log_debug=lambda msg: debug.append(msg),
                get_pending_sync=lambda: pending or {},
                uow_factory=FakeUnitOfWorkFactory(uow=self.uow),
            )
        )

    def seed_grids(self, body=None):
        self.api.seed_raw_response(case_grids_path(4242), body or json.loads(_FIXTURE.read_text()))
        for grid in (body or json.loads(_FIXTURE.read_text()))["data"]:
            self.api.seed_image_bytes(grid["url"], f"raw-{grid['id']}".encode())

    def cache_case(self, grid_id=102, manual=False, published="case"):
        self.cache.files[IMAGE] = _png(600, 900)
        self.cache.files[SIDECAR] = json.dumps({"grid_id": grid_id, "manual": manual, "published": published}).encode()


@pytest.fixture
async def h():
    return _Harness()


class TestCoverChoice:
    def test_case_style_with_cached_case_chooses_it(self, h):
        h.cache_case()
        assert h.service.do_choose_cover_path(41, PLAIN) == IMAGE
        assert h.service.do_choose_cover_path("41", PLAIN) == IMAGE

    async def test_plain_style_keeps_the_plain_cover_even_with_case_cached(self):
        h = _Harness(settings={"cover_style": "plain"})
        h.cache_case()
        assert h.service.do_choose_cover_path(41, PLAIN) == PLAIN
        assert h.service.do_has_case_cover(41) is True

    def test_no_case_cached_falls_back_to_the_plain_cover(self, h):
        assert h.service.do_choose_cover_path(41, PLAIN) == PLAIN
        assert h.service.do_has_case_cover(41) is False

    def test_restyle_candidates_are_roms_with_case_art_showing_the_other_style(self, h):
        h.cache_case(published="plain")
        assert h.service.do_restyle_candidates([41, 99]) == [41]
        h.cache_case(published="case")
        assert h.service.do_restyle_candidates([41]) == []

    def test_switch_to_plain_makes_case_tiles_candidates_and_mark_records_it(self, h):
        h.cache_case(published="case")
        h.settings["cover_style"] = "plain"
        assert h.service.do_restyle_candidates([41]) == [41]
        h.service.do_mark_published(41)
        assert json.loads(h.cache.files[SIDECAR])["published"] == "plain"
        assert h.service.do_restyle_candidates([41]) == []


class TestListCaseArt:
    async def test_lists_ranked_grids_with_the_selected_one(self, h):
        h.seed_grids()
        h.cache_case(grid_id=103)
        result = await h.service.list_case_art(41)
        assert result["success"] is True, result
        assert [g["id"] for g in result["grids"]] == [102, 105, 103, 101]
        assert result["grids"][0] == {
            "id": 102,
            "thumb": "https://cdn2.steamgriddb.com/thumb/102.png",
            "width": 600,
            "height": 900,
            "author": "Castcoder",
            "score": 3,
            "curated": True,
        }
        assert result["selected_grid_id"] == 103

    async def test_no_api_key(self):
        h = _Harness(settings={})
        assert (await h.service.list_case_art(41))["reason"] == "no_api_key"

    async def test_no_sgdb_game(self):
        h = _Harness(sgdb_id=None)
        result = await h.service.list_case_art(41)
        assert result == {
            "success": False,
            "reason": "no_sgdb_game",
            "message": "No SteamGridDB game is known for this ROM",
        }

    async def test_pending_sync_sgdb_id_is_used(self):
        h = _Harness(sgdb_id=None, pending={41: {"sgdb_id": 4242}})
        h.seed_grids()
        assert (await h.service.list_case_art(41))["success"] is True

    async def test_unreachable_and_rejected_key(self, h):
        h.api.request_side_effect = OSError("down")
        assert (await h.service.list_case_art(41))["reason"] == "server_unreachable"
        h.api.request_side_effect = SgdbApiError(status_code=401, message="no")
        assert (await h.service.list_case_art(41))["reason"] == "auth_failed"


class TestGetCaseArtSource:
    async def test_plain_style_answers_plain_without_any_request(self):
        h = _Harness(settings={"steamgriddb_api_key": "k", "cover_style": "plain"})
        assert await h.service.get_case_art_source(41) == {"success": True, "state": "plain"}
        assert h.api.requested_paths == []

    async def test_fetches_the_top_ranked_grid_for_the_frontend_to_letterbox(self, h):
        h.seed_grids()
        result = await h.service.get_case_art_source(41)
        assert result["state"] == "fetched"
        assert result["grid_id"] == 102
        assert (result["width"], result["height"]) == (600, 900)
        assert result["manual"] is False
        assert base64.b64decode(result["base64"]) == b"raw-102"
        assert h.api.downloaded == [("https://cdn2.steamgriddb.com/grid/102.png", SOURCE)]

    async def test_cached_and_already_on_the_tile_is_current_and_downloads_nothing(self, h):
        h.cache_case()
        assert await h.service.get_case_art_source(41) == {"success": True, "state": "current", "grid_id": 102}
        assert h.api.requested_paths == []

    async def test_cached_but_tile_shows_plain_hands_back_the_cached_image_and_marks_it(self, h):
        h.cache_case(published="plain")
        result = await h.service.get_case_art_source(41)
        assert result["state"] == "cached"
        assert base64.b64decode(result["base64"]) == _png(600, 900)
        assert json.loads(h.cache.files[SIDECAR])["published"] == "case"
        assert h.api.requested_paths == []

    async def test_refresh_redownloads_even_when_cached(self, h):
        h.seed_grids()
        h.cache_case(grid_id=101)
        result = await h.service.get_case_art_source(41, None, True)
        assert result["state"] == "fetched"
        assert result["grid_id"] == 102

    async def test_refresh_keeps_a_grid_the_user_chose(self, h):
        h.seed_grids()
        h.cache_case(grid_id=101, manual=True)
        result = await h.service.get_case_art_source(41, None, True)
        assert (result["grid_id"], result["manual"]) == (101, True)

    async def test_a_chosen_grid_is_fetched_even_with_plain_style(self):
        h = _Harness(settings={"steamgriddb_api_key": "k", "cover_style": "plain"})
        h.seed_grids()
        result = await h.service.get_case_art_source(41, 103)
        assert (result["state"], result["grid_id"], result["manual"]) == ("fetched", 103, True)

    async def test_a_chosen_grid_no_longer_listed_is_not_found(self, h):
        h.seed_grids()
        result = await h.service.get_case_art_source(41, 104)
        assert result["success"] is False
        assert result["reason"] == "not_found"

    async def test_no_usable_grid_keeps_the_plain_cover(self, h):
        h.seed_grids({"success": True, "data": [{"id": 1, "nsfw": True, "width": 600, "height": 900, "url": "u"}]})
        assert await h.service.get_case_art_source(41) == {"success": True, "state": "none"}

    async def test_no_sgdb_game_keeps_the_plain_cover(self):
        h = _Harness(sgdb_id=None)
        result = await h.service.get_case_art_source(41)
        assert (result["success"], result["state"]) == (True, "none")

    async def test_no_api_key_fails_with_the_canonical_shape(self):
        h = _Harness(settings={})
        result = await h.service.get_case_art_source(41)
        assert result == {"success": False, "reason": "no_api_key", "message": "No SteamGridDB API key configured"}

    async def test_download_failure(self, h):
        h.api.seed_raw_response(case_grids_path(4242), json.loads(_FIXTURE.read_text()))
        h.api.download_image_return = False
        assert (await h.service.get_case_art_source(41))["reason"] == "download_failed"

    async def test_download_reporting_success_without_a_file_is_a_download_failure(self, h):
        h.api.seed_raw_response(case_grids_path(4242), json.loads(_FIXTURE.read_text()))
        assert (await h.service.get_case_art_source(41))["reason"] == "download_failed"

    async def test_server_unreachable(self, h):
        h.api.request_side_effect = OSError("down")
        result = await h.service.get_case_art_source(41)
        assert result["reason"] == "server_unreachable"


class TestSaveCaseArt:
    async def test_stores_the_letterboxed_png_and_sidecar_and_drops_the_source(self, h):
        h.cache.files[SOURCE] = b"raw"
        png = _png(600, 900)
        result = await h.service.save_case_art(41, 102, base64.b64encode(png).decode(), False)
        assert result == {"success": True}
        assert h.cache.files[IMAGE] == png
        assert json.loads(h.cache.files[SIDECAR]) == {"grid_id": 102, "manual": False, "published": "case"}
        assert SOURCE not in h.cache.files

    async def test_records_a_manual_pick(self, h):
        await h.service.save_case_art(41, 103, base64.b64encode(_png(600, 900)).decode(), True)
        assert json.loads(h.cache.files[SIDECAR])["manual"] is True

    @pytest.mark.parametrize("png", [_png(512, 512), _png(600, 899), b"not a png"])
    async def test_refuses_anything_but_a_600x900_png(self, h, png):
        result = await h.service.save_case_art(41, 102, base64.b64encode(png).decode(), False)
        assert result["reason"] == "invalid_payload"
        assert IMAGE not in h.cache.files

    async def test_refuses_bad_base64(self, h):
        result = await h.service.save_case_art(41, 102, "%%%", False)
        assert result["reason"] == "invalid_payload"


class TestAuthorsFile:
    async def test_missing_authors_file_still_ranks_by_shape_and_score(self, h):
        del h.cache.files["/plugin/case_art_authors.json"]
        h.seed_grids()
        result = await h.service.list_case_art(41)
        assert [g["id"] for g in result["grids"]] == [105, 103, 101, 102]

    async def test_dev_deploy_reads_the_defaults_folder(self, h):
        h.cache.files["/plugin/defaults/case_art_authors.json"] = h.cache.files.pop("/plugin/case_art_authors.json")
        h.seed_grids()
        assert (await h.service.list_case_art(41))["grids"][0]["id"] == 102
