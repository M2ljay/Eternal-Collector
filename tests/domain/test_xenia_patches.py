"""Tests for domain.xenia_patches — Xenia Canary .patch.toml files, read and switched line by line."""

from __future__ import annotations

import pytest

from domain.xenia_patches import PATCH_FILE_RE, patch_file_title_id, xenia_patches, xenia_set_patch

_FILE = (
    'title_name = "Halo 3"\r\n'
    'title_id = "4d5307e6"\r\n'
    'hash = ["A0E13F1B4A1A6F1E"]\r\n'
    "\r\n"
    "[[patch]]\r\n"
    '    name = "60 FPS"\r\n'
    '    desc = "Unlocks the frame rate"\r\n'
    "    is_enabled = false  # needs a fast PC\r\n"
    "\r\n"
    "    [[patch.be32]]\r\n"
    "        address = 0x82000000\r\n"
    "        value = 0x60000000\r\n"
    "\r\n"
    "[[patch]]\r\n"
    "    name = 'Disable HUD'\r\n"
    "\r\n"
    "    [[patch.be8]]\r\n"
    "        address = 0x82000004\r\n"
    "        value = 0x00\r\n"
)


def test_file_name_pattern():
    assert PATCH_FILE_RE.match("4D5307E6 - Halo 3.patch.toml")
    assert not PATCH_FILE_RE.match("Halo 3.patch.toml")


def test_title_id_is_read_from_the_top():
    assert patch_file_title_id(_FILE) == "4D5307E6"
    assert patch_file_title_id('[[patch]]\ntitle_id = "1"\n') is None


def test_lists_patches_with_state_and_defaults():
    listing = xenia_patches(_FILE, "4D5307E6.patch.toml")
    assert [(e.name, e.description, e.enabled, e.can_toggle) for e in listing.entries] == [
        ("60 FPS", "Unlocks the frame rate", False, True),
        ("Disable HUD", "", False, True),
    ]
    assert listing.editable is True


def test_switching_keeps_spacing_and_comment():
    out = xenia_set_patch(_FILE, "60 FPS", True)
    assert out is not None
    assert "    is_enabled = true  # needs a fast PC\r\n" in out
    assert xenia_patches(out, "x").entries[0].enabled is True


def test_a_block_without_is_enabled_gets_one_after_its_name():
    out = xenia_set_patch(_FILE, "Disable HUD", True)
    assert out is not None
    assert "    name = 'Disable HUD'\r\n    is_enabled = true\r\n" in out


@pytest.mark.parametrize(
    "text",
    [
        '[[patch]]\nname = "A"\ndesc = """multi\nline"""\n',
        '[[patch]]\ndesc = "no name"\n',
        '[[patch]]\nname = "A"\n[[patch]]\nname = "A"\n',
        '[[patch]]\nname = "A"\nis_enabled = "yes"\n',
    ],
)
def test_layouts_not_edited_here_are_read_only(text):
    listing = xenia_patches(text, "x.patch.toml")
    assert listing.editable is False
    assert xenia_set_patch(text, "A", True) is None


def test_unknown_name_is_refused():
    assert xenia_set_patch(_FILE, "Nope", True) is None
