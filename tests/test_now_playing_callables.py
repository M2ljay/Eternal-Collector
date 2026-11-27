"""The now-playing callables pass the frontend's numbers to NowPlayingService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p._now_playing_service = MagicMock(
        publish=AsyncMock(return_value={"success": True, "record": {"app_id": 5}}),
        resolve_cover=AsyncMock(return_value={"success": True, "record": None}),
        clear=AsyncMock(return_value={"success": True}),
    )
    return p


@pytest.mark.asyncio
async def test_publish_coerces_numbers(plugin):
    assert await plugin.publish_now_playing("7", 5.0, "1764190000000") == {"success": True, "record": {"app_id": 5}}
    plugin._now_playing_service.publish.assert_awaited_once_with(7, 5, 1764190000000)


@pytest.mark.asyncio
async def test_resolve_cover_and_clear(plugin):
    assert await plugin.resolve_now_playing_cover(7, 5) == {"success": True, "record": None}
    plugin._now_playing_service.resolve_cover.assert_awaited_once_with(7, 5)
    assert await plugin.clear_now_playing("5") == {"success": True}
    plugin._now_playing_service.clear.assert_awaited_once_with(5)
