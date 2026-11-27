"""RaGameJournal — the user's own goals and notes for one RetroAchievements game.

Identity is the RetroAchievements game id, not a RomM ``rom_id``: every version of
a game shares one achievement set, and the journal is the user's own writing, held
nowhere else. Keying it on a ROM would let a deliberate purge of that ROM row cascade
it away, so it outlives every ROM that points at it.

A goal is an achievement the user pinned, with the title, description and points it
had when pinned, so the cross-game goals list reads without a network round trip.
A goal is ticked off by :meth:`RaGameJournal.record_unlock` once an unlock is seen.

Invariants enforced here:

1. ``ra_game_id > 0`` and ``game_title`` is never empty.
2. ``notes`` is stripped and at most :data:`MAX_NOTES_CHARS` characters; empty notes
   carry no ``notes_updated_at``.
3. Each achievement is pinned at most once, and a journal holds at most
   :data:`MAX_GOALS_PER_GAME` goals.
4. An unlock only ever moves forward: unlocked stays unlocked, and a softcore unlock
   can be upgraded to hardcore but never the other way.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final

from domain._aggregate import cosmic_aggregate

MAX_NOTES_CHARS: Final = 4000
MAX_GOALS_PER_GAME: Final = 100
MAX_TITLE_CHARS: Final = 200
MAX_DESCRIPTION_CHARS: Final = 500
MAX_POINTS: Final = 1000


def _clip(text: str, limit: int) -> str:
    return text.strip()[:limit]


@dataclass(frozen=True, slots=True)
class AchievementGoal:
    """One pinned achievement, with what it looked like when pinned and whether it is unlocked."""

    achievement_id: int
    title: str
    description: str
    points: int
    pinned_at: str
    unlocked_at: str | None
    unlocked_hardcore: bool

    @classmethod
    def pinned(
        cls,
        *,
        achievement_id: object,
        title: str,
        description: str,
        points: object,
        pinned_at: str,
    ) -> AchievementGoal:
        """A fresh, not yet unlocked goal; raises ``ValueError`` on an impossible shape.

        Title and description are trimmed and clipped to their length limits.
        """
        if isinstance(achievement_id, bool) or not isinstance(achievement_id, int) or achievement_id <= 0:
            raise ValueError(f"achievement id must be a positive integer, got {achievement_id!r}")
        if isinstance(points, bool) or not isinstance(points, int) or not 0 <= points <= MAX_POINTS:
            raise ValueError(f"achievement points must be 0..{MAX_POINTS}, got {points!r}")
        clean_title = _clip(title, MAX_TITLE_CHARS)
        if not clean_title:
            raise ValueError("a goal needs the achievement's title")
        if not pinned_at:
            raise ValueError("a goal needs the instant it was pinned")
        return cls(
            achievement_id=achievement_id,
            title=clean_title,
            description=_clip(description, MAX_DESCRIPTION_CHARS),
            points=points,
            pinned_at=pinned_at,
            unlocked_at=None,
            unlocked_hardcore=False,
        )

    @property
    def done(self) -> bool:
        """Whether the achievement has been seen unlocked."""
        return self.unlocked_at is not None

    def to_wire(self) -> dict[str, Any]:
        """The JSON shape the frontend reads."""
        return {
            "achievement_id": self.achievement_id,
            "title": self.title,
            "description": self.description,
            "points": self.points,
            "pinned_at": self.pinned_at,
            "unlocked_at": self.unlocked_at,
            "unlocked_hardcore": self.unlocked_hardcore,
        }


@cosmic_aggregate
class RaGameJournal:
    """Goals and notes for one RetroAchievements game, keyed by its game id."""

    ra_game_id: int
    game_title: str
    notes: str
    notes_updated_at: str | None
    goals: list[AchievementGoal]

    @classmethod
    def opened(cls, *, ra_game_id: object, game_title: str) -> RaGameJournal:
        """An empty journal for one game; raises ``ValueError`` on a bad id or empty title."""
        if isinstance(ra_game_id, bool) or not isinstance(ra_game_id, int) or ra_game_id <= 0:
            raise ValueError(f"RetroAchievements game id must be a positive integer, got {ra_game_id!r}")
        title = game_title.strip()
        if not title:
            raise ValueError("a journal needs the game's title")
        return cls(ra_game_id=ra_game_id, game_title=title, notes="", notes_updated_at=None, goals=[])

    @property
    def is_empty(self) -> bool:
        """No notes and no goals: nothing of the user's is left to keep."""
        return not self.notes and not self.goals

    def retitle(self, game_title: str) -> None:
        """Follow the game's current title; a blank title is ignored."""
        title = game_title.strip()
        if title:
            self.game_title = title

    def write_notes(self, text: str, *, at: str) -> None:
        """Replace the notes with *text*, trimmed; empty text clears them.

        Raises ``ValueError`` when the trimmed text is longer than :data:`MAX_NOTES_CHARS`:
        the user's writing is refused whole, never silently cut.
        """
        clean = text.strip()
        if len(clean) > MAX_NOTES_CHARS:
            raise ValueError(f"notes are limited to {MAX_NOTES_CHARS} characters, got {len(clean)}")
        self.notes = clean
        self.notes_updated_at = at if clean else None

    def pin_goal(self, goal: AchievementGoal) -> bool:
        """Pin *goal*; ``False`` when that achievement is already pinned.

        Raises ``ValueError`` when the journal already holds :data:`MAX_GOALS_PER_GAME` goals.
        """
        if any(existing.achievement_id == goal.achievement_id for existing in self.goals):
            return False
        if len(self.goals) >= MAX_GOALS_PER_GAME:
            raise ValueError(f"a game holds at most {MAX_GOALS_PER_GAME} goals")
        self.goals.append(goal)
        return True

    def unpin_goal(self, achievement_id: int) -> bool:
        """Remove the goal for *achievement_id*; ``False`` when it was not pinned."""
        kept = [goal for goal in self.goals if goal.achievement_id != achievement_id]
        if len(kept) == len(self.goals):
            return False
        self.goals = kept
        return True

    def record_unlock(self, achievement_id: int, *, unlocked_at: str, hardcore: bool) -> bool:
        """Tick off the goal for *achievement_id*; ``True`` when anything changed.

        An achievement that is not a goal, an empty date, and an unlock that adds
        nothing (already unlocked, or softcore over hardcore) change nothing.
        """
        if not unlocked_at:
            return False
        for index, goal in enumerate(self.goals):
            if goal.achievement_id != achievement_id:
                continue
            if goal.done and (goal.unlocked_hardcore or not hardcore):
                return False
            self.goals[index] = replace(goal, unlocked_at=unlocked_at, unlocked_hardcore=hardcore)
            return True
        return False

    def open_goal_ids(self) -> list[int]:
        """The achievement ids of the goals not yet unlocked, in pin order."""
        return [goal.achievement_id for goal in self.goals if not goal.done]

    def to_wire(self) -> dict[str, Any]:
        """The JSON shape the frontend reads."""
        return {
            "ra_game_id": self.ra_game_id,
            "game_title": self.game_title,
            "notes": self.notes,
            "notes_updated_at": self.notes_updated_at,
            "goals": [goal.to_wire() for goal in self.goals],
        }
