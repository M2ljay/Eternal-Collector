"""Tests for the ``RaGameJournal`` aggregate and its ``AchievementGoal`` value object."""

from __future__ import annotations

from typing import Any

import pytest

from domain.ra_game_journal import (
    MAX_DESCRIPTION_CHARS,
    MAX_GOALS_PER_GAME,
    MAX_NOTES_CHARS,
    MAX_TITLE_CHARS,
    AchievementGoal,
    RaGameJournal,
)

AT = "2026-11-26T10:00:00+00:00"


def _goal(achievement_id: int = 1, **overrides: Any) -> AchievementGoal:
    fields: dict[str, Any] = {
        "achievement_id": achievement_id,
        "title": f"Goal {achievement_id}",
        "description": "Do the thing",
        "points": 10,
        "pinned_at": AT,
    }
    fields.update(overrides)
    return AchievementGoal.pinned(**fields)


def _journal() -> RaGameJournal:
    return RaGameJournal.opened(ra_game_id=77, game_title="Sonic the Hedgehog")


class TestGoal:
    def test_a_fresh_goal_is_open(self):
        goal = _goal()
        assert not goal.done
        assert goal.unlocked_at is None
        assert goal.unlocked_hardcore is False

    def test_title_and_description_are_trimmed_and_clipped(self):
        goal = _goal(title="  " + "t" * 300 + "  ", description="d" * 900)
        assert len(goal.title) == MAX_TITLE_CHARS
        assert len(goal.description) == MAX_DESCRIPTION_CHARS

    @pytest.mark.parametrize(
        "overrides",
        [
            {"achievement_id": 0},
            {"achievement_id": -4},
            {"achievement_id": True},
            {"achievement_id": "12"},
            {"points": -1},
            {"points": 1001},
            {"points": True},
            {"points": "5"},
            {"title": "   "},
            {"title": ""},
            {"pinned_at": ""},
        ],
    )
    def test_rejects_an_impossible_goal(self, overrides):
        with pytest.raises(ValueError):
            _goal(**overrides)

    def test_wire_shape(self):
        assert _goal(5).to_wire() == {
            "achievement_id": 5,
            "title": "Goal 5",
            "description": "Do the thing",
            "points": 10,
            "pinned_at": AT,
            "unlocked_at": None,
            "unlocked_hardcore": False,
        }


class TestOpened:
    def test_an_opened_journal_is_empty(self):
        journal = _journal()
        assert journal.is_empty
        assert journal.goals == []
        assert journal.notes == ""

    @pytest.mark.parametrize(("ra_game_id", "title"), [(0, "Sonic"), (-1, "Sonic"), (True, "Sonic"), (5, "  ")])
    def test_rejects_a_bad_identity(self, ra_game_id, title):
        with pytest.raises(ValueError):
            RaGameJournal.opened(ra_game_id=ra_game_id, game_title=title)

    def test_retitle_follows_the_game_and_ignores_blank(self):
        journal = _journal()
        journal.retitle("  Sonic 1  ")
        assert journal.game_title == "Sonic 1"
        journal.retitle("   ")
        assert journal.game_title == "Sonic 1"


class TestNotes:
    def test_write_and_clear(self):
        journal = _journal()
        journal.write_notes("  Use the spin dash  ", at=AT)
        assert journal.notes == "Use the spin dash"
        assert journal.notes_updated_at == AT
        assert not journal.is_empty
        journal.write_notes("   ", at="later")
        assert journal.notes == ""
        assert journal.notes_updated_at is None
        assert journal.is_empty

    def test_exactly_the_limit_is_accepted(self):
        journal = _journal()
        journal.write_notes("n" * MAX_NOTES_CHARS, at=AT)
        assert len(journal.notes) == MAX_NOTES_CHARS

    def test_over_the_limit_is_refused_whole(self):
        journal = _journal()
        journal.write_notes("keep me", at=AT)
        with pytest.raises(ValueError):
            journal.write_notes("n" * (MAX_NOTES_CHARS + 1), at="later")
        assert journal.notes == "keep me"


class TestGoals:
    def test_pin_is_idempotent(self):
        journal = _journal()
        assert journal.pin_goal(_goal(1)) is True
        assert journal.pin_goal(_goal(1, title="Other")) is False
        assert [g.title for g in journal.goals] == ["Goal 1"]

    def test_pin_refuses_past_the_limit(self):
        journal = _journal()
        for i in range(1, MAX_GOALS_PER_GAME + 1):
            journal.pin_goal(_goal(i))
        with pytest.raises(ValueError):
            journal.pin_goal(_goal(MAX_GOALS_PER_GAME + 1))
        assert journal.pin_goal(_goal(1)) is False

    def test_unpin(self):
        journal = _journal()
        journal.pin_goal(_goal(1))
        journal.pin_goal(_goal(2))
        assert journal.unpin_goal(1) is True
        assert journal.unpin_goal(1) is False
        assert journal.open_goal_ids() == [2]

    def test_unlock_ticks_off_only_a_pinned_goal(self):
        journal = _journal()
        journal.pin_goal(_goal(1))
        assert journal.record_unlock(99, unlocked_at=AT, hardcore=True) is False
        assert journal.record_unlock(1, unlocked_at="", hardcore=True) is False
        assert journal.record_unlock(1, unlocked_at=AT, hardcore=False) is True
        assert journal.goals[0].done
        assert journal.open_goal_ids() == []

    def test_unlock_only_moves_forward(self):
        journal = _journal()
        journal.pin_goal(_goal(1))
        journal.record_unlock(1, unlocked_at="soft", hardcore=False)
        assert journal.record_unlock(1, unlocked_at="soft again", hardcore=False) is False
        assert journal.record_unlock(1, unlocked_at="hard", hardcore=True) is True
        assert journal.goals[0].unlocked_at == "hard"
        assert journal.goals[0].unlocked_hardcore is True
        assert journal.record_unlock(1, unlocked_at="soft later", hardcore=False) is False
        assert journal.record_unlock(1, unlocked_at="hard later", hardcore=True) is False
        assert journal.goals[0].unlocked_at == "hard"

    def test_wire_shape(self):
        journal = _journal()
        journal.pin_goal(_goal(3))
        wire = journal.to_wire()
        assert wire["ra_game_id"] == 77
        assert wire["game_title"] == "Sonic the Hedgehog"
        assert [g["achievement_id"] for g in wire["goals"]] == [3]
