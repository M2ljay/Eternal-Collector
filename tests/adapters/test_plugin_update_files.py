"""Tests for ``PluginUpdateFileAdapter`` — the self-update staging folder."""

from __future__ import annotations

import hashlib
import zipfile

from adapters.plugin_update_files import PluginUpdateFileAdapter


def test_json_round_trip(tmp_path):
    files = PluginUpdateFileAdapter()
    path = str(tmp_path / "state.json")
    files.write_json(path, {"a": 1})
    assert files.read_json(path) == {"a": 1}


def test_read_json_tolerates_missing_corrupt_and_non_object(tmp_path):
    files = PluginUpdateFileAdapter()
    assert files.read_json(str(tmp_path / "missing.json")) is None
    (tmp_path / "bad.json").write_text("{nope")
    assert files.read_json(str(tmp_path / "bad.json")) is None
    (tmp_path / "list.json").write_text("[1]")
    assert files.read_json(str(tmp_path / "list.json")) is None


def test_digest_and_remove(tmp_path):
    files = PluginUpdateFileAdapter()
    target = tmp_path / "f.bin"
    target.write_bytes(b"abc")
    assert files.digest(str(target)) == (3, hashlib.sha256(b"abc").hexdigest())
    files.remove(str(target))
    files.remove(str(target))
    assert files.digest(str(target)) is None


def test_archive_folder_uses_the_top_folder_and_skips_caches_and_logs(tmp_path):
    src = tmp_path / "romm-dock"
    (src / "py_modules" / "__pycache__").mkdir(parents=True)
    (src / "bin").mkdir()
    (src / "main.py").write_text("m")
    (src / "py_modules" / "a.py").write_text("a")
    (src / "py_modules" / "__pycache__" / "a.pyc").write_bytes(b"\0")
    (src / "bin" / "rom-launcher.log").write_text("l")
    (src / "bin" / "rom-launcher.exe").write_bytes(b"MZ")
    dest = tmp_path / "out.zip"

    size, sha = PluginUpdateFileAdapter().archive_folder(str(src), "romm-dock", str(dest))

    assert (size, sha) == (dest.stat().st_size, hashlib.sha256(dest.read_bytes()).hexdigest())
    with zipfile.ZipFile(dest) as zf:
        assert sorted(zf.namelist()) == [
            "romm-dock/bin/rom-launcher.exe",
            "romm-dock/main.py",
            "romm-dock/py_modules/a.py",
        ]
        assert zf.read("romm-dock/main.py") == b"m"


def test_archive_is_reproducible(tmp_path):
    src = tmp_path / "p"
    src.mkdir()
    (src / "main.py").write_text("m")
    files = PluginUpdateFileAdapter()
    first = files.archive_folder(str(src), "p", str(tmp_path / "1.zip"))
    second = files.archive_folder(str(src), "p", str(tmp_path / "2.zip"))
    assert first == second
