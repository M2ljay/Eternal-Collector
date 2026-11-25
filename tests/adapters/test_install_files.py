"""Tests for ``InstallFileAdapter`` — the stdlib-only reads behind the install check."""

from __future__ import annotations

import hashlib

from adapters.install_files import InstallFileAdapter


def _tree(tmp_path):
    root = tmp_path / "romm-dock"
    (root / "py_modules" / "services" / "downloads" / "__pycache__").mkdir(parents=True)
    (root / "main.py").write_bytes(b"main")
    (root / "py_modules" / "services" / "downloads.py").write_bytes(b"old")
    (root / "py_modules" / "services" / "downloads" / "__init__.py").write_bytes(b"")
    (root / "py_modules" / "services" / "downloads" / "__pycache__" / "x.py").write_bytes(b"")
    return root


def test_read_file(tmp_path):
    root = _tree(tmp_path)
    adapter = InstallFileAdapter(str(root))
    assert adapter.read_file("main.py") == b"main"
    assert adapter.read_file("install-manifest.json") is None


def test_sizes_reports_absent_and_directories_as_none(tmp_path):
    adapter = InstallFileAdapter(str(_tree(tmp_path)))
    assert adapter.sizes(["main.py", "nope.py", "py_modules"]) == {"main.py": 4, "nope.py": None, "py_modules": None}


def test_python_tree_skips_pycache(tmp_path):
    files, dirs = InstallFileAdapter(str(_tree(tmp_path))).python_tree("py_modules")
    assert files == {"py_modules/services/downloads.py", "py_modules/services/downloads/__init__.py"}
    assert dirs == {"py_modules/services", "py_modules/services/downloads"}


def test_python_tree_of_missing_root_is_empty(tmp_path):
    assert InstallFileAdapter(str(tmp_path)).python_tree("py_modules") == (frozenset(), frozenset())


def test_sha256(tmp_path):
    adapter = InstallFileAdapter(str(_tree(tmp_path)))
    assert adapter.sha256("main.py") == hashlib.sha256(b"main").hexdigest()
    assert adapter.sha256("missing") is None
