"""In-memory ``RetroAchievementsConfigReader`` implementation for service tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.retroachievements import RaStatus


class FakeRetroAchievementsConfigReader:
    """Returns a preset status and login-failure answer, and records what was asked.

    ``status=None`` models a missing settings file.
    """

    def __init__(self, *, status: RaStatus | None = None, login_failed: bool = False) -> None:
        self.status = status
        self.login_failed = login_failed
        self.status_calls: list[tuple[str, str]] = []
        self.log_calls: list[tuple[str, str, float]] = []

    def read_status(self, emulator_id: str, emulator_dir: str) -> RaStatus | None:
        self.status_calls.append((emulator_id, emulator_dir))
        return self.status

    def login_failed_since(self, emulator_id: str, emulator_dir: str, since: float) -> bool:
        self.log_calls.append((emulator_id, emulator_dir, since))
        return self.login_failed
