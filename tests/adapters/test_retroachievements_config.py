"""Tests for adapters.retroachievements_config.RetroAchievementsConfigAdapter."""

from __future__ import annotations

import builtins
import logging
import os
from typing import TYPE_CHECKING

import pytest

from adapters.retroachievements_config import RetroAchievementsConfigAdapter
from domain.retroachievements import DOLPHIN, DUCKSTATION, PCSX2, PPSSPP, RETROARCH, RaStatus

if TYPE_CHECKING:
    from pathlib import Path

SECRET = "tok3n-SECRET-value-0123456789"
PPSSPP_INI_REL = "memstick/PSP/SYSTEM/ppsspp.ini"
PPSSPP_INI_TEXT = "[Achievements]\nAchievementsEnable = True\nAchievementsUserName = u\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def adapter() -> RetroAchievementsConfigAdapter:
    return RetroAchievementsConfigAdapter(logger=logging.getLogger("test"))


class TestReadStatus:
    def test_pcsx2_reads_the_secrets_file(self, tmp_path, adapter):
        _write(tmp_path, "inis/PCSX2.ini", "[Achievements]\nEnabled = true\nUsername = u\n")
        _write(tmp_path, "inis/secrets.ini", f"[Achievements]\nToken = {SECRET}\n")
        assert adapter.read_status(PCSX2, str(tmp_path)) == RaStatus(enabled=True, signed_in=True)

    def test_pcsx2_without_secrets_is_signed_out(self, tmp_path, adapter):
        _write(tmp_path, "inis/PCSX2.ini", "[Achievements]\nEnabled = true\nUsername = u\n")
        assert adapter.read_status(PCSX2, str(tmp_path)) == RaStatus(enabled=True, signed_in=False)

    def test_duckstation(self, tmp_path, adapter):
        _write(tmp_path, "settings.ini", "[Cheevos]\nEnabled = false\n")
        assert adapter.read_status(DUCKSTATION, str(tmp_path)) == RaStatus(enabled=False, signed_in=False)

    def test_dolphin(self, tmp_path, adapter):
        ini = f"[Achievements]\nEnabled = True\nUsername = u\nApiToken = {SECRET}\n"
        _write(tmp_path, "User/Config/RetroAchievements.ini", ini)
        assert adapter.read_status(DOLPHIN, str(tmp_path)) == RaStatus(enabled=True, signed_in=True)

    def test_ppsspp_measures_the_token_file(self, tmp_path, adapter):
        _write(tmp_path, PPSSPP_INI_REL, PPSSPP_INI_TEXT)
        assert adapter.read_status(PPSSPP, str(tmp_path)) == RaStatus(enabled=True, signed_in=False)
        _write(tmp_path, "memstick/PSP/SYSTEM/ppsspp_retroachievements.dat", SECRET)
        assert adapter.read_status(PPSSPP, str(tmp_path)) == RaStatus(enabled=True, signed_in=True)

    def test_retroarch(self, tmp_path, adapter):
        cfg = f'cheevos_enable = "true"\ncheevos_username = "u"\ncheevos_token = "{SECRET}"\n'
        _write(tmp_path, "retroarch.cfg", cfg)
        assert adapter.read_status(RETROARCH, str(tmp_path)) == RaStatus(enabled=True, signed_in=True)

    def test_missing_settings_file_is_unknown(self, tmp_path, adapter):
        assert adapter.read_status(PCSX2, str(tmp_path)) is None

    def test_unknown_emulator_is_unknown(self, tmp_path, adapter):
        assert adapter.read_status("azahar", str(tmp_path)) is None

    def test_unreadable_file_is_unknown_and_logs_no_content(self, tmp_path, adapter, caplog):
        (tmp_path / "settings.ini").mkdir()
        with caplog.at_level(logging.WARNING):
            assert adapter.read_status(DUCKSTATION, str(tmp_path)) is None


class TestNoCredentialEscapes:
    def test_ppsspp_token_file_is_never_opened(self, tmp_path, adapter, monkeypatch):
        _write(tmp_path, PPSSPP_INI_REL, PPSSPP_INI_TEXT)
        token = _write(tmp_path, "memstick/PSP/SYSTEM/ppsspp_retroachievements.dat", SECRET)
        real_open = builtins.open
        opened: list[str] = []

        def spy(file, *args, **kwargs):
            opened.append(os.fspath(file))
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", spy)
        assert adapter.read_status(PPSSPP, str(tmp_path)) == RaStatus(enabled=True, signed_in=True)
        assert str(token) not in opened

    def test_results_and_logs_never_carry_the_token(self, tmp_path, adapter, caplog):
        _write(tmp_path, "inis/PCSX2.ini", f"[Achievements]\nEnabled = true\nUsername = u\nToken = {SECRET}\n")
        with caplog.at_level(logging.DEBUG):
            status = adapter.read_status(PCSX2, str(tmp_path))
        assert status == RaStatus(enabled=True, signed_in=True)
        assert SECRET not in repr(status)
        assert SECRET not in caplog.text


class TestLoginFailedSince:
    def test_pcsx2_failure_in_a_fresh_log(self, tmp_path, adapter):
        log = _write(tmp_path, "logs/emulog.txt", "Achievements error: Login failed: Invalid token\n")
        os.utime(log, (1000.0, 1000.0))
        assert adapter.login_failed_since(PCSX2, str(tmp_path), 1000.0) is True

    def test_stale_log_is_ignored(self, tmp_path, adapter):
        log = _write(tmp_path, "logs/emulog.txt", "Achievements error: Login failed: x\n")
        os.utime(log, (1000.0, 1000.0))
        assert adapter.login_failed_since(PCSX2, str(tmp_path), 2000.0) is False

    def test_clean_log(self, tmp_path, adapter):
        log = _write(tmp_path, "logs/emulog.txt", "Achievements: Game 1 loaded\n")
        os.utime(log, (1000.0, 1000.0))
        assert adapter.login_failed_since(PCSX2, str(tmp_path), 1000.0) is False

    def test_missing_log(self, tmp_path, adapter):
        assert adapter.login_failed_since(PCSX2, str(tmp_path), 0.0) is False

    def test_other_emulators_have_no_log_check(self, tmp_path, adapter):
        assert adapter.login_failed_since(DUCKSTATION, str(tmp_path), 0.0) is False
