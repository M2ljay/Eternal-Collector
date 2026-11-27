"""``main.py`` in a half-copied install: the full import fails, the install check still answers.

Reproduces the reported Windows failure — ``services/game_mods/service.py`` missing after
an interrupted Decky install — on a copy of the plugin, in a fresh interpreter
so the test process's own imports are untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = textwrap.dedent(r"""
    import asyncio, importlib.util, json, logging, os, sys, types
    root = sys.argv[1]
    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("decky")
    for attr in ("DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR", "DECKY_USER_HOME"):
        setattr(decky, attr, os.path.join(root, "..", attr))
    decky.DECKY_PLUGIN_DIR = root
    async def emit(*a, **k):
        return None
    decky.emit = emit
    sys.modules["decky"] = decky
    spec = importlib.util.spec_from_file_location("rescue_main", os.path.join(root, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    async def run():
        plugin = mod.Plugin()
        await plugin._main()
        out = {
            "full_import_error": mod.FULL_IMPORT_ERROR is not None,
            "integrity": await plugin.get_install_integrity(),
            "reinstall": await plugin.prepare_plugin_reinstall(),
            "check": await plugin.check_plugin_update(False),
        }
        await plugin._unload()
        print(json.dumps(out))

    asyncio.run(run())
""")


# Imports main.py only: the pass before the full import is what is under test.
IMPORT_ONLY = textwrap.dedent(r"""
    import importlib.util, json, logging, os, sys, types
    root = sys.argv[1]
    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("decky")
    for attr in ("DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_LOG_DIR", "DECKY_USER_HOME"):
        setattr(decky, attr, os.path.join(root, "..", attr))
    decky.DECKY_PLUGIN_DIR = root
    sys.modules["decky"] = decky
    spec = importlib.util.spec_from_file_location("rescue_main", os.path.join(root, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print(json.dumps({
        "full_import_error": mod.FULL_IMPORT_ERROR,
        "repaired": list(mod.PRE_IMPORT_CHECK.repaired),
        "prepare_for_install": hasattr(mod.Plugin, "prepare_for_plugin_install"),
    }))
""")


def _copy_plugin(tmp_path):
    dest = tmp_path / "romm-dock"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(ROOT, "py_modules"), dest / "py_modules", ignore=ignore)
    for name in ("main.py", "package.json", "plugin.json"):
        shutil.copy(os.path.join(ROOT, name), dest / name)
    return dest


def _write_manifest(dest, rel_paths):
    files = []
    for rel in rel_paths:
        data = (dest / rel).read_bytes()
        files.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (dest / "install-manifest.json").write_text(json.dumps({"format": 1, "version": "0.33.0-win.19", "files": files}))


def _run(dest, child=CHILD):
    result = subprocess.run(
        [sys.executable, "-I", "-c", child, str(dest)], capture_output=True, text=True, timeout=180, check=False
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_missing_module_runs_the_install_check_only(tmp_path):
    dest = _copy_plugin(tmp_path)
    _write_manifest(dest, ["main.py", "py_modules/services/game_mods/service.py"])
    (dest / "py_modules" / "services" / "game_mods" / "service.py").unlink()

    out = _run(dest)

    assert out["full_import_error"] is True
    integrity = out["integrity"]
    assert integrity["success"] is True
    assert integrity["status"] == "incomplete"
    assert integrity["missing"] == ["py_modules/services/game_mods/service.py"]
    assert "game_mods" in integrity["import_error"]
    # Off Windows the update channel answers "unsupported", in the canonical failure shape.
    assert out["reinstall"]["success"] is False
    assert out["reinstall"]["reason"] == "unsupported"
    assert out["reinstall"]["message"]
    assert out["check"]["supported"] is False


def test_a_kept_zip_of_the_build_heals_the_folder_before_the_full_import(tmp_path):
    """The reported case: Decky's extract stopped before services/, the verified zip of the build is still kept."""
    import zipfile

    dest = _copy_plugin(tmp_path)
    missing = [
        "py_modules/services/achievement_journal.py",
        "py_modules/services/savestates/__init__.py",
        "py_modules/services/savestates/service.py",
    ]
    _write_manifest(dest, ["main.py", *missing])
    manifest = (dest / "install-manifest.json").read_bytes()
    download = tmp_path / "DECKY_PLUGIN_RUNTIME_DIR" / "plugin-update" / "download"
    download.mkdir(parents=True)
    with zipfile.ZipFile(download / "romm-dock-0.33.0-win.19.zip", "w") as zf:
        zf.writestr("romm-dock/install-manifest.json", manifest)
        for rel in ["main.py", *missing]:
            zf.writestr(f"romm-dock/{rel}", (dest / rel).read_bytes())
    for rel in missing:
        (dest / rel).unlink()

    out = _run(dest, IMPORT_ONLY)

    assert out["full_import_error"] is None
    assert out["repaired"] == sorted(missing)
    assert out["prepare_for_install"] is True
    for rel in missing:
        assert (dest / rel).exists()
