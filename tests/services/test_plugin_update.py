"""Tests for ``PluginUpdateService`` — the fork's self-update channel.

The refusal paths are the point: nothing is handed to Decky's installer unless the
downloaded file matches ``update.json`` in both size and SHA-256, the channel is
the fork's own, and the installed build was snapshotted first.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fakes.fake_plugin_release_source import FakePluginReleaseSource
from fakes.system_time import FakeClock

from adapters.plugin_update_files import PluginUpdateFileAdapter
from domain.plugin_release import ARTIFACT_URL, CHECK_INTERVAL_SECONDS, MANIFEST_URL
from services.plugin_update import PluginUpdateService, PluginUpdateServiceConfig

CURRENT = "0.33.0-win.16"
ARTIFACT = b"PK\x03\x04 pretend this is romm-dock.zip"


def _manifest_bytes(version="0.33.0-win.17", artifact=ARTIFACT, **overrides) -> bytes:
    payload = {
        "version": version,
        "sha256": hashlib.sha256(artifact).hexdigest(),
        "size": len(artifact),
        "notes": "What changed",
        "url": ARTIFACT_URL,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


@pytest.fixture
def plugin_dir(tmp_path):
    root = tmp_path / "plugins" / "romm-dock"
    (root / "py_modules" / "__pycache__").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "main.py").write_text("print('installed')\n")
    (root / "py_modules" / "x.py").write_text("X = 1\n")
    (root / "py_modules" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"\0")
    (root / "bin" / "rom-launcher.log").write_text("log\n")
    return str(root)


@pytest.fixture
def source():
    return FakePluginReleaseSource(manifest=_manifest_bytes(), artifact=ARTIFACT)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_service(tmp_path, plugin_dir, source, clock):
    def _make(
        *,
        current=CURRENT,
        platform_supported=True,
        release_source=source,
        files=None,
        running_executables=None,
        folder_handles=None,
    ):
        return PluginUpdateService(
            config=PluginUpdateServiceConfig(
                loop=asyncio.get_running_loop(),
                logger=logging.getLogger("test"),
                log_debug=MagicMock(),
                clock=clock,
                release_source=release_source,
                files=files if files is not None else PluginUpdateFileAdapter(),
                current_version=current,
                plugin_dir=plugin_dir,
                staging_dir=str(tmp_path / "runtime" / "plugin-update"),
                platform_supported=platform_supported,
                running_executables=running_executables,
                launcher_name="rom-launcher.exe",
                folder_handles=folder_handles,
            )
        )

    return _make


class TestSupport:
    async def test_linux_build_is_left_to_the_store(self, make_service, source):
        svc = make_service(platform_supported=False)
        result = await svc.check_for_update(force=True)
        assert result == {"success": True, "supported": False, "current": CURRENT, "update_available": False}
        assert source.manifest_urls == []

    async def test_non_fork_version_is_unsupported(self, make_service, source):
        svc = make_service(current="0.33.0")
        assert (await svc.check_for_update())["supported"] is False
        assert source.manifest_urls == []

    async def test_prepare_refuses_when_unsupported(self, make_service):
        result = await make_service(platform_supported=False).prepare_update()
        assert result["success"] is False
        assert result["reason"] == "unsupported"
        assert result["message"]

    async def test_rollback_unavailable_when_unsupported(self, make_service):
        assert await make_service(platform_supported=False).get_rollback() == {"success": True, "available": False}


class TestCheck:
    async def test_reports_a_newer_build(self, make_service, source):
        result = await make_service().check_for_update()
        assert result["success"] is True
        assert result["update_available"] is True
        assert result["version"] == "0.33.0-win.17"
        assert result["notes"] == "What changed"
        assert result["size"] == len(ARTIFACT)
        assert source.manifest_urls[0].startswith(MANIFEST_URL + "?t=")

    async def test_double_digit_build_counts_as_newer(self, make_service, source):
        source.manifest = _manifest_bytes(version="0.33.0-win.10")
        result = await make_service(current="0.33.0-win.9").check_for_update()
        assert result["update_available"] is True

    async def test_same_build_is_not_an_update(self, make_service, source):
        source.manifest = _manifest_bytes(version=CURRENT)
        assert (await make_service().check_for_update())["update_available"] is False

    async def test_reads_the_channel_at_most_once_per_interval(self, make_service, source, clock):
        svc = make_service()
        await svc.check_for_update()
        await svc.check_for_update()
        assert len(source.manifest_urls) == 1
        clock.advance(CHECK_INTERVAL_SECONDS + 1)
        await svc.check_for_update()
        assert len(source.manifest_urls) == 2

    async def test_force_reads_now(self, make_service, source):
        svc = make_service()
        await svc.check_for_update()
        await svc.check_for_update(force=True)
        assert len(source.manifest_urls) == 2

    async def test_last_answer_survives_a_restart(self, make_service, source):
        await make_service().check_for_update()
        result = await make_service().check_for_update()
        assert len(source.manifest_urls) == 1
        assert result["update_available"] is True

    async def test_unreachable_channel(self, make_service, source):
        source.manifest_error = "HTTP 404 from the release channel"
        result = await make_service().check_for_update()
        assert result == {
            "success": False,
            "reason": "server_unreachable",
            "message": "HTTP 404 from the release channel",
            "current": CURRENT,
        }

    async def test_invalid_json(self, make_service, source):
        source.manifest = b"<html>"
        result = await make_service().check_for_update()
        assert result["success"] is False
        assert result["reason"] == "manifest_invalid"

    async def test_foreign_artifact_url_is_refused(self, make_service, source):
        source.manifest = _manifest_bytes(url="https://example.com/romm-dock.zip")
        result = await make_service().check_for_update()
        assert result["success"] is False
        assert result["reason"] == "manifest_invalid"


class TestPrepare:
    async def test_verified_download_is_handed_on_as_a_file_artifact(self, make_service, source, tmp_path):
        result = await make_service().prepare_update()
        assert result["success"] is True
        assert result["version"] == "0.33.0-win.17"
        assert result["sha256"] == hashlib.sha256(ARTIFACT).hexdigest()
        assert result["size"] == len(ARTIFACT)
        assert result["artifact"].startswith("file://")
        path = result["artifact"][len("file://") :]
        assert Path(path).read_bytes() == ARTIFACT
        assert source.download_urls[0].startswith(ARTIFACT_URL + "?t=")

    async def test_rereads_the_manifest_even_when_a_check_is_cached(self, make_service, source):
        svc = make_service()
        await svc.check_for_update()
        await svc.prepare_update()
        assert len(source.manifest_urls) == 2

    async def test_size_mismatch_is_refused_and_discarded(self, make_service, source, tmp_path):
        source.artifact = ARTIFACT + b"extra"
        result = await make_service().prepare_update()
        assert result["success"] is False
        assert result["reason"] == "size_mismatch"
        assert "Nothing was installed" in result["message"]
        assert not _downloads(tmp_path)

    async def test_hash_mismatch_is_refused_and_discarded(self, make_service, source, tmp_path):
        source.artifact = b"X" * len(ARTIFACT)
        result = await make_service().prepare_update()
        assert result["success"] is False
        assert result["reason"] == "hash_mismatch"
        assert result["message"]
        assert not _downloads(tmp_path)

    async def test_up_to_date_is_refused(self, make_service, source):
        source.manifest = _manifest_bytes(version=CURRENT)
        result = await make_service().prepare_update()
        assert result["success"] is False
        assert result["reason"] == "up_to_date"
        assert source.download_urls == []

    async def test_download_failure(self, make_service, source):
        source.download_error = "Downloading the update failed: reset"
        result = await make_service().prepare_update()
        assert result["success"] is False
        assert result["reason"] == "server_unreachable"
        assert result["message"] == "Downloading the update failed: reset"

    async def test_unreachable_manifest_stops_before_download(self, make_service, source):
        source.manifest_error = "boom"
        result = await make_service().prepare_update()
        assert result["reason"] == "server_unreachable"
        assert source.download_urls == []

    async def test_snapshot_failure_refuses_the_update(self, make_service):
        files = PluginUpdateFileAdapter()
        files.archive_folder = MagicMock(side_effect=OSError("disk full"))
        result = await make_service(files=files).prepare_update()
        assert result["success"] is False
        assert result["reason"] == "backup_failed"
        assert "disk full" in result["message"]

    async def test_installed_build_is_snapshotted_in_its_own_folder(self, make_service, tmp_path):
        await make_service().prepare_update()
        snapshot = tmp_path / "runtime" / "plugin-update" / "previous" / "romm-dock-previous.zip"
        with zipfile.ZipFile(snapshot) as zf:
            names = set(zf.namelist())
        assert names == {"romm-dock/main.py", "romm-dock/py_modules/x.py"}


class TestRollback:
    async def test_offered_after_an_update(self, make_service):
        await make_service().prepare_update()
        after = make_service(current="0.33.0-win.17")
        result = await after.get_rollback()
        assert result["success"] is True
        assert result["available"] is True
        assert result["version"] == CURRENT
        assert result["artifact"].startswith("file://")
        path = result["artifact"][len("file://") :]
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == result["sha256"]

    async def test_not_offered_for_the_running_build(self, make_service):
        svc = make_service()
        await svc.prepare_update()
        assert await svc.get_rollback() == {"success": True, "available": False}

    async def test_not_offered_when_nothing_was_kept(self, make_service):
        assert await make_service().get_rollback() == {"success": True, "available": False}

    async def test_not_offered_when_the_snapshot_changed(self, make_service, tmp_path):
        await make_service().prepare_update()
        snapshot = tmp_path / "runtime" / "plugin-update" / "previous" / "romm-dock-previous.zip"
        snapshot.write_bytes(b"tampered")
        result = await make_service(current="0.33.0-win.17").get_rollback()
        assert result == {"success": True, "available": False}


def _downloads(tmp_path) -> list[str]:
    folder = tmp_path / "runtime" / "plugin-update" / "download"
    return os.listdir(folder) if folder.exists() else []


class _Handles:
    def __init__(self, failing=()):
        self.released = 0
        self.failing = list(failing)

    def register(self, name, release):
        raise AssertionError("not used")

    def release_all(self):
        self.released += 1
        return self.failing


class TestPrepareGuards:
    async def test_refuses_while_a_launched_game_runs(self, make_service, source):
        handles = _Handles()
        svc = make_service(
            running_executables=lambda: frozenset({"explorer.exe", "rom-launcher.exe"}), folder_handles=handles
        )
        result = await svc.prepare_update()
        assert result["success"] is False
        assert result["reason"] == "game_running"
        assert "Close it first" in result["message"]
        assert source.download_urls == []
        assert handles.released == 0

    async def test_other_processes_do_not_block(self, make_service):
        handles = _Handles()
        svc = make_service(running_executables=lambda: frozenset({"explorer.exe"}), folder_handles=handles)
        result = await svc.prepare_update()
        assert result["success"] is True
        assert result["install_type"] == 2
        assert handles.released == 1

    async def test_unreadable_process_table_does_not_block(self, make_service):
        result = await make_service(running_executables=lambda: None).prepare_update()
        assert result["success"] is True

    async def test_game_started_during_download_refuses_and_discards(self, make_service, tmp_path):
        answers = iter([frozenset(), frozenset({"rom-launcher.exe"})])
        handles = _Handles()
        svc = make_service(running_executables=lambda: next(answers), folder_handles=handles)
        result = await svc.prepare_update()
        assert result["reason"] == "game_running"
        assert handles.released == 0
        download = tmp_path / "runtime" / "plugin-update" / "download"
        assert list(download.iterdir()) == []

    async def test_handle_release_failure_is_logged_not_fatal(self, make_service, caplog):
        svc = make_service(folder_handles=_Handles(failing=["gavel native core"]))
        with caplog.at_level(logging.WARNING):
            result = await svc.prepare_update()
        assert result["success"] is True
        assert "gavel native core" in caplog.text

    async def test_refused_download_releases_nothing(self, make_service, source):
        source.manifest = _manifest_bytes(size=len(ARTIFACT) + 1)
        handles = _Handles()
        result = await make_service(folder_handles=handles).prepare_update()
        assert result["reason"] == "size_mismatch"
        assert handles.released == 0


class TestPrepareReinstall:
    async def test_same_version_is_a_reinstall_without_snapshot(self, make_service, source, tmp_path):
        source.manifest = _manifest_bytes(version=CURRENT)
        handles = _Handles()
        result = await make_service(folder_handles=handles).prepare_reinstall()
        assert result["success"] is True
        assert result["version"] == CURRENT
        assert result["install_type"] == 1
        assert result["artifact"].startswith("file://")
        assert handles.released == 1
        assert not (tmp_path / "runtime" / "plugin-update" / "previous").exists()

    async def test_newer_version_is_an_update(self, make_service):
        result = await make_service().prepare_reinstall()
        assert result["success"] is True
        assert result["install_type"] == 2

    async def test_older_channel_is_refused(self, make_service, source):
        source.manifest = _manifest_bytes(version="0.33.0-win.15")
        result = await make_service().prepare_reinstall()
        assert result["success"] is False
        assert result["reason"] == "channel_older"
        assert source.download_urls == []

    async def test_reinstall_keeps_the_previous_snapshot(self, make_service, source, tmp_path):
        assert (await make_service().prepare_update())["success"] is True
        record = tmp_path / "runtime" / "plugin-update" / "previous" / "previous.json"
        before = record.read_bytes()
        source.manifest = _manifest_bytes(version=CURRENT)
        assert (await make_service().prepare_reinstall())["success"] is True
        assert record.read_bytes() == before

    async def test_reinstall_refuses_while_a_game_runs(self, make_service):
        svc = make_service(running_executables=lambda: frozenset({"rom-launcher.exe"}))
        assert (await svc.prepare_reinstall())["reason"] == "game_running"

    async def test_hash_mismatch_is_refused(self, make_service, source):
        source.manifest = _manifest_bytes(version=CURRENT, sha256="0" * 64)
        result = await make_service().prepare_reinstall()
        assert result["reason"] == "hash_mismatch"

    async def test_unsupported_platform(self, make_service):
        result = await make_service(platform_supported=False).prepare_reinstall()
        assert result["reason"] == "unsupported"
