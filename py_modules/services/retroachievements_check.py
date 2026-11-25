"""RetroAchievementsCheckService — the "RetroAchievements isn't working" notice for a launched ROM.

Owns the decision whether a game session that just started (or just ended)
deserves one notice that RetroAchievements will not (or did not) earn
anything: the emulator the ROM's recorded launch command runs, whether that
emulator and platform support RetroAchievements, and what the emulator's own
settings and log say. It never blocks play and answers at most once per
session: a session warned at start is not checked again at its end.

Credentials are out of scope by construction: the config reader answers in
booleans, so no username or token value reaches this service.
"""

from __future__ import annotations

import ntpath
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.retroachievements import (
    emulator_exe_from_command,
    has_login_log_check,
    identify_emulator,
    login_failed_warning,
    platform_supports_ra,
    ra_warning,
)

if TYPE_CHECKING:
    import asyncio

    from services.protocols import Clock, DebugLogger, RetroAchievementsConfigReader, UnitOfWorkFactory

SETTING_KEY = "retroachievements_warning"


@dataclass(frozen=True)
class RetroAchievementsCheckServiceConfig:
    """Frozen wiring bundle handed to ``RetroAchievementsCheckService.__init__``.

    Carries the event loop and Unit-of-Work factory (to read the ROM's
    platform and recorded launch command off the loop thread), the live
    settings dict (for the user's on/off switch), the boolean-only emulator
    config reader, the clock that stamps a session's start, and the debug
    logger.
    """

    loop: asyncio.AbstractEventLoop
    uow_factory: UnitOfWorkFactory
    settings: dict[str, Any]
    config_reader: RetroAchievementsConfigReader
    clock: Clock
    log_debug: DebugLogger


@dataclass(frozen=True)
class _PendingLogCheck:
    emulator_id: str
    display_name: str
    emulator_dir: str
    started_at: float


class RetroAchievementsCheckService:
    """Session-start config check and session-end log check for RetroAchievements."""

    def __init__(self, *, config: RetroAchievementsCheckServiceConfig) -> None:
        self._loop = config.loop
        self._uow_factory = config.uow_factory
        self._settings = config.settings
        self._config_reader = config.config_reader
        self._clock = config.clock
        self._log_debug = config.log_debug
        self._pending: dict[int, _PendingLogCheck] = {}

    async def check_session_start(self, rom_id: int) -> dict[str, str | None]:
        """Return ``{"warning": <notice or None>}`` for the session *rom_id* just started.

        A notice comes back only when the warning is switched on, the ROM's
        recorded launch command runs a RetroAchievements emulator on a
        platform RetroAchievements covers, and that emulator's settings say
        achievements are off or no login is stored. A missing settings file,
        an unknown emulator and any error answer ``None``: the check must
        never be the reason a game appears broken. When the settings look
        fine and the emulator logs logins, the session is remembered for
        :meth:`check_session_end`.
        """
        self._pending.pop(rom_id, None)
        if not self._settings.get(SETTING_KEY, True):
            return {"warning": None}
        try:
            return {"warning": await self._loop.run_in_executor(None, self._check_start_io, rom_id)}
        except Exception as exc:
            self._log_debug(f"retroachievements: start check for rom {rom_id} failed: {exc}")
            return {"warning": None}

    async def check_session_end(self, rom_id: int) -> dict[str, str | None]:
        """Return ``{"warning": <notice or None>}`` for the session *rom_id* just ended.

        Only a session :meth:`check_session_start` passed and remembered is
        checked, so a session warned at its start gets no second notice. The
        notice reports a login failure the emulator logged during the session.
        """
        pending = self._pending.pop(rom_id, None)
        if pending is None or not self._settings.get(SETTING_KEY, True):
            return {"warning": None}
        try:
            failed = await self._loop.run_in_executor(
                None,
                self._config_reader.login_failed_since,
                pending.emulator_id,
                pending.emulator_dir,
                pending.started_at,
            )
        except Exception as exc:
            self._log_debug(f"retroachievements: end check for rom {rom_id} failed: {exc}")
            return {"warning": None}
        return {"warning": login_failed_warning(pending.display_name) if failed else None}

    def _check_start_io(self, rom_id: int) -> str | None:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
        if rom is None:
            return None
        exe = emulator_exe_from_command(rom.applied_launch_options)
        emulator = identify_emulator(exe) if exe else None
        if exe is None or emulator is None or not platform_supports_ra(emulator.emulator_id, rom.platform_slug):
            return None
        emulator_dir = ntpath.dirname(exe)
        status = self._config_reader.read_status(emulator.emulator_id, emulator_dir)
        if status is None:
            self._log_debug(f"retroachievements: no {emulator.display_name} settings found for rom {rom_id}")
            return None
        self._log_debug(
            f"retroachievements: {emulator.display_name} rom {rom_id} "
            f"enabled={status.enabled} signed_in={status.signed_in}"
        )
        warning = ra_warning(emulator.display_name, status)
        if warning is None and has_login_log_check(emulator.emulator_id):
            self._pending[rom_id] = _PendingLogCheck(
                emulator_id=emulator.emulator_id,
                display_name=emulator.display_name,
                emulator_dir=emulator_dir,
                started_at=self._clock.time(),
            )
        return warning
