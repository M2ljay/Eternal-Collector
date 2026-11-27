"""Tests for ``InstallRepairFileAdapter`` over real zips and folders."""

from __future__ import annotations

import zipfile

import pytest

from adapters.install_repair_files import InstallRepairFileAdapter


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return str(path)


@pytest.fixture
def dirs(tmp_path):
    plugin = tmp_path / "romm-dock"
    download = tmp_path / "runtime" / "plugin-update" / "download"
    plugin.mkdir()
    download.mkdir(parents=True)
    return plugin, download


def test_finds_only_the_kept_zip_of_the_asked_version(dirs):
    plugin, download = dirs
    adapter = InstallRepairFileAdapter(str(plugin), str(download))
    assert adapter.cached_release("0.33.0-win.25") is None
    _zip(download / "romm-dock-0.33.0-win.24.zip", {"romm-dock/a": b"1"})
    assert adapter.cached_release("0.33.0-win.25") is None
    kept = _zip(download / "romm-dock-0.33.0-win.25.zip", {"romm-dock/a": b"1"})
    assert adapter.cached_release("0.33.0-win.25") == kept


def test_missing_download_folder_has_no_kept_zip(tmp_path):
    assert InstallRepairFileAdapter(str(tmp_path), str(tmp_path / "nope")).cached_release("1.0.0") is None


def test_reads_named_members_below_the_single_top_folder(dirs):
    plugin, download = dirs
    archive = _zip(
        download / "r.zip",
        {"romm-dock/install-manifest.json": b"{}", "romm-dock/py_modules/x.py": b"X = 1\n"},
    )
    adapter = InstallRepairFileAdapter(str(plugin), str(download))
    got = adapter.read_members(archive, ["install-manifest.json", "py_modules/x.py", "py_modules/absent.py"])
    assert got == {"install-manifest.json": b"{}", "py_modules/x.py": b"X = 1\n"}


def test_a_zip_with_two_top_folders_is_not_read(dirs):
    plugin, download = dirs
    archive = _zip(download / "r.zip", {"a/main.py": b"1", "b/main.py": b"2"})
    assert InstallRepairFileAdapter(str(plugin), str(download)).read_members(archive, ["main.py"]) == {}


def test_an_unreadable_zip_reads_as_empty(dirs):
    plugin, download = dirs
    bad = download / "r.zip"
    bad.write_bytes(b"not a zip")
    adapter = InstallRepairFileAdapter(str(plugin), str(download))
    assert adapter.read_members(str(bad), ["main.py"]) == {}
    assert adapter.read_members(str(download / "gone.zip"), ["main.py"]) == {}


def test_writes_atomically_creating_folders(dirs):
    plugin, download = dirs
    adapter = InstallRepairFileAdapter(str(plugin), str(download))
    adapter.write_file("py_modules/services/savestates/service.py", b"S = 1\n")
    target = plugin / "py_modules" / "services" / "savestates" / "service.py"
    assert target.read_bytes() == b"S = 1\n"
    adapter.write_file("py_modules/services/savestates/service.py", b"S = 2\n")
    assert target.read_bytes() == b"S = 2\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["service.py"]


def test_a_failed_write_leaves_no_temp_file(dirs, monkeypatch):
    import os

    plugin, download = dirs
    adapter = InstallRepairFileAdapter(str(plugin), str(download))

    def refuse(src, dst):
        raise PermissionError(13, "in use", dst)

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        adapter.write_file("main.py", b"x")
    assert list(plugin.iterdir()) == []
