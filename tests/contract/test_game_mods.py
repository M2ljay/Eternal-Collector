"""Contract tests for the Mods panel callables over the real Plugin/bootstrap.

Driven frontend-shaped per ``src/api/backend.ts`` (``getGameMods``,
``listModSources``, ``previewModInstall``, ``installMod``, ``removeMod``,
``enableModSetting``, ``openModFolder``, ``listModBuiltins``, ``setModBuiltin``). The harness bootstraps on Linux,
where no mod store is wired: every callable must answer the canonical
``unsupported`` failure shape and touch nothing.
"""

from __future__ import annotations

import pytest

_CALLS = [
    ("get_game_mods", (1,)),
    ("list_mod_sources", (1, "textures")),
    ("preview_mod_install", (1, "textures", "pack.zip")),
    ("install_mod", (1, "textures", "pack.zip", "fp")),
    ("remove_mod", (1, "textures", None)),
    ("enable_mod_setting", (1, "textures")),
    ("open_mod_folder", (1, "textures")),
    ("list_mod_builtins", (1, "gecko_codes")),
    ("set_mod_builtin", (1, "gecko_codes", "Widescreen", True)),
]


@pytest.mark.parametrize(("method", "args"), _CALLS)
async def test_without_a_mod_store_every_callable_is_unsupported(harness, method, args):
    result = await getattr(harness.plugin, method)(*args)
    assert set(result) == {"success", "reason", "message"}
    assert result["success"] is False
    assert result["reason"] == "unsupported"
    assert result["message"]
