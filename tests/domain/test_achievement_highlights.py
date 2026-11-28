"""Tests for the achievements bridge's pure rules (``domain/achievement_highlights.py``)."""

from __future__ import annotations

import pytest

from domain.achievement_highlights import (
    LibraryRom,
    closest_to_complete,
    completion_percent,
    library_by_ra_game,
)
from domain.rom_achievement_progress import RomAchievementProgress


def _rom(rom_id: int, ra: int, app_id: int | None = None, name: str | None = None) -> LibraryRom:
    return LibraryRom(rom_id=rom_id, app_id=app_id, name=name or f"G{rom_id}", platform_slug="snes", ra_game_id=ra)


def _progress(earned: int, total: int) -> RomAchievementProgress:
    return RomAchievementProgress.observed(
        earned=earned, earned_hardcore=0, total=total, highest_award_kind=None, fetched_at="2026-11-26T00:00:00Z"
    )


class TestLibraryByRaGame:
    def test_prefers_the_version_in_steam_then_the_lowest_rom_id(self):
        chosen = library_by_ra_game([_rom(9, 1), _rom(4, 1, app_id=400), _rom(2, 1), _rom(7, 2), _rom(3, 2)])
        assert chosen[1].rom_id == 4
        assert chosen[2].rom_id == 3


class TestCompletionPercent:
    @pytest.mark.parametrize(("earned", "total", "percent"), [(1, 3, 33.3), (2, 3, 66.7), (5, 5, 100.0), (1, 0, 0.0)])
    def test_rounds_to_one_decimal(self, earned, total, percent):
        assert completion_percent(earned, total) == percent


class TestClosestToComplete:
    def test_orders_by_percent_and_leaves_out_zero_complete_and_unknown(self):
        library = library_by_ra_game([_rom(1, 1), _rom(2, 2), _rom(3, 3), _rom(4, 4), _rom(5, 5), _rom(6, 6)])
        progress = {
            1: _progress(1, 10),
            2: _progress(9, 10),
            3: _progress(0, 10),
            4: _progress(10, 10),
            5: _progress(1, 2),
        }
        items = closest_to_complete(library, progress, 10)
        assert [(c.rom.rom_id, c.percent) for c in items] == [(2, 90.0), (5, 50.0), (1, 10.0)]

    def test_ties_go_to_more_earned_then_name(self):
        library = library_by_ra_game([_rom(1, 1, name="b"), _rom(2, 2, name="a"), _rom(3, 3, name="c")])
        progress = {1: _progress(1, 2), 2: _progress(1, 2), 3: _progress(5, 10)}
        assert [c.rom.rom_id for c in closest_to_complete(library, progress, 10)] == [3, 2, 1]

    def test_limit(self):
        library = library_by_ra_game([_rom(i, i) for i in range(1, 6)])
        progress = {i: _progress(1, 4) for i in range(1, 6)}
        assert len(closest_to_complete(library, progress, 2)) == 2
        assert closest_to_complete(library, progress, 0) == []
