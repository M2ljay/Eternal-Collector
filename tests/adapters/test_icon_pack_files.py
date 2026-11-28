"""Tests for ``IconPackFilesAdapter`` over a generated pack in a temp folder (never the real pack)."""

from __future__ import annotations

import os

import pytest

from adapters.icon_pack_files import IconPackFilesAdapter


@pytest.fixture
def appdata(tmp_path):
    root = tmp_path / "GamingMode" / "icons" / "colorgrade" / "families" / "nintendo"
    root.mkdir(parents=True)
    (root / "logo.png").write_bytes(b"generated logo")
    (root / "hero.png").write_bytes(b"x" * 64)
    return tmp_path


def test_reads_a_file_under_the_pack(appdata):
    adapter = IconPackFilesAdapter(appdata=str(appdata))
    assert adapter.read_art(("families", "nintendo", "logo.png"), 1024) == b"generated logo"


def test_missing_file_folder_or_appdata_answer_none(appdata, tmp_path):
    assert IconPackFilesAdapter(appdata=str(appdata)).read_art(("families", "sega", "logo.png"), 1024) is None
    assert (
        IconPackFilesAdapter(appdata=str(tmp_path / "nowhere")).read_art(("families", "nintendo", "logo.png"), 1024)
        is None
    )
    assert IconPackFilesAdapter(appdata=None).read_art(("families", "nintendo", "logo.png"), 1024) is None


def test_a_file_over_the_limit_is_not_read(appdata):
    assert IconPackFilesAdapter(appdata=str(appdata)).read_art(("families", "nintendo", "hero.png"), 63) is None


def test_a_path_that_escapes_the_pack_is_refused(appdata):
    outside = appdata / "secret.png"
    outside.write_bytes(b"not pack art")
    adapter = IconPackFilesAdapter(appdata=str(appdata))
    assert adapter.read_art(("..", "..", "..", "secret.png"), 1024) is None


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_a_symlink_out_of_the_pack_is_refused(appdata):
    outside = appdata / "outside.png"
    outside.write_bytes(b"outside")
    link = appdata / "GamingMode" / "icons" / "colorgrade" / "families" / "nintendo" / "icon.png"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks not permitted")
    assert IconPackFilesAdapter(appdata=str(appdata)).read_art(("families", "nintendo", "icon.png"), 1024) is None
