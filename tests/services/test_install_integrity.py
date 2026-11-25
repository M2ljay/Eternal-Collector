"""Tests for ``InstallIntegrityService`` over a real folder (the adapter is stdlib file reads)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging

import pytest

from adapters.install_files import InstallFileAdapter
from services.install_integrity import InstallIntegrityService, InstallIntegrityServiceConfig

FILES = {
    "main.py": b"import decky\n",
    "plugin.json": b"{}",
    "py_modules/services/game_mods.py": b"GAME = 1\n",
    "py_modules/services/downloads/__init__.py": b"",
}


def _write_install(root, files=FILES, manifest_files=FILES, version="0.33.0-win.19"):
    for rel, data in files.items():
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    entries = [
        {"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for rel, data in manifest_files.items()
    ]
    (root / "install-manifest.json").write_text(json.dumps({"format": 1, "version": version, "files": entries}))


@pytest.fixture
def make(tmp_path):
    def _make(root=None):
        return InstallIntegrityService(
            config=InstallIntegrityServiceConfig(
                loop=asyncio.get_running_loop(),
                logger=logging.getLogger("test"),
                scanner=InstallFileAdapter(str(root or tmp_path)),
                current_version="0.33.0-win.19",
            )
        )

    return _make


async def test_complete_install_is_ok(tmp_path, make):
    _write_install(tmp_path)
    svc = make()
    assert svc.check_sizes().status == "ok"
    report = await svc.get_report()
    assert report["success"] is True
    assert report["status"] == "ok"
    assert report["hashes_checked"] is True
    assert report["expected_version"] == "0.33.0-win.19"
    assert report["current_version"] == "0.33.0-win.19"


async def test_missing_file_is_incomplete_from_the_size_pass(tmp_path, make, caplog):
    _write_install(tmp_path)
    (tmp_path / "py_modules" / "services" / "game_mods.py").unlink()
    with caplog.at_level(logging.ERROR):
        report = await make().get_report()
    assert report["status"] == "incomplete"
    assert report["missing"] == ["py_modules/services/game_mods.py"]
    assert "incomplete" in caplog.text


async def test_same_size_different_bytes_is_caught_by_the_hash_pass(tmp_path, make):
    _write_install(tmp_path)
    (tmp_path / "main.py").write_bytes(b"import DECKY\n")
    svc = make()
    assert svc.check_sizes().status == "ok"
    report = await svc.get_report()
    assert report["status"] == "incomplete"
    assert report["mismatched"] == ["main.py"]


async def test_stale_module_beside_a_package_is_reported(tmp_path, make):
    _write_install(tmp_path)
    (tmp_path / "py_modules" / "services" / "downloads.py").write_bytes(b"OLD = 1\n")
    report = await make().get_report()
    assert report["status"] == "stale_files"
    assert report["extra"] == ["py_modules/services/downloads.py"]
    assert report["shadowing"] == ["py_modules/services/downloads.py"]


async def test_no_manifest_is_unchecked(tmp_path, make):
    (tmp_path / "main.py").write_bytes(b"x")
    report = await make().get_report()
    assert report["status"] == "unchecked"


async def test_corrupt_manifest_is_incomplete(tmp_path, make):
    (tmp_path / "install-manifest.json").write_bytes(b"{trunc")
    report = await make().get_report()
    assert report["status"] == "incomplete"
    assert "not valid JSON" in report["detail"]


async def test_import_failure_marks_a_clean_folder_incomplete(tmp_path, make):
    _write_install(tmp_path)
    svc = make()
    svc.check_sizes()
    svc.record_import_failure("ModuleNotFoundError: No module named 'services.game_mods'")
    report = await svc.get_report()
    assert report["status"] == "incomplete"
    assert "game_mods" in report["import_error"]


async def test_hash_pass_runs_once(tmp_path, make):
    _write_install(tmp_path)
    svc = make()
    svc.check_sizes()
    svc.start_hash_check()
    first = svc._hash_task
    svc.start_hash_check()
    assert svc._hash_task is first
    await svc.get_report()
