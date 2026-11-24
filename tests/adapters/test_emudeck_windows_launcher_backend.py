"""Tests for adapters.emudeck_windows_launcher_backend — standalone save roots."""

from __future__ import annotations

import logging
import os

import pytest

from adapters.emudeck_windows_launcher_backend import EmuDeckWindowsLauncherBackend


def _backend(settings: dict[str, str]) -> EmuDeckWindowsLauncherBackend:
    return EmuDeckWindowsLauncherBackend(
        installation_id="emudeck:test",
        settings=settings,
        appdata="/appdata",
        user_profile="/home/v",
        resolve_system=lambda slug, _fs: slug,
        logger=logging.getLogger("test"),
        path_exists=lambda _p: False,
    )


class TestStandaloneSavesPath:
    @pytest.mark.parametrize(
        ("emulator_id", "folder"),
        [("melonds", "melonds"), ("duckstation", "duckstation"), ("vita3k", "Vita3K")],
    )
    def test_under_emudecks_saves_root(self, emulator_id, folder):
        backend = _backend({"savesPath": "C:\\Emulation\\saves"})
        assert backend.standalone_saves_path(emulator_id) == os.path.join("C:\\Emulation\\saves", folder, "saves")

    def test_follows_the_configured_saves_root(self):
        backend = _backend({"savesPath": "/mnt/d/Emu/saves"})
        assert backend.standalone_saves_path("melonds") == os.path.join("/mnt/d/Emu/saves", "melonds", "saves")

    def test_unknown_emulator_is_empty(self):
        backend = _backend({"savesPath": "C:\\Emulation\\saves"})
        assert backend.standalone_saves_path("pcsx2") == ""
        assert backend.standalone_saves_path("") == ""

    def test_no_saves_root_is_empty(self):
        assert _backend({}).standalone_saves_path("melonds") == ""
        assert _backend({"savesPath": ""}).standalone_saves_path("vita3k") == ""

    def test_retroarch_saves_path_unchanged(self):
        backend = _backend({"savesPath": "C:\\Emulation\\saves"})
        assert backend.saves_path() == os.path.join("C:\\Emulation\\saves", "retroarch", "saves")
