"""Tests for the console shelf's pure rules (``domain/console_shelf.py``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.console_shelf import (
    HALF_LIFE_DAYS,
    ShelfGame,
    achievement_badge,
    continue_game,
    newest_instant,
    order_console_games,
    rank_consoles,
    recency_weight,
)
from domain.rom_achievement_progress import RomAchievementProgress

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _game(rom_id: int, slug: str, seconds: int = 0, last: str | None = None, name: str | None = None) -> ShelfGame:
    return ShelfGame(
        rom_id=rom_id,
        app_id=5000 + rom_id,
        name=name or f"Game {rom_id}",
        platform_slug=slug,
        play_seconds=seconds,
        last_played=last,
    )


class TestRecencyWeight:
    def test_played_now_weighs_one(self):
        assert recency_weight(NOW.isoformat(), NOW.timestamp()) == pytest.approx(1.0)

    def test_halves_every_half_life(self):
        assert recency_weight(_ago(HALF_LIFE_DAYS), NOW.timestamp()) == pytest.approx(0.5)
        assert recency_weight(_ago(2 * HALF_LIFE_DAYS), NOW.timestamp()) == pytest.approx(0.25)

    @pytest.mark.parametrize("instant", [None, "", "not a date"])
    def test_unknown_instant_weighs_zero(self, instant):
        assert recency_weight(instant, NOW.timestamp()) == 0.0

    def test_future_instant_weighs_one(self):
        assert recency_weight((NOW + timedelta(days=3)).isoformat(), NOW.timestamp()) == 1.0

    def test_trailing_z_is_understood(self):
        assert recency_weight("2026-11-26T12:00:00Z", NOW.timestamp()) == pytest.approx(1.0)


class TestNewestInstant:
    def test_picks_latest_and_skips_garbage(self):
        assert newest_instant([_ago(5), None, "x", _ago(1), _ago(3)]) == _ago(1)

    def test_none_when_nothing_parses(self):
        assert newest_instant([None, "nope"]) is None
        assert newest_instant([]) is None


class TestRankConsoles:
    def test_recent_play_beats_an_old_binge(self):
        games = [
            _game(1, "ps2", seconds=100 * 3600, last=_ago(720)),  # 100 h, two years ago
            _game(2, "ngc", seconds=10 * 3600, last=_ago(2)),
        ]
        ranked = rank_consoles(games, {"ps2": "PlayStation 2", "ngc": "GameCube"}, NOW.timestamp())
        assert [e.platform_slug for e in ranked] == ["ngc", "ps2"]
        assert ranked[0].name == "GameCube"

    def test_entry_totals_and_newest_last_played(self):
        games = [_game(1, "snes", 60, _ago(10)), _game(2, "snes", 40, _ago(1)), _game(3, "snes")]
        [entry] = rank_consoles(games, {}, NOW.timestamp())
        assert entry.game_count == 3
        assert entry.play_seconds == 100
        assert entry.last_played == _ago(1)
        assert entry.name == "snes"  # falls back to the slug

    def test_unplayed_consoles_go_last_by_game_count_then_name(self):
        games = [
            _game(1, "n64"),
            _game(2, "gba"),
            _game(3, "gba"),
            _game(4, "psx"),
            _game(5, "snes", seconds=1, last=_ago(400)),
        ]
        ranked = rank_consoles(games, {"n64": "Nintendo 64", "psx": "PlayStation"}, NOW.timestamp())
        assert [e.platform_slug for e in ranked] == ["snes", "gba", "n64", "psx"]

    def test_ties_break_on_last_played_then_count_then_name(self):
        same = _ago(0)
        games = [
            _game(1, "b", 100, _ago(0)),
            _game(2, "a", 100, _ago(0)),
            _game(3, "c", 50, same),
            _game(4, "c", 50, same),
        ]
        ranked = rank_consoles(games, {}, NOW.timestamp())
        # Equal scores and equal last-played: the bigger console first, then by name.
        assert [e.platform_slug for e in ranked] == ["c", "a", "b"]

    def test_play_time_without_a_date_does_not_lift_a_console(self):
        games = [_game(1, "a", seconds=10_000, last=None), _game(2, "b", seconds=1, last=_ago(1))]
        assert [e.platform_slug for e in rank_consoles(games, {}, NOW.timestamp())] == ["b", "a"]

    def test_empty(self):
        assert rank_consoles([], {}, NOW.timestamp()) == []

    def test_cover_is_the_most_recently_played_game(self):
        games = [_game(1, "ps2", 500, _ago(30)), _game(2, "ps2", 10, _ago(1)), _game(3, "ps2")]
        [entry] = rank_consoles(games, {}, NOW.timestamp())
        assert entry.cover_app_id == 5002

    def test_cover_falls_back_to_the_first_game_by_name(self):
        games = [_game(1, "gba", name="Zelda"), _game(2, "gba", name="advance wars"), _game(3, "gba", name="Metroid")]
        [entry] = rank_consoles(games, {}, NOW.timestamp())
        assert entry.cover_app_id == 5002


class TestContinueAndOrder:
    def test_continue_is_most_recent(self):
        games = [_game(1, "ps2", last=_ago(3)), _game(2, "ps2", last=_ago(1)), _game(3, "ps2")]
        assert continue_game(games).rom_id == 2  # type: ignore[union-attr]

    def test_no_continue_without_play(self):
        assert continue_game([_game(1, "ps2")]) is None

    def test_order_puts_continue_first_then_names(self):
        games = [
            _game(1, "ps2", name="Zelda"),
            _game(2, "ps2", name="ape escape", last=_ago(5)),
            _game(3, "ps2", name="Okami", last=_ago(1)),
        ]
        assert [g.rom_id for g in order_console_games(games)] == [3, 2, 1]

    def test_order_without_play_is_alphabetical(self):
        games = [_game(1, "ps2", name="b"), _game(2, "ps2", name="A")]
        assert [g.rom_id for g in order_console_games(games)] == [2, 1]


def _progress(earned: int, hardcore: int, total: int = 40, kind: str | None = None) -> RomAchievementProgress:
    return RomAchievementProgress.observed(
        earned=earned, earned_hardcore=hardcore, total=total, highest_award_kind=kind, fetched_at="t"
    )


class TestAchievementBadge:
    def test_none_without_progress(self):
        assert achievement_badge(None) is None

    def test_counts_carried(self):
        badge = achievement_badge(_progress(12, 3))
        assert badge is not None
        assert (badge.earned, badge.total, badge.earned_hardcore) == (12, 40, 3)
        assert badge.hardcore is False
        assert badge.award is None

    def test_hardcore_only_when_every_unlock_was_hardcore(self):
        assert achievement_badge(_progress(5, 5)).hardcore is True  # type: ignore[union-attr]
        assert achievement_badge(_progress(0, 0)).hardcore is False  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        ("kind", "award"),
        [
            ("mastered", "mastered"),
            ("completed", "completed"),
            ("beaten-hardcore", "beaten"),
            ("beaten-softcore", "beaten"),
            ("participated", None),
            (None, None),
        ],
    )
    def test_award_marks(self, kind, award):
        assert achievement_badge(_progress(40, 40, kind=kind)).award == award  # type: ignore[union-attr]
