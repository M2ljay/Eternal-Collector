"""Contract tests for the savestate backup settings and its slot in the after-exit result.

Driven frontend-shaped per ``src/api/backend.ts``: ``get_savestate_backup_settings``
takes no argument and returns ``{enabled, scope}``;
``update_savestate_backup_settings`` takes one partial-settings object and returns
``{success, settings}`` or the canonical failure shape. ``finalize_game_session``
carries ``savestates_backed_up`` beside ``sync``.
"""

from __future__ import annotations

from ._seed import enable_save_sync, seed_rom


async def test_settings_default_to_off_and_auto_state(harness):
    assert await harness.plugin.get_savestate_backup_settings() == {"enabled": False, "scope": "auto"}


async def test_turning_on_persists_and_stamps_the_moment(harness):
    result = await harness.plugin.update_savestate_backup_settings({"enabled": True, "scope": "all"})

    assert result == {"success": True, "settings": {"enabled": True, "scope": "all"}}
    assert harness.plugin.settings["savestate_backup_enabled_at"] == harness.clock.time()
    assert await harness.plugin.get_savestate_backup_settings() == {"enabled": True, "scope": "all"}


async def test_invalid_scope_answers_with_the_failure_shape(harness):
    result = await harness.plugin.update_savestate_backup_settings({"scope": "every-slot"})

    assert set(result) == {"success", "reason", "message"}
    assert result["success"] is False
    assert result["reason"] == "invalid_scope"
    assert await harness.plugin.get_savestate_backup_settings() == {"enabled": False, "scope": "auto"}


async def test_finalize_reports_no_savestates_when_the_backup_is_off(harness):
    seed_rom(harness, 1)
    enable_save_sync(harness)
    await harness.plugin.record_session_start(1)

    result = await harness.plugin.finalize_game_session(1)

    assert result["savestates_backed_up"] == 0
    assert set(result) == {"total_seconds", "sync", "migration", "savestates_backed_up"}
