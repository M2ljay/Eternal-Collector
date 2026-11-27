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


# ── repair from the kept release zip ───────────────────────────────


class _MemoryRepairStore:
    """``InstallRepairStore`` over an in-memory zip and the real folder, recording what it wrote."""

    def __init__(self, root, members, *, archive: str | None = "romm-dock-0.33.0-win.19.zip", fail=()):
        self._root = root
        self._members = members
        self._archive = archive
        self._fail = set(fail)
        self.written: list[str] = []
        self.asked_version: str | None = None

    def cached_release(self, version):
        self.asked_version = version
        return None if self._archive is None else f"/runtime/plugin-update/download/{self._archive}"

    def read_members(self, archive_path, rel_paths):
        return {p: self._members[p] for p in rel_paths if p in self._members}

    def write_file(self, rel_path, data):
        if rel_path in self._fail:
            raise PermissionError(13, "in use", rel_path)
        path = self._root.joinpath(*rel_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.written.append(rel_path)


def _kept_zip(root, files=FILES):
    return {"install-manifest.json": (root / "install-manifest.json").read_bytes(), **files}


def _with_store(tmp_path, store, loop):
    return InstallIntegrityService(
        config=InstallIntegrityServiceConfig(
            loop=loop,
            logger=logging.getLogger("test"),
            scanner=InstallFileAdapter(str(tmp_path)),
            current_version="0.33.0-win.19",
            repair_store=store,
        )
    )


def test_pre_import_pass_restores_missing_files_from_the_kept_zip(tmp_path, caplog):
    _write_install(tmp_path)
    (tmp_path / "py_modules" / "services" / "game_mods.py").unlink()
    store = _MemoryRepairStore(tmp_path, _kept_zip(tmp_path))
    svc = _with_store(tmp_path, store, None)
    with caplog.at_level(logging.INFO):
        report = svc.check_sizes_and_repair()
    assert report.status == "ok"
    assert store.asked_version == "0.33.0-win.19"
    assert store.written == ["py_modules/services/game_mods.py"]
    assert (tmp_path / "py_modules" / "services" / "game_mods.py").read_bytes() == FILES[
        "py_modules/services/game_mods.py"
    ]
    assert svc.repaired == ("py_modules/services/game_mods.py",)
    assert svc.repair_source == "romm-dock-0.33.0-win.19.zip"
    assert "incomplete" not in caplog.text
    assert "restored 1 file(s)" in caplog.text


def test_pre_import_pass_restores_a_truncated_file(tmp_path):
    _write_install(tmp_path)
    (tmp_path / "main.py").write_bytes(b"imp")
    store = _MemoryRepairStore(tmp_path, _kept_zip(tmp_path))
    assert _with_store(tmp_path, store, None).check_sizes_and_repair().status == "ok"
    assert (tmp_path / "main.py").read_bytes() == FILES["main.py"]


async def test_hash_pass_repair_asks_for_a_restart(tmp_path):
    _write_install(tmp_path)
    (tmp_path / "main.py").write_bytes(b"import DECKY\n")
    store = _MemoryRepairStore(tmp_path, _kept_zip(tmp_path))
    svc = _with_store(tmp_path, store, asyncio.get_running_loop())
    assert svc.check_sizes().status == "ok"
    report = await svc.get_report()
    assert report["status"] == "ok"
    assert report["hashes_checked"] is True
    assert report["repaired"] == ["main.py"]
    assert report["repair_source"] == "romm-dock-0.33.0-win.19.zip"
    assert report["restart_needed"] is True


async def test_a_clean_report_carries_no_repair(tmp_path, make):
    _write_install(tmp_path)
    report = await make().get_report()
    assert report["repaired"] == []
    assert report["repair_source"] is None
    assert report["restart_needed"] is False


def test_no_kept_zip_leaves_the_folder_incomplete(tmp_path):
    _write_install(tmp_path)
    (tmp_path / "plugin.json").unlink()
    store = _MemoryRepairStore(tmp_path, {}, archive=None)
    report = _with_store(tmp_path, store, None).check_sizes_and_repair()
    assert report.status == "incomplete"
    assert store.written == []


def test_a_zip_of_another_build_is_never_used(tmp_path, caplog):
    _write_install(tmp_path)
    (tmp_path / "plugin.json").unlink()
    members = {**_kept_zip(tmp_path), "install-manifest.json": b'{"format": 1, "version": "other", "files": []}'}
    store = _MemoryRepairStore(tmp_path, members)
    with caplog.at_level(logging.WARNING):
        report = _with_store(tmp_path, store, None).check_sizes_and_repair()
    assert report.status == "incomplete"
    assert store.written == []
    assert "is not this build" in caplog.text


def test_a_member_that_does_not_match_the_manifest_is_not_written(tmp_path):
    _write_install(tmp_path)
    (tmp_path / "plugin.json").unlink()
    (tmp_path / "main.py").unlink()
    members = {**_kept_zip(tmp_path), "plugin.json": b"{X"}
    store = _MemoryRepairStore(tmp_path, members)
    svc = _with_store(tmp_path, store, None)
    report = svc.check_sizes_and_repair()
    assert store.written == ["main.py"]
    assert report.missing == ("plugin.json",)
    assert not (tmp_path / "plugin.json").exists()


def test_a_member_the_zip_lacks_stays_missing(tmp_path):
    _write_install(tmp_path)
    (tmp_path / "plugin.json").unlink()
    members = _kept_zip(tmp_path)
    del members["plugin.json"]
    store = _MemoryRepairStore(tmp_path, members)
    assert _with_store(tmp_path, store, None).check_sizes_and_repair().missing == ("plugin.json",)


def test_a_locked_file_is_reported_and_the_rest_restored(tmp_path, caplog):
    _write_install(tmp_path)
    (tmp_path / "plugin.json").unlink()
    (tmp_path / "main.py").unlink()
    store = _MemoryRepairStore(tmp_path, _kept_zip(tmp_path), fail={"main.py"})
    with caplog.at_level(logging.WARNING):
        report = _with_store(tmp_path, store, None).check_sizes_and_repair()
    assert store.written == ["plugin.json"]
    assert report.missing == ("main.py",)
    assert "could not restore main.py" in caplog.text


def test_leftover_files_are_never_touched(tmp_path):
    _write_install(tmp_path)
    stale = tmp_path / "py_modules" / "services" / "downloads.py"
    stale.write_bytes(b"OLD = 1\n")
    store = _MemoryRepairStore(tmp_path, _kept_zip(tmp_path))
    report = _with_store(tmp_path, store, None).check_sizes_and_repair()
    assert report.status == "stale_files"
    assert store.written == []
    assert stale.exists()


def test_note_repaired_carries_an_earlier_pass(tmp_path):
    svc = _with_store(tmp_path, None, None)
    svc.note_repaired((), "ignored.zip")
    assert svc.repair_source is None
    svc.note_repaired(("main.py",), "romm-dock-0.33.0-win.19.zip")
    svc.note_repaired(("main.py",), "romm-dock-0.33.0-win.19.zip")
    assert svc.repaired == ("main.py",)
