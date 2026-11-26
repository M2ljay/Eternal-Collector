"""Tests for ``domain.savestate_backup`` — the upload-or-baseline decision."""

from __future__ import annotations

import pytest

from domain.savestate_backup import (
    ADOPT_BASELINE,
    MAX_UPLOAD_BYTES,
    TOO_LARGE,
    UNCHANGED,
    UPLOAD,
    savestate_backup_action,
)

_ENABLED_AT = 1_000.0


def _action(
    *,
    local_hash: str = "h2",
    recorded_hash: str | None = "h1",
    local_mtime: float = 2_000.0,
    local_size: int = 1024,
    enabled_at: float | None = _ENABLED_AT,
) -> str:
    return savestate_backup_action(
        local_hash=local_hash,
        recorded_hash=recorded_hash,
        local_mtime=local_mtime,
        local_size=local_size,
        enabled_at=enabled_at,
    )


class TestSavestateBackupAction:
    def test_same_hash_is_unchanged_whatever_the_timestamps(self):
        assert _action(local_hash="h1", recorded_hash="h1") == UNCHANGED
        assert _action(local_hash="h1", recorded_hash="h1", local_mtime=0.0) == UNCHANGED

    def test_changed_savestate_written_after_enabling_uploads(self):
        assert _action() == UPLOAD

    def test_never_recorded_savestate_written_after_enabling_uploads(self):
        assert _action(recorded_hash=None) == UPLOAD

    def test_written_exactly_at_the_enable_moment_uploads(self):
        assert _action(local_mtime=_ENABLED_AT) == UPLOAD

    def test_savestate_older_than_the_enable_moment_is_only_baselined(self):
        assert _action(recorded_hash=None, local_mtime=_ENABLED_AT - 1) == ADOPT_BASELINE
        assert _action(local_mtime=_ENABLED_AT - 1) == ADOPT_BASELINE

    def test_missing_enable_stamp_uploads_nothing(self):
        assert _action(enabled_at=None) == ADOPT_BASELINE

    @pytest.mark.parametrize(("size", "expected"), [(MAX_UPLOAD_BYTES, UPLOAD), (MAX_UPLOAD_BYTES + 1, TOO_LARGE)])
    def test_size_ceiling(self, size, expected):
        assert _action(local_size=size) == expected

    def test_old_oversized_savestate_is_baselined_not_flagged(self):
        assert _action(local_size=MAX_UPLOAD_BYTES + 1, local_mtime=0.0) == ADOPT_BASELINE
