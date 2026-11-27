"""Contract tests for the Game case cover-art callables over the real nesting.

Driven frontend-shaped per ``src/api/backend.ts``: ``list_case_art(rom_id)``,
``get_case_art_source(rom_id, grid_id | null, refresh)``,
``save_case_art(rom_id, grid_id, png_base64, manual)`` and
``set_cover_style(style)``.
"""

from __future__ import annotations

import base64
import struct
import zlib

from domain.case_art import case_grids_path
from domain.rom import Rom
from lib.errors import SgdbApiError

_GRID = {
    "id": 9,
    "score": 4,
    "style": "alternate",
    "width": 512,
    "height": 512,
    "nsfw": False,
    "humor": False,
    "epilepsy": False,
    "mime": "image/png",
    "url": "https://cdn2.steamgriddb.com/grid/9.png",
    "thumb": "https://cdn2.steamgriddb.com/thumb/9.png",
    "author": {"name": "Someone", "steam64": "1", "avatar": None},
}


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


def _seed(harness, *, sgdb_id: int | None = 77) -> None:
    harness.plugin.settings["steamgriddb_api_key"] = "key"
    with harness.uow_factory() as uow:
        uow.roms.save(
            Rom(
                rom_id=41,
                platform_slug="nds",
                name="rom-41",
                fs_name="rom-41",
                shortcut_app_id=41,
                last_synced_at="2026-01-01T00:00:00",
                sgdb_id=sgdb_id,
            )
        )
    harness.sgdb.seed_raw_response(case_grids_path(77), {"success": True, "data": [_GRID]})
    harness.sgdb.seed_image_bytes(_GRID["url"], b"raw grid bytes")


async def test_fetch_save_then_current_and_served_as_the_cover(harness):
    _seed(harness)

    fetched = await harness.plugin.get_case_art_source(41, None, False)
    assert fetched["success"] is True
    assert fetched["state"] == "fetched"
    assert (fetched["grid_id"], fetched["width"], fetched["height"], fetched["manual"]) == (9, 512, 512, False)
    assert base64.b64decode(fetched["base64"]) == b"raw grid bytes"
    assert isinstance(fetched["prune_lease_token"], str)

    png = _png(600, 900)
    saved = await harness.plugin.save_case_art(41, 9, base64.b64encode(png).decode(), False)
    assert saved == {"success": True}

    again = await harness.plugin.get_case_art_source(41, None, False)
    assert again == {"success": True, "state": "current", "grid_id": 9}

    cover = await harness.plugin.get_artwork_base64(41)
    assert base64.b64decode(cover["base64"]) == png


async def test_list_shape(harness):
    _seed(harness)
    result = await harness.plugin.list_case_art(41)
    assert result == {
        "success": True,
        "grids": [
            {
                "id": 9,
                "thumb": _GRID["thumb"],
                "width": 512,
                "height": 512,
                "author": "Someone",
                "score": 4,
                "curated": False,
            }
        ],
        "selected_grid_id": None,
    }


async def test_failures_use_the_canonical_shape(harness):
    _seed(harness)
    harness.sgdb.request_side_effect = SgdbApiError(status_code=503, message="down")
    result = await harness.plugin.list_case_art(41)
    assert set(result) == {"success", "reason", "message"}
    assert result["reason"] == "server_unreachable"

    bad = await harness.plugin.save_case_art(41, 9, base64.b64encode(_png(512, 512)).decode(), False)
    assert bad["success"] is False
    assert bad["reason"] == "invalid_payload"


async def test_plain_style_round_trips_and_answers_plain(harness):
    _seed(harness)
    assert await harness.plugin.set_cover_style("plain") == {"success": True}
    assert (await harness.plugin.get_settings())["cover_style"] == "plain"
    assert await harness.plugin.get_case_art_source(41, None, False) == {"success": True, "state": "plain"}
    rejected = await harness.plugin.set_cover_style("shiny")
    assert rejected["reason"] == "invalid_style"


async def test_unknown_sgdb_game_keeps_the_plain_cover(harness):
    _seed(harness, sgdb_id=None)
    result = await harness.plugin.get_case_art_source(41, None, False)
    assert (result["success"], result["state"]) == (True, "none")
