"""In-memory ``RetroAchievementsWebApi`` for service tests: canned answers, recorded calls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.errors import RaWebApiError


class FakeRetroAchievementsWeb:
    """Answers from ``timeline`` / ``games``; ``error`` (or ``game_errors[id]``) raises instead."""

    def __init__(self) -> None:
        self.timeline: Any = []
        self.games: dict[int, Any] = {}
        self.error: RaWebApiError | None = None
        self.game_errors: dict[int, RaWebApiError] = {}
        self.verify_error: RaWebApiError | None = None
        self.calls: list[tuple[Any, ...]] = []

    def get_achievements_earned_between(self, username: str, from_epoch: int, to_epoch: int) -> Any:
        self.calls.append(("earned_between", username, from_epoch, to_epoch))
        if self.error is not None:
            raise self.error
        return self.timeline

    def get_game_info_and_user_progress(self, username: str, game_id: int) -> Any:
        self.calls.append(("game", username, game_id))
        if self.error is not None:
            raise self.error
        if game_id in self.game_errors:
            raise self.game_errors[game_id]
        return self.games.get(game_id, {})

    def verify_credentials(self, username: str, api_key: str) -> None:
        self.calls.append(("verify", username, api_key))
        if self.verify_error is not None:
            raise self.verify_error
