"""Tests for domain.rpcs3_patches — RPCS3's patch lists and patch_config.yml, over YAML read as text."""

from __future__ import annotations

from adapters.yaml_codec import YamlCodecAdapter
from domain.rpcs3_patches import (
    config_for_dump,
    entry_id,
    patch_list_subset,
    rpcs3_patches,
    rpcs3_set,
    rpcs3_target,
)

_YAML = YamlCodecAdapter()

_PATCH_YML = """Version: 1.2

Anchors:
  60fps_common: &60fps_common
    - [ be32, 0x00010000, 0x60000000 ]

PPU-b8c34f774adb367761706a7f685d4f8d9d355426:
  "60 FPS":
    Games:
      "Demon's Souls":
        BLUS30443: [ 01.00, 01.04 ]
    Author: someone
    Notes: Set the frame limit to Off.
    Patch Version: 1.0
    Patch: *60fps_common
  "Disable Blur":
    Games:
      "Demon's Souls":
        BLUS30443: [ All ]
    Patch Version: 1.0
    Patch:
      - [ be32, 0x00020000, 0x00000000 ]

PPU-0000000000000000000000000000000000000000:
  "Other game":
    Games:
      "Other":
        BLES00001: [ 01.00 ]
    Patch Version: 1.0
    Patch:
      - [ be32, 0x1, 0x2 ]
"""

_HASH = "PPU-b8c34f774adb367761706a7f685d4f8d9d355426"


def _docs():
    return [("patch.yml", _YAML.load(patch_list_subset(_PATCH_YML, "BLUS30443")))]


def test_subset_keeps_version_anchors_and_the_game_only():
    subset = patch_list_subset(_PATCH_YML, "BLUS30443")
    assert "Anchors:" in subset
    assert _HASH in subset
    assert "BLES00001" not in subset
    doc = _YAML.load(subset)
    assert doc["Version"] == "1.2"


def test_versions_stay_text_and_entries_follow_the_app_version():
    listing = rpcs3_patches(_docs(), {}, "BLUS30443", "01.04")
    by_name = {e.name: e for e in listing.entries}
    assert by_name["60 FPS"].can_toggle is True
    assert by_name["60 FPS"].notes == ("Set the frame limit to Off.",)
    assert by_name["Disable Blur"].can_toggle is True
    assert all(e.enabled is False for e in listing.entries)


def test_a_patch_for_other_versions_cannot_be_switched():
    listing = rpcs3_patches(_docs(), {}, "BLUS30443", "01.02")
    sixty = next(e for e in listing.entries if e.name == "60 FPS")
    assert sixty.can_toggle is False
    assert "this game is version 01.02" in sixty.notes[-1]


def test_switching_writes_the_keys_rpcs3_writes_and_round_trips():
    ident = entry_id(_HASH, "60 FPS", "Demon's Souls")
    where = rpcs3_target(_docs(), ident, "BLUS30443", "01.04")
    assert where == (_HASH, "60 FPS", "Demon's Souls", "01.04")
    config = rpcs3_set({}, (*where[:3], "BLUS30443", where[3]), True)
    text = _YAML.dump(config_for_dump(config))
    assert "Enabled: true" in text
    assert "'01.04'" in text
    reread = _YAML.load(text)
    listing = rpcs3_patches(_docs(), reread, "BLUS30443", "01.04")
    assert next(e for e in listing.entries if e.name == "60 FPS").enabled is True


def test_switching_off_drops_empty_maps_and_keeps_other_entries():
    key_a = (_HASH, "60 FPS", "Demon's Souls", "BLUS30443", "01.04")
    key_b = (_HASH, "Disable Blur", "Demon's Souls", "BLUS30443", "All")
    config = rpcs3_set(rpcs3_set({}, key_a, True), key_b, True)
    off = rpcs3_set(config, key_a, False)
    assert "60 FPS" not in off[_HASH]
    assert off[_HASH]["Disable Blur"]["Demon's Souls"]["BLUS30443"]["All"]["Enabled"] == "true"
    assert rpcs3_set(off, key_b, False) == {}


def test_configurable_values_survive_switching_off_as_numbers():
    key = (_HASH, "60 FPS", "Demon's Souls", "BLUS30443", "01.04")
    config = {
        _HASH: {
            "60 FPS": {
                "Demon's Souls": {
                    "BLUS30443": {"01.04": {"Enabled": "true", "Configurable Values": {"FPS": "60", "Scale": "1.5"}}}
                }
            }
        }
    }
    off = rpcs3_set(config, key, False)
    dumped = config_for_dump(off)
    values = dumped[_HASH]["60 FPS"]["Demon's Souls"]["BLUS30443"]["01.04"]["Configurable Values"]
    assert values == {"FPS": 60, "Scale": 1.5}


def test_unknown_entry_has_no_target():
    assert rpcs3_target(_docs(), "PPU-x:abc", "BLUS30443", "01.04") is None
