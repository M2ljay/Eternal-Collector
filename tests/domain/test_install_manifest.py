"""Tests for ``domain.install_manifest`` — manifest parsing and the size/hash verdicts."""

from __future__ import annotations

import json

import pytest

from domain.install_manifest import (
    INCOMPLETE,
    OK,
    STALE_FILES,
    UNCHECKED,
    InstallManifestError,
    compare_sizes,
    is_safe_relative,
    parse_manifest,
    unchecked,
    unreadable_manifest,
    with_hashes,
)

A = "a" * 64
B = "b" * 64


def _raw(files=None, **overrides) -> bytes:
    payload = {
        "format": 1,
        "version": "0.33.0-win.19",
        "files": files
        if files is not None
        else [
            {"path": "main.py", "size": 10, "sha256": A},
            {"path": "py_modules/services/game_mods.py", "size": 20, "sha256": B},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


class TestParse:
    def test_reads_version_and_entries(self):
        manifest = parse_manifest(_raw())
        assert manifest.version == "0.33.0-win.19"
        assert manifest.paths() == {"main.py", "py_modules/services/game_mods.py"}

    @pytest.mark.parametrize(
        "raw",
        [
            b"not json",
            b"\xff\xfe",
            json.dumps([]).encode(),
            _raw(format=2),
            _raw(version=""),
            _raw(files="nope"),
            _raw(files=["x"]),
            _raw(files=[{"path": "../evil", "size": 1, "sha256": A}]),
            _raw(files=[{"path": "C:/evil", "size": 1, "sha256": A}]),
            _raw(files=[{"path": "a\\\\b", "size": 1, "sha256": A}]),
            _raw(files=[{"path": "a", "size": -1, "sha256": A}]),
            _raw(files=[{"path": "a", "size": True, "sha256": A}]),
            _raw(files=[{"path": "a", "size": 1, "sha256": "ABC"}]),
            _raw(files=[{"path": "a", "size": 1, "sha256": A}, {"path": "a", "size": 1, "sha256": A}]),
        ],
    )
    def test_rejects_unusable_manifests(self, raw):
        with pytest.raises(InstallManifestError):
            parse_manifest(raw)

    def test_empty_file_list_is_valid(self):
        assert parse_manifest(_raw(files=[])).entries == ()

    @pytest.mark.parametrize(
        ("path", "safe"),
        [("main.py", True), ("a/b.py", True), ("", False), ("/a", False), ("a//b", False), ("a/./b", False)],
    )
    def test_safe_relative(self, path, safe):
        assert is_safe_relative(path) is safe


class TestCompareSizes:
    def test_all_present_is_ok(self):
        m = parse_manifest(_raw())
        report = compare_sizes(
            m,
            {"main.py": 10, "py_modules/services/game_mods.py": 20},
            frozenset({"py_modules/services/game_mods.py"}),
            frozenset(),
        )
        assert report.status == OK
        assert report.hashes_checked is False

    def test_missing_file_is_incomplete(self):
        m = parse_manifest(_raw())
        report = compare_sizes(m, {"main.py": 10, "py_modules/services/game_mods.py": None}, frozenset(), frozenset())
        assert report.status == INCOMPLETE
        assert report.missing == ("py_modules/services/game_mods.py",)

    def test_size_mismatch_is_incomplete(self):
        m = parse_manifest(_raw())
        report = compare_sizes(
            m,
            {"main.py": 11, "py_modules/services/game_mods.py": 20},
            frozenset({"py_modules/services/game_mods.py"}),
            frozenset(),
        )
        assert report.status == INCOMPLETE
        assert report.mismatched == ("main.py",)

    def test_extra_py_files_are_stale_and_shadowing_is_named(self):
        m = parse_manifest(_raw())
        present = frozenset(
            {"py_modules/services/game_mods.py", "py_modules/services/downloads.py", "py_modules/services/old.py"}
        )
        report = compare_sizes(
            m,
            {"main.py": 10, "py_modules/services/game_mods.py": 20},
            present,
            frozenset({"py_modules/services/downloads"}),
        )
        assert report.status == STALE_FILES
        assert report.extra == ("py_modules/services/downloads.py", "py_modules/services/old.py")
        assert report.shadowing == ("py_modules/services/downloads.py",)

    def test_missing_wins_over_extra(self):
        m = parse_manifest(_raw())
        report = compare_sizes(m, {}, frozenset({"py_modules/x.py"}), frozenset())
        assert report.status == INCOMPLETE


class TestWithHashes:
    def test_matching_hashes_stay_ok(self):
        m = parse_manifest(_raw())
        sizes = compare_sizes(m, {"main.py": 10, "py_modules/services/game_mods.py": 20}, frozenset(), frozenset())
        report = with_hashes(sizes, m, {"main.py": A, "py_modules/services/game_mods.py": B})
        assert report.status == OK
        assert report.hashes_checked is True

    def test_wrong_or_unreadable_hash_is_incomplete(self):
        m = parse_manifest(_raw())
        sizes = compare_sizes(m, {"main.py": 10, "py_modules/services/game_mods.py": 20}, frozenset(), frozenset())
        report = with_hashes(sizes, m, {"main.py": B, "py_modules/services/game_mods.py": None})
        assert report.status == INCOMPLETE
        assert report.mismatched == ("main.py", "py_modules/services/game_mods.py")


def test_unchecked_and_unreadable_reports():
    assert unchecked("dev").status == UNCHECKED
    bad = unreadable_manifest("broken")
    assert bad.status == INCOMPLETE
    assert bad.to_dict()["detail"] == "broken"
