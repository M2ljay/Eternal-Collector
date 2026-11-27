"""Tests for ``core_bootstrap`` — the import-safe root behind the install check and self-update."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import patch

import core_bootstrap
from core_bootstrap import build_core, check_install_before_import, read_plugin_version


def _no_debug(msg: str) -> None:
    del msg


def _plugin(tmp_path, version="0.33.0-win.19"):
    root = tmp_path / "romm-dock"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"version": version}))
    return root


async def test_builds_both_services(tmp_path):
    root = _plugin(tmp_path)
    core = build_core(
        loop=asyncio.get_running_loop(),
        logger=logging.getLogger("t"),
        log_debug=_no_debug,
        plugin_dir=str(root),
        runtime_dir=str(tmp_path / "runtime"),
    )
    assert core.current_version == "0.33.0-win.19"
    assert core.plugin_update is not None
    assert core.folder_handles is not None
    assert core.update_wiring_error is None
    assert (await core.install_integrity.get_report())["status"] == "unchecked"


async def test_update_half_failing_leaves_the_install_check(tmp_path):
    root = _plugin(tmp_path)
    with patch.object(
        core_bootstrap, "_build_update", side_effect=ImportError("no module named services.plugin_update")
    ):
        core = build_core(
            loop=asyncio.get_running_loop(),
            logger=logging.getLogger("t"),
            log_debug=_no_debug,
            plugin_dir=str(root),
            runtime_dir=str(tmp_path / "runtime"),
        )
    assert core.plugin_update is None
    assert core.folder_handles is None
    assert "plugin_update" in (core.update_wiring_error or "")
    assert (await core.install_integrity.get_report())["success"] is True


def _half_copied_with_kept_zip(tmp_path, version="0.33.0-win.25"):
    """A plugin folder missing one module, and the verified release zip of the same build in the update cache."""
    import hashlib
    import zipfile

    root = _plugin(tmp_path, version)
    files = {
        "package.json": (root / "package.json").read_bytes(),
        "py_modules/services/now_playing.py": b"NOW = 1\n",
    }
    entries = [{"path": p, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for p, d in files.items()]
    manifest = json.dumps({"format": 1, "version": version, "files": entries}).encode()
    (root / "install-manifest.json").write_bytes(manifest)
    download = tmp_path / "runtime" / "plugin-update" / "download"
    download.mkdir(parents=True)
    with zipfile.ZipFile(download / f"romm-dock-{version}.zip", "w") as zf:
        zf.writestr("romm-dock/install-manifest.json", manifest)
        for rel, data in files.items():
            zf.writestr(f"romm-dock/{rel}", data)
    return root


async def test_pre_import_pass_restores_from_the_kept_zip_and_build_core_reports_it(tmp_path):
    root = _half_copied_with_kept_zip(tmp_path)
    runtime = str(tmp_path / "runtime")
    before = check_install_before_import(logger=logging.getLogger("t"), plugin_dir=str(root), runtime_dir=runtime)
    assert (root / "py_modules" / "services" / "now_playing.py").read_bytes() == b"NOW = 1\n"
    core = build_core(
        loop=asyncio.get_running_loop(),
        logger=logging.getLogger("t"),
        log_debug=_no_debug,
        plugin_dir=str(root),
        runtime_dir=runtime,
        pre_import_check=before,
    )
    report = await core.install_integrity.get_report()
    assert report["status"] == "ok"
    assert report["repaired"] == ["py_modules/services/now_playing.py"]
    assert report["repair_source"] == "romm-dock-0.33.0-win.25.zip"
    assert report["restart_needed"] is False


def test_pre_import_pass_without_a_kept_zip_changes_nothing(tmp_path):
    root = _half_copied_with_kept_zip(tmp_path)
    (tmp_path / "runtime" / "plugin-update" / "download" / "romm-dock-0.33.0-win.25.zip").unlink()
    before = check_install_before_import(
        logger=logging.getLogger("t"), plugin_dir=str(root), runtime_dir=str(tmp_path / "runtime")
    )
    assert before.repaired == ()
    assert not (root / "py_modules").exists()


def test_read_plugin_version_tolerates_bad_files(tmp_path):
    assert read_plugin_version(str(tmp_path)) == ""
    (tmp_path / "package.json").write_text("[1]")
    assert read_plugin_version(str(tmp_path)) == ""
    (tmp_path / "package.json").write_text(json.dumps({"version": 3}))
    assert read_plugin_version(str(tmp_path)) == ""


# The import-safe core: these files load before (and without) every other plugin module.
_CORE_FILES = {
    "core_bootstrap.py": "core_bootstrap",
    "domain/install_manifest.py": "domain.install_manifest",
    "adapters/install_files.py": "adapters.install_files",
    "adapters/install_repair_files.py": "adapters.install_repair_files",
    "services/install_integrity.py": "services.install_integrity",
}


def _module_level_imports(path):
    import ast

    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = []

    def visit(body):
        for node in body:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                continue  # never executed
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.append(node.module)
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                visit(getattr(node, "orelse", []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)

    visit(tree.body)
    return found


def test_core_files_import_only_the_stdlib_and_each_other():
    import os
    import sys

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules")
    allowed = set(_CORE_FILES.values())
    for rel in _CORE_FILES:
        for name in _module_level_imports(os.path.join(root, rel)):
            assert name.split(".")[0] in sys.stdlib_module_names or name in allowed, f"{rel} imports {name}"


def test_import_scan_catches_a_plugin_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import lib.errors\nimport services.saves\n"
    )
    assert _module_level_imports(bad) == ["typing", "services.saves"]
