"""Contract tests for The Collector's callables over the real nesting.

Driven frontend-shaped per ``src/api/backend.ts``: ``get_console_shelf`` takes no
argument; ``get_console_games`` takes ``(platform_slug, offset, limit)``;
``refresh_console_achievements`` takes no argument and answers ``{success,
refreshed_at}`` or the canonical failure shape; ``save_collector_home_shelf`` takes
one boolean.
"""

from __future__ import annotations

from domain.rom import Rom
from lib.errors import RommConnectionError

from ._seed import seed_rom


def _seed_ra_rom(harness, rom_id: int, ra_id: int) -> None:
    with harness.uow_factory() as uow:
        uow.roms.save(
            Rom(
                rom_id=rom_id,
                platform_slug="ps2",
                name=f"rom-{rom_id}",
                fs_name=f"rom-{rom_id}",
                shortcut_app_id=rom_id,
                last_synced_at="2026-01-01T00:00:00",
                ra_id=ra_id,
            )
        )


async def test_shelf_shape_over_real_sqlite(harness):
    seed_rom(harness, 1, platform_slug="ps2")
    seed_rom(harness, 2, platform_slug="ps2")
    seed_rom(harness, 3, platform_slug="gba", shortcut_app_id=None)

    result = await harness.plugin.get_console_shelf()

    assert result == {
        "success": True,
        "enabled": True,
        "consoles": [
            {
                "platform_slug": "ps2",
                "name": "ps2",
                "game_count": 2,
                "last_played": None,
                "play_seconds": 0,
                "cover_app_id": 1,
            },
        ],
    }


async def test_toggle_round_trips_through_the_shelf_and_settings(harness):
    assert await harness.plugin.save_collector_home_shelf(False) == {"success": True}
    assert (await harness.plugin.get_console_shelf())["enabled"] is False
    assert (await harness.plugin.get_settings())["collector_home_shelf"] is False


async def test_console_page_shape(harness):
    seed_rom(harness, 1, platform_slug="ps2")

    result = await harness.plugin.get_console_games("ps2", 0, 100)

    assert set(result) == {
        "success",
        "platform_slug",
        "name",
        "total",
        "offset",
        "continue_rom_id",
        "save_sync_enabled",
        "achievements_fetched_at",
        "games",
    }
    assert result["games"] == [
        {
            "rom_id": 1,
            "app_id": 1,
            "name": "rom-1",
            "last_played": None,
            "play_seconds": 0,
            "installed": False,
            "save_sync": None,
            "achievements": None,
            "has_ra_set": False,
        }
    ]


async def test_console_page_rejects_a_bad_page(harness):
    result = await harness.plugin.get_console_games("ps2", -5, 100)
    assert set(result) == {"success", "reason", "message"}
    assert result["reason"] == "invalid_page"


async def test_refresh_then_the_page_shows_progress(harness):
    _seed_ra_rom(harness, 1, 777)
    harness.romm.current_user = {
        "id": 1,
        "ra_username": "player",
        "ra_progression": {
            "results": [{"rom_ra_id": 777, "num_awarded": 3, "num_awarded_hardcore": 0, "max_possible": 12}]
        },
    }

    refreshed = await harness.plugin.refresh_console_achievements()
    page = await harness.plugin.get_console_games("ps2", 0, 100)

    assert refreshed["success"] is True
    assert page["achievements_fetched_at"] == refreshed["refreshed_at"]
    assert page["games"][0]["has_ra_set"] is True
    assert page["games"][0]["achievements"]["earned"] == 3
    assert page["games"][0]["achievements"]["total"] == 12


async def test_refresh_failure_answers_with_the_failure_shape(harness):
    harness.romm.get_current_user_side_effect = RommConnectionError("down")

    result = await harness.plugin.refresh_console_achievements()

    assert set(result) == {"success", "reason", "message"}
    assert result["success"] is False
    assert result["reason"] == "server_unreachable"
