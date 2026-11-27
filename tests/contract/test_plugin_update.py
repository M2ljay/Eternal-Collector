"""Contract test for the plugin self-update callables on a build that is not a Windows fork build.

Driven frontend-shaped per ``src/api/backend.ts``:
``checkPluginUpdate = callable<[boolean], PluginUpdateCheck>``,
``preparePluginUpdate = callable<[], PluginUpdatePrepared>``,
``getPluginRollback = callable<[], PluginRollback>`` and
``prepareForPluginInstall = callable<[], PluginInstallReady>``.

The test process is not ``win32``, so the real wiring must leave the update to the
Decky store: the check answers ``supported: False`` without touching the network,
an install is refused with the canonical failure shape, and no rollback is offered.
The Windows-side behaviour is pinned in ``tests/services/test_plugin_update.py``.
"""

from __future__ import annotations


async def test_check_is_unsupported_off_windows(harness):
    result = await harness.plugin.check_plugin_update(True)
    assert result["success"] is True
    assert result["supported"] is False
    assert result["update_available"] is False
    assert isinstance(result["current"], str)


async def test_prepare_is_refused_off_windows(harness):
    result = await harness.plugin.prepare_plugin_update()
    assert result["success"] is False
    assert result["reason"] == "unsupported"
    assert isinstance(result["message"], str)
    assert result["message"]


async def test_no_rollback_off_windows(harness):
    assert await harness.plugin.get_plugin_rollback() == {"success": True, "available": False}


async def test_prepare_for_install_releases_the_real_handles(harness):
    """The hand-off step runs on every build: nothing launched is running here, so the install is allowed."""
    result = await harness.plugin.prepare_for_plugin_install()
    assert result == {"success": True, "still_held": []}
