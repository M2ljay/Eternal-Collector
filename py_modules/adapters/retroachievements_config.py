"""Emulator RetroAchievements settings adapter — file reads behind the RA readiness check.

Reads an emulator's own settings files (and, where one is written by default,
its log) from the folder holding the emulator's exe, and hands the text
straight to the pure parsers in ``domain.retroachievements``. Only their
boolean answers leave this module: the text is never kept, returned or logged,
and PPSSPP's token file is only ever measured, never opened.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from domain.retroachievements import (
    DOLPHIN,
    DOLPHIN_RA_INI,
    DUCKSTATION,
    DUCKSTATION_INI,
    PCSX2,
    PCSX2_INI,
    PCSX2_LOG,
    PCSX2_SECRETS_INI,
    PPSSPP,
    PPSSPP_INI,
    PPSSPP_TOKEN_FILE,
    RETROARCH,
    RETROARCH_CFG,
    RaStatus,
    dolphin_status,
    duckstation_status,
    pcsx2_login_failed,
    pcsx2_status,
    ppsspp_status,
    retroarch_status,
)

if TYPE_CHECKING:
    import logging

# A log stamped up to this many seconds before the session started still
# counts as that session's: file-time granularity and the gap between Steam
# starting the emulator and the plugin hearing about it.
_LOG_SLACK_SECONDS = 5.0


class RetroAchievementsConfigAdapter:
    """Reads emulator RetroAchievements settings and answers in booleans."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def read_status(self, emulator_id: str, emulator_dir: str) -> RaStatus | None:
        """Whether RetroAchievements is enabled and signed in, or ``None`` when the settings file is missing.

        ``None`` also covers an unreadable file and an emulator this adapter
        does not know — the caller treats all of them as "cannot tell".
        """
        if emulator_id == PCSX2:
            ini = self._read(emulator_dir, PCSX2_INI)
            return None if ini is None else pcsx2_status(ini, self._read(emulator_dir, PCSX2_SECRETS_INI))
        if emulator_id == DUCKSTATION:
            ini = self._read(emulator_dir, DUCKSTATION_INI)
            return None if ini is None else duckstation_status(ini)
        if emulator_id == DOLPHIN:
            ini = self._read(emulator_dir, DOLPHIN_RA_INI)
            return None if ini is None else dolphin_status(ini)
        if emulator_id == PPSSPP:
            ini = self._read(emulator_dir, PPSSPP_INI)
            if ini is None:
                return None
            return ppsspp_status(ini, token_file_nonempty=self._nonempty(emulator_dir, PPSSPP_TOKEN_FILE))
        if emulator_id == RETROARCH:
            cfg = self._read(emulator_dir, RETROARCH_CFG)
            return None if cfg is None else retroarch_status(cfg)
        return None

    def login_failed_since(self, emulator_id: str, emulator_dir: str, since: float) -> bool:
        """Whether the emulator's log, written at or after *since*, records a failed login.

        ``False`` for an emulator without a default log, a missing log, and a
        log older than the session (a previous run's).
        """
        if emulator_id != PCSX2:
            return False
        path = os.path.join(emulator_dir, *PCSX2_LOG)
        try:
            if os.path.getmtime(path) < since - _LOG_SLACK_SECONDS:
                return False
        except OSError:
            return False
        text = self._read(emulator_dir, PCSX2_LOG)
        return text is not None and pcsx2_login_failed(text)

    def _read(self, emulator_dir: str, parts: tuple[str, ...]) -> str | None:
        path = os.path.join(emulator_dir, *parts)
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            self._logger.warning("retroachievements: cannot read %s: %s", path, exc.strerror)
            return None

    @staticmethod
    def _nonempty(emulator_dir: str, parts: tuple[str, ...]) -> bool:
        try:
            return os.path.getsize(os.path.join(emulator_dir, *parts)) > 0
        except OSError:
            return False
