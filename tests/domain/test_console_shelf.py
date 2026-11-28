"""Tests for the console pages' pure rules (``domain/console_shelf.py``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.console_shelf import (
    ShelfGame,
    achievement_badge,
    continue_game,
    newest_instant,
    order_console_games,
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


class TestNewestInstant:
    def test_picks_latest_and_skips_garbage(self):
        assert newest_instant([_ago(5), None, "x", _ago(1), _ago(3)]) == _ago(1)

    def test_none_when_nothing_parses(self):
        assert newest_instant([None, "nope"]) is None
        assert newest_instant([]) is None


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
