"""Tests for the icon pack's layout and the RomM-to-pack platform slug helper."""

from __future__ import annotations

import pytest

from domain.icon_pack import FAMILIES, PACK_PLATFORMS, family_art_parts, pack_platform_slug, platform_art_parts


def test_family_paths_come_only_from_the_allow_lists():
    assert family_art_parts("playstation", "hero") == ("families", "playstation", "hero.png")
    assert family_art_parts("retro", "logo") == ("families", "retro", "logo.png")
    assert family_art_parts("snes", "hero") is None
    assert family_art_parts("sega", "../x") is None
    assert FAMILIES == ("playstation", "nintendo", "sega", "xbox", "retro")


def test_the_pack_lists_83_platforms():
    assert len(PACK_PLATFORMS) == 83


@pytest.mark.parametrize(
    ("romm", "pack"),
    [
        ("snes", "snes"),
        ("psx", "psx"),
        ("ngc", "gc"),
        ("genesis-slash-megadrive", "genesis"),
        ("3ds", "n3ds"),
        ("dc", "dreamcast"),
        ("neo-geo-pocket-color", "ngpc"),
        ("turbografx-cd", "tg-cd"),
        ("arcade", "mame"),
        ("SNES ", "snes"),
    ],
)
def test_maps_romm_slugs_to_pack_folders(romm, pack):
    assert pack_platform_slug(romm) == pack


@pytest.mark.parametrize("romm", ["ps4", "xbox360", "unknown-thing", "", None, 3])
def test_answers_none_where_the_pack_has_no_folder(romm):
    assert pack_platform_slug(romm) is None


def test_every_mapped_slug_names_a_pack_folder():
    from domain import icon_pack

    assert set(icon_pack._PACK_SLUG_FOR.values()) <= PACK_PLATFORMS


def test_platform_paths():
    assert platform_art_parts("ngc", "icon") == ("platforms", "gc", "icon.png")
    assert platform_art_parts("ps4", "icon") is None
    assert platform_art_parts("snes", "cover") is None
