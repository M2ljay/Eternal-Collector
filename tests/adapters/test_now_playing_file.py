"""Tests for NowPlayingFileAdapter — the shared file's atomic writes."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from adapters.now_playing_file import NowPlayingFileAdapter


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "data" / "eternal-now-playing" / "now-playing.json")


def test_write_creates_the_folder_and_round_trips(path):
    store = NowPlayingFileAdapter(path=path)
    assert store.read() is None
    store.write({"v": 1, "records": {"1": {"app_id": 1, "name": "Pokémon Red"}}})
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["records"]["1"]["name"] == "Pokémon Red"
    assert store.read() == {"v": 1, "records": {"1": {"app_id": 1, "name": "Pokémon Red"}}}


def test_corrupt_or_oversized_files_read_as_none(path, tmp_path):
    store = NowPlayingFileAdapter(path=path)
    store.write({"v": 1, "records": {}})
    with open(path, "w", encoding="utf-8") as f:
        f.write("{half")
    assert store.read() is None
    with open(path, "w", encoding="utf-8") as f:
        f.write(" " * (64 * 1024 + 1))
    assert store.read() is None


def test_a_failed_write_keeps_the_previous_file_and_leaves_no_temporary(path):
    store = NowPlayingFileAdapter(path=path)
    store.write({"v": 1, "records": {"1": {"app_id": 1}}})
    with patch("adapters.now_playing_file.os.replace", side_effect=OSError("locked")), pytest.raises(OSError):
        store.write({"v": 1, "records": {}})
    assert store.read() == {"v": 1, "records": {"1": {"app_id": 1}}}
    assert not os.path.exists(path + ".tmp")


def test_remove_is_idempotent(path):
    store = NowPlayingFileAdapter(path=path)
    store.remove()
    store.write({"v": 1, "records": {}})
    store.remove()
    store.remove()
    assert store.read() is None
