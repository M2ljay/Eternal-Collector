"""Contract tests for the achievement goals, notes and unlock-timeline callables over the real nesting.

Driven frontend-shaped per ``src/api/backend.ts``: ROM ids are numbers, the pinned
achievement is ``{achievement_id, title, description, points}``, unlocks are
``[{achievement_id, unlocked_at, hardcore}]``, the timeline takes ``(days, force)``,
and the Web API settings take ``(username, api_key)`` with ``"••••"`` meaning "keep
the stored key". Failures use the canonical shape.
"""

from __future__ import annotations

from domain.rom import Rom
from lib.errors import RaWebApiError

KEY = "AbCdEf0123456789AbCdEf0123456789"


def _seed(harness, rom_id: int = 1, ra_id: int | None = 77) -> None:
    with harness.uow_factory() as uow:
        rom = Rom.synced(
            rom_id=rom_id,
            platform_slug="genesis",
            name="Sonic",
            fs_name="sonic.md",
            shortcut_app_id=4000 + rom_id,
            synced_at="2026-01-01T00:00:00",
        )
        if ra_id is not None:
            rom.assign_ra_id(ra_id)
        uow.roms.save(rom)


async def test_goals_and_notes_round_trip_over_real_sqlite(harness):
    _seed(harness)
    plugin = harness.plugin

    pinned = await plugin.pin_achievement_goal(
        1, {"achievement_id": 11, "title": "Ring Master", "description": "Collect 100 rings", "points": 10}
    )
    assert pinned["success"] is True
    assert (await plugin.save_achievement_notes(1, "Spin dash past the spikes"))["success"] is True
    assert await plugin.record_achievement_goal_unlocks(
        1, [{"achievement_id": 11, "unlocked_at": "2026-11-20 10:00:00", "hardcore": False}]
    ) == {"success": True, "changed": 1}

    journal = await plugin.get_achievement_journal(1)
    assert journal["notes"] == "Spin dash past the spikes"
    assert journal["web_api_configured"] is False
    assert journal["goals"][0]["unlocked_at"] == "2026-11-20T10:00:00Z"

    overview = await plugin.get_achievement_goals()
    assert overview["success"] is True
    assert overview["goals"][0]["app_id"] == 4001
    assert overview["open_count"] == 0

    assert (await plugin.unpin_achievement_goal(1, 11))["goals"] == []


async def test_failures_use_the_canonical_shape(harness):
    _seed(harness, rom_id=2, ra_id=None)
    plugin = harness.plugin
    for answer in (
        await plugin.get_achievement_journal(2),
        await plugin.save_achievement_notes(999, "x"),
        await plugin.pin_achievement_goal(2, {"achievement_id": 1, "title": "t", "points": 1}),
        await plugin.get_unlock_timeline(30, False),
        await plugin.refresh_achievement_goals(),
        await plugin.save_ra_web_api("", KEY),
    ):
        assert answer["success"] is False
        assert set(answer) == {"success", "reason", "message"}


async def test_web_api_key_is_masked_and_used_only_by_the_adapter_edge(harness):
    _seed(harness)
    plugin = harness.plugin
    assert await plugin.verify_ra_web_api("Jamiras", KEY) == {
        "success": True,
        "message": "RetroAchievements accepted the key",
    }
    assert await plugin.save_ra_web_api("Jamiras", KEY) == {"success": True}

    settings = await plugin.get_settings()
    assert settings["ra_web_username"] == "Jamiras"
    assert settings["ra_web_api_key_masked"] == "••••"
    assert KEY not in repr(settings)

    harness.ra_web.timeline = [
        {
            "Date": "2026-11-25 10:00:00",
            "HardcoreMode": 1,
            "AchievementID": 11,
            "Title": "Ring Master",
            "Points": 10,
            "GameID": 77,
            "GameTitle": "Sonic",
            "ConsoleName": "Genesis/Mega Drive",
        }
    ]
    timeline = await plugin.get_unlock_timeline(30, True)
    assert timeline["success"] is True
    assert [e["achievement_id"] for e in timeline["entries"]] == [11]
    assert KEY not in repr(timeline)

    harness.ra_web.error = RaWebApiError(401, "refused")
    assert (await plugin.get_unlock_timeline(90, True))["reason"] == "auth_failed"

    assert await plugin.clear_ra_web_api() == {"success": True}
    assert (await plugin.get_settings())["ra_web_api_key_masked"] == ""


async def test_game_links(harness):
    _seed(harness)
    links = await harness.plugin.get_achievement_game_links(1)
    assert links == {
        "success": True,
        "game_url": "https://retroachievements.org/game/77",
        "guide_url": None,
        "web_api_configured": False,
    }


async def test_bridge_reads_over_real_sqlite_never_carry_the_key(harness):
    _seed(harness)
    plugin = harness.plugin

    assert (await plugin.get_recent_ra_unlocks(5))["reason"] == "no_web_api_key"
    assert (await plugin.get_closest_ra_completions(5))["reason"] == "no_snapshot"
    for answer in (await plugin.get_recent_ra_unlocks(0), await plugin.get_closest_ra_completions("5")):
        assert set(answer) == {"success", "reason", "message"}
        assert answer["reason"] == "invalid_argument"

    assert await plugin.save_ra_web_api("Jamiras", KEY) == {"success": True}
    harness.ra_web.timeline = [
        {
            "Date": "2026-11-25 10:00:00",
            "HardcoreMode": 1,
            "AchievementID": 11,
            "Title": "Ring Master",
            "Description": "Collect 100 rings",
            "Points": 10,
            "GameID": 77,
            "GameTitle": "Sonic",
            "ConsoleName": "Genesis/Mega Drive",
            "BadgeURL": "/Badge/250336.png",
        }
    ]
    recent = await plugin.get_recent_ra_unlocks(5)
    assert recent == {
        "success": True,
        "items": [
            {
                "rom_id": 1,
                "app_id": 4001,
                "game": "Sonic",
                "platform": "Genesis/Mega Drive",
                "title": "Ring Master",
                "description": "Collect 100 rings",
                "badge_url": "https://media.retroachievements.org/Badge/250336.png",
                "unlocked_at": "2026-11-25T10:00:00Z",
                "hardcore": True,
            }
        ],
    }
    assert KEY not in repr(recent)

    harness.romm.current_user = {
        "id": 1,
        "ra_username": "player",
        "ra_progression": {
            "results": [{"rom_ra_id": 77, "num_awarded": 3, "num_awarded_hardcore": 0, "max_possible": 12}]
        },
    }
    assert (await plugin.refresh_console_achievements())["success"] is True
    closest = await plugin.get_closest_ra_completions(5)
    assert closest["success"] is True
    assert closest["items"] == [
        {"rom_id": 1, "app_id": 4001, "game": "Sonic", "platform": "genesis", "earned": 3, "total": 12, "percent": 25.0}
    ]
    assert KEY not in repr(closest)

    harness.ra_web.error = RaWebApiError(None, "down")
    await plugin.save_ra_web_api("Jamiras", "••••")  # drops the cached timeline
    failed = await plugin.get_recent_ra_unlocks(5)
    assert set(failed) == {"success", "reason", "message"}
    assert failed["reason"] == "server_unreachable"
