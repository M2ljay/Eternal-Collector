"""Tests for the achievement snapshot aggregate (``domain/rom_achievement_progress.py``)."""

from __future__ import annotations

import pytest

from domain.rom_achievement_progress import RomAchievementProgress, build_snapshot

AT = "2026-11-26T12:00:00+00:00"


class TestObserved:
    def test_valid(self):
        p = RomAchievementProgress.observed(earned=3, earned_hardcore=1, total=10, highest_award_kind="", fetched_at=AT)
        assert (p.earned, p.earned_hardcore, p.total, p.highest_award_kind, p.fetched_at) == (3, 1, 10, None, AT)

    @pytest.mark.parametrize(
        ("earned", "hardcore", "total"),
        [(1, 0, 0), (11, 0, 10), (2, 3, 10), (-1, 0, 10), (1, -1, 10)],
    )
    def test_impossible_shapes_rejected(self, earned, hardcore, total):
        with pytest.raises(ValueError):
            RomAchievementProgress.observed(
                earned=earned, earned_hardcore=hardcore, total=total, highest_award_kind=None, fetched_at=AT
            )

    def test_needs_fetched_at(self):
        with pytest.raises(ValueError):
            RomAchievementProgress.observed(
                earned=0, earned_hardcore=0, total=1, highest_award_kind=None, fetched_at=""
            )


def _entry(
    ra_id: object, earned: object = 2, hardcore: object = 1, total: object = 20, kind: object = "beaten-softcore"
):
    return {
        "rom_ra_id": ra_id,
        "num_awarded": earned,
        "num_awarded_hardcore": hardcore,
        "max_possible": total,
        "highest_award_kind": kind,
    }


class TestBuildSnapshot:
    def test_maps_by_ra_id_and_shares_between_versions(self):
        payload = {"results": [_entry(100), _entry(200, earned=20, hardcore=20, kind="mastered")]}
        snapshot = build_snapshot(payload, [(1, 100), (2, 100), (3, 200), (4, 300)], AT)
        assert set(snapshot) == {1, 2, 3}
        assert snapshot[1] == snapshot[2]
        assert snapshot[3].highest_award_kind == "mastered"
        assert snapshot[3].fetched_at == AT

    @pytest.mark.parametrize("payload", [None, {}, {"results": None}, {"results": "x"}, [], "junk"])
    def test_absent_or_malformed_payload_is_empty(self, payload):
        assert build_snapshot(payload, [(1, 100)], AT) == {}

    def test_bad_entries_are_skipped_not_guessed(self):
        payload = {
            "results": [
                "junk",
                {"rom_ra_id": "100", "max_possible": 5},
                _entry(101, total=None),
                _entry(102, earned=9, total=5),
                _entry(103, total=0),
                {"rom_ra_id": True, "max_possible": 5},
                _entry(104, earned=None, hardcore=None, kind=7),
            ]
        }
        snapshot = build_snapshot(payload, [(1, 100), (2, 101), (3, 102), (4, 103), (5, 104)], AT)
        assert set(snapshot) == {5}
        assert (snapshot[5].earned, snapshot[5].earned_hardcore, snapshot[5].highest_award_kind) == (0, 0, None)

    def test_first_entry_for_an_ra_id_wins(self):
        payload = {"results": [_entry(100, earned=1), _entry(100, earned=7)]}
        assert build_snapshot(payload, [(1, 100)], AT)[1].earned == 1
