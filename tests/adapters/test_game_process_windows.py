"""Tests for adapters.game_process_windows — the part that needs no Win32: running executable names."""

from __future__ import annotations

from adapters.game_process_windows import WindowsGameProcessAdapter


class TestRunningExecutableNames:
    def test_lower_cased_names(self, monkeypatch):
        adapter = WindowsGameProcessAdapter()
        monkeypatch.setattr(adapter, "_process_table", lambda: {1: (0, "Dolphin.exe"), 2: (1, "explorer.exe")})
        assert adapter.running_executable_names() == frozenset({"dolphin.exe", "explorer.exe"})

    def test_unreadable_table_is_unknown(self, monkeypatch):
        adapter = WindowsGameProcessAdapter()
        monkeypatch.setattr(adapter, "_process_table", dict)
        assert adapter.running_executable_names() is None

    def test_win32_failure_is_unknown(self, monkeypatch):
        adapter = WindowsGameProcessAdapter()

        def boom():
            raise OSError("no kernel32")

        monkeypatch.setattr(adapter, "_process_table", boom)
        assert adapter.running_executable_names() is None
