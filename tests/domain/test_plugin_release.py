"""Tests for the fork's release-channel rules: version order and ``update.json`` validation."""

from __future__ import annotations

import pytest

from domain.plugin_release import (
    ARTIFACT_URL,
    LEGACY_ARTIFACT_URL,
    MANIFEST_URL,
    MAX_ARTIFACT_BYTES,
    ManifestError,
    is_fork_build,
    is_newer,
    parse_manifest,
    parse_version,
)

SHA = "a" * 64


def _manifest(**overrides):
    payload = {"version": "0.33.0-win.17", "sha256": SHA, "size": 1234, "notes": "n", "url": ARTIFACT_URL}
    payload.update(overrides)
    return payload


class TestParseVersion:
    def test_fork_build(self):
        assert parse_version("0.33.0-win.17") == (0, 33, 0, 17)

    def test_plain_release_is_build_zero(self):
        assert parse_version("0.34.0") == (0, 34, 0, 0)

    def test_leading_v_and_whitespace(self):
        assert parse_version(" v1.2.3-win.4 ") == (1, 2, 3, 4)

    @pytest.mark.parametrize("bad", ["", "0.33", "0.33.0-beta.1", "0.33.0-win", "0.33.0-win.x", "1.2.3.4", None, 7])
    def test_unreadable(self, bad):
        assert parse_version(bad) is None


class TestIsNewer:
    def test_two_digit_build_beats_one_digit(self):
        assert is_newer("0.33.0-win.9", "0.33.0-win.10")

    def test_older_and_equal_are_not_newer(self):
        assert not is_newer("0.33.0-win.10", "0.33.0-win.9")
        assert not is_newer("0.33.0-win.16", "0.33.0-win.16")

    def test_upstream_minor_bump_is_newer(self):
        assert is_newer("0.33.0-win.16", "0.34.0-win.1")

    def test_unreadable_side_is_never_newer(self):
        assert not is_newer("0.33.0-win.16", "garbage")
        assert not is_newer("garbage", "0.33.0-win.17")


class TestIsForkBuild:
    def test_win_suffix(self):
        assert is_fork_build("0.33.0-win.17")

    def test_upstream_version(self):
        assert not is_fork_build("0.33.0")


class TestParseManifest:
    def test_valid(self):
        m = parse_manifest(_manifest(notes="  Self-update  "))
        assert (m.version, m.sha256, m.size, m.notes, m.url) == (
            "0.33.0-win.17",
            SHA,
            1234,
            "Self-update",
            ARTIFACT_URL,
        )

    def test_notes_optional_and_bounded(self):
        assert parse_manifest(_manifest(notes=None)).notes == ""
        assert len(parse_manifest(_manifest(notes="x" * 5000)).notes) == 2000

    @pytest.mark.parametrize(
        "overrides",
        [
            {"version": "nope"},
            {"version": 17},
            {"sha256": "A" * 64},
            {"sha256": "a" * 63},
            {"sha256": None},
            {"size": 0},
            {"size": True},
            {"size": "1234"},
            {"size": MAX_ARTIFACT_BYTES + 1},
            {"url": "https://example.com/romm-dock.zip"},
            {"url": ARTIFACT_URL + "?x=1"},
            {"url": LEGACY_ARTIFACT_URL + "?x=1"},
            {"url": "https://raw.githubusercontent.com/M2ljay/Eternal-Collector/main/romm-dock.zip"},
            {"url": None},
        ],
    )
    def test_rejects(self, overrides):
        with pytest.raises(ManifestError):
            parse_manifest(_manifest(**overrides))

    def test_accepts_the_legacy_repository_url(self):
        # Builds up to win.17 accept only the pre-rename URL, so the channel publishes it.
        assert parse_manifest(_manifest(url=LEGACY_ARTIFACT_URL)).url == LEGACY_ARTIFACT_URL

    def test_channel_reads_the_renamed_repository(self):
        assert MANIFEST_URL == "https://raw.githubusercontent.com/M2ljay/Eternal-Collector/release/update.json"
        assert ARTIFACT_URL == "https://raw.githubusercontent.com/M2ljay/Eternal-Collector/release/romm-dock.zip"
        assert LEGACY_ARTIFACT_URL == "https://raw.githubusercontent.com/M2ljay/Eternal-Romm/release/romm-dock.zip"

    def test_rejects_non_object(self):
        with pytest.raises(ManifestError):
            parse_manifest(["not", "an", "object"])
