"""Tests for the platform-name cache decoder and the shown-name overrides."""

from __future__ import annotations

import pytest

from domain.platform_names import (
    PLATFORM_NAME_OVERRIDES,
    decode_platform_names,
    decode_romm_platform_names,
    platform_renames,
    shown_platform_name,
    shown_platform_names,
)


class TestDecodePlatformNames:
    def test_decodes_valid_object(self):
        raw = '{"snes": "Super Nintendo", "n64": "Nintendo 64"}'
        assert decode_platform_names(raw) == {"snes": "Super Nintendo", "n64": "Nintendo 64"}

    def test_empty_object_round_trips(self):
        assert decode_platform_names("{}") == {}

    @pytest.mark.parametrize("raw", [None, ""])
    def test_absent_value_yields_empty(self, raw):
        assert decode_platform_names(raw) == {}

    def test_invalid_json_yields_empty(self):
        assert decode_platform_names("not json at all {") == {}

    @pytest.mark.parametrize("raw", ['"a json string, not a dict"', "[1, 2, 3]", "42", "true", "null"])
    def test_non_object_json_yields_empty(self, raw):
        # A corrupt cache must degrade to the slug, never surface a non-dict.
        assert decode_platform_names(raw) == {}


class TestOverrides:
    @pytest.mark.parametrize("slug", ["ps", "psx"])
    def test_ps1_is_shown_as_playstation_1_under_both_romm_slugs(self, slug):
        assert shown_platform_name(slug, "PlayStation") == "PlayStation 1"

    def test_matches_the_slug_never_the_name(self):
        assert shown_platform_name("ps2", "PlayStation") == "PlayStation"
        assert shown_platform_name("snes", "Super Nintendo") == "Super Nintendo"

    def test_every_override_is_a_non_empty_name(self):
        assert all(name.strip() for name in PLATFORM_NAME_OVERRIDES.values())

    def test_shown_names_apply_every_override(self):
        assert shown_platform_names({"psx": "PlayStation", "ps2": "PlayStation 2"}) == {
            "psx": "PlayStation 1",
            "ps2": "PlayStation 2",
        }


class TestPlatformRenames:
    def test_maps_romm_name_to_shown_name(self):
        assert platform_renames({"psx": "PlayStation", "n64": "Nintendo 64"}) == {"PlayStation": "PlayStation 1"}

    def test_a_platform_already_named_as_shown_is_no_rename(self):
        assert platform_renames({"psx": "playstation 1"}) == {}

    def test_an_empty_romm_name_is_no_rename(self):
        assert platform_renames({"psx": ""}) == {}


class TestDecodeShownAndRomm:
    def test_decode_shows_the_override_and_the_romm_decode_keeps_romm_names(self):
        raw = '{"psx": "PlayStation", "ps2": "PlayStation 2"}'
        assert decode_platform_names(raw) == {"psx": "PlayStation 1", "ps2": "PlayStation 2"}
        assert decode_romm_platform_names(raw) == {"psx": "PlayStation", "ps2": "PlayStation 2"}

    def test_non_string_names_are_dropped(self):
        assert decode_romm_platform_names('{"psx": 7, "n64": "Nintendo 64"}') == {"n64": "Nintendo 64"}
