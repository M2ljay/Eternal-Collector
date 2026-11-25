"""Tests for ``domain.save_sync_blockers`` — slugs and the sentences the UI shows."""

from __future__ import annotations

import pytest

from domain import save_sync_blockers as b


def test_file_card_sentence_is_exact():
    blocker = b.pcsx2_file_card()
    assert blocker.to_dict() == {
        "reason": "pcsx2_file_card",
        "message": (
            "PS2 saves aren't syncing: PCSX2 is using a single-file memory card. Switch slot 1 to a folder card."
        ),
    }


@pytest.mark.parametrize(
    ("kind", "detail", "ext", "reason", "fragment"),
    [
        ("unsupported_format", ".pbp", ".pbp", "disc_format_unsupported", ".pbp files"),
        (
            "unsupported_image",
            "unsupported CHD codec b'zstd'",
            ".chd",
            "disc_image_unsupported",
            "(unsupported CHD codec",
        ),
        ("unsupported_image", "", ".chd", "disc_image_unsupported", "this disc image,"),
        ("no_disc_id", "", ".iso", "disc_id_missing", "no game ID"),
        ("unreadable", "denied", ".iso", "disc_unreadable", "couldn't open"),
        (None, None, ".iso", "disc_unreadable", "couldn't open"),
    ],
)
def test_disc_problems(kind, detail, ext, reason, fragment):
    blocker = b.disc_problem("pcsx2", kind, detail, ext)
    assert blocker.reason == reason
    assert blocker.message.startswith("PS2 saves aren't syncing: ")
    assert fragment in blocker.message


def test_unknown_emulator_without_a_name():
    assert "this emulator" in b.unknown_emulator(None).message


def test_unknown_platform_label_falls_back():
    assert b.emulator_folder_unknown("mystery").message.startswith("Saves aren't syncing: ")


@pytest.mark.parametrize(
    "factory",
    [b.pcsx2_settings_unreadable, b.pcsx2_slot_empty, b.pcsx2_cards_elsewhere, b.vita_no_title_id],
)
def test_every_sentence_says_saves_are_not_syncing(factory):
    assert "saves aren't syncing:" in factory().message
