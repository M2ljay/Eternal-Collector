"""Tests for ``PluginFolderHandleRegistry``."""

from __future__ import annotations

import logging

from adapters.plugin_folder_handles import PluginFolderHandleRegistry


def test_releases_every_holder_and_reports_failures(caplog):
    registry = PluginFolderHandleRegistry(logging.getLogger("test"))
    calls = []
    registry.register("a", lambda: calls.append("a"))

    def boom():
        raise OSError("locked")

    registry.register("b", boom)
    registry.register("c", lambda: calls.append("c"))
    with caplog.at_level(logging.WARNING):
        assert registry.release_all() == ["b"]
    assert calls == ["a", "c"]
    assert "locked" in caplog.text


def test_empty_registry_releases_nothing():
    assert PluginFolderHandleRegistry(logging.getLogger("test")).release_all() == []


def test_re_registering_a_name_replaces_it():
    registry = PluginFolderHandleRegistry(logging.getLogger("test"))
    calls = []
    registry.register("a", lambda: calls.append(1))
    registry.register("a", lambda: calls.append(2))
    registry.release_all()
    assert calls == [2]
