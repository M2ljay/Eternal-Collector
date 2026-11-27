"""Tests for adapters.game_mod_files — listing, installing a planned source, backing up, editing an ini."""

from __future__ import annotations

import os
import stat
import zipfile

import pytest

from adapters.game_mod_files import GameModFilesAdapter
from domain.game_mods import (
    SCOPE_GAME,
    SCOPE_PATCH,
    TARGET_SOFT_PATCH,
    TARGET_TEXTURES,
    InstallPlan,
    ModTarget,
    PlannedWrite,
    PlanRefusal,
    check_against_disk,
    plan_dirs,
    plan_install,
)


@pytest.fixture
def downloads(tmp_path):
    path = tmp_path / "Downloads"
    path.mkdir()
    return path


@pytest.fixture
def store(downloads):
    return GameModFilesAdapter(downloads_dir=str(downloads), running_executable_names=lambda: frozenset({"x.exe"}))


def _zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return str(path)


def _target(root) -> ModTarget:
    return ModTarget(TARGET_TEXTURES, "t", SCOPE_GAME, str(root), game_folder="GALE01")


def _install(store, source, target):
    entries = store.read_source_entries(source)
    plan = plan_install(target, entries)
    assert isinstance(plan, InstallPlan)
    kinds = store.probe_kinds(target.path, (*plan_dirs(plan), *(w.dest for w in plan.writes)))
    check = check_against_disk(plan, kinds)
    return plan, check


class TestSources:
    def test_list_sources_newest_first_with_limit(self, store, downloads):
        for i, name in enumerate(["a.zip", "b.zip", "c.zip"]):
            (downloads / name).write_bytes(b"x")
            os.utime(downloads / name, (1000 + i, 1000 + i))
        entries, truncated = store.list_sources(str(downloads), 2)
        assert [e.name for e in entries] == ["c.zip", "b.zip"]
        assert truncated is True

    @pytest.mark.parametrize("name", ["..", "../x", "a/b", "C:x", "", "missing.zip"])
    def test_source_path_refuses_anything_but_an_existing_child(self, store, name):
        assert store.source_path(name) is None

    def test_source_path_refuses_a_link(self, store, downloads, tmp_path):
        (tmp_path / "outside.zip").write_bytes(b"x")
        os.symlink(tmp_path / "outside.zip", downloads / "link.zip")
        assert store.source_path("link.zip") is None

    def test_source_path_ok(self, store, downloads):
        (downloads / "pack.zip").write_bytes(b"x")
        assert store.source_path("pack.zip") == os.path.join(str(downloads), "pack.zip")

    def test_stamp_changes_with_content(self, store, downloads):
        folder = downloads / "Pack"
        folder.mkdir()
        (folder / "a.png").write_bytes(b"1")
        first = store.source_stamp(str(folder))
        (folder / "b.png").write_bytes(b"22")
        assert store.source_stamp(str(folder)) != first
        assert store.source_stamp(str(downloads / "gone")) is None

    def test_folder_entries_report_links_without_entering(self, store, downloads, tmp_path):
        folder = downloads / "GALE01"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "a.png").write_bytes(b"abc")
        (tmp_path / "secret").mkdir()
        os.symlink(tmp_path / "secret", folder / "escape")
        entries = {e.name: e for e in store.read_source_entries(str(folder))}
        assert entries["GALE01/sub/a.png"].size == 3
        assert entries["GALE01/escape"].link is True
        assert not any(name.startswith("GALE01/escape/") for name in entries)

    def test_zip_symlink_member_is_marked(self, store, downloads):
        path = downloads / "l.zip"
        with zipfile.ZipFile(path, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        (entry,) = store.read_source_entries(str(path))
        assert entry.link is True

    def test_bad_zip_is_value_error(self, store, downloads):
        (downloads / "bad.zip").write_bytes(b"not a zip")
        with pytest.raises(ValueError, match="zip"):
            store.read_source_entries(str(downloads / "bad.zip"))


class TestInstall:
    def test_zip_slip_is_refused_before_anything_is_written(self, store, downloads, tmp_path):
        source = _zip(downloads / "evil.zip", {"ok.png": b"1", "../../evil.png": b"2"})
        root = tmp_path / "Textures"
        plan = plan_install(_target(root), store.read_source_entries(source))
        assert isinstance(plan, PlanRefusal)
        assert not root.exists()

    def test_adapter_confines_a_write_even_without_the_plan(self, store, downloads, tmp_path):
        source = _zip(downloads / "evil.zip", {"x": b"1"})
        root = tmp_path / "Textures" / "GALE01"
        outcome = store.install(source, str(root), (PlannedWrite("x", "../../escaped", 1),), frozenset(), "b")
        assert outcome.error is not None
        assert not (tmp_path / "escaped").exists()

    def test_game_id_folder_is_not_nested_twice(self, store, downloads, tmp_path):
        source = _zip(downloads / "pack.zip", {"GALE01/a.png": b"aa", "GALE01/sub/b.png": b"b"})
        target = _target(tmp_path / "Textures")
        plan, check = _install(store, source, target)
        outcome = store.install(source, target.path, plan.writes, check.replaces, str(tmp_path / "bk"))
        assert outcome.error is None
        assert outcome.written == 2
        assert (tmp_path / "Textures" / "GALE01" / "a.png").read_bytes() == b"aa"
        assert (tmp_path / "Textures" / "GALE01" / "sub" / "b.png").read_bytes() == b"b"
        assert not (tmp_path / "Textures" / "GALE01" / "GALE01").exists()

    def test_existing_files_are_backed_up_never_overwritten(self, store, downloads, tmp_path):
        game = tmp_path / "Textures" / "GALE01"
        game.mkdir(parents=True)
        (game / "a.png").write_bytes(b"old")
        source = _zip(downloads / "pack.zip", {"a.png": b"new"})
        target = _target(tmp_path / "Textures")
        plan, check = _install(store, source, target)
        assert check.replaces == frozenset({"a.png"})
        backup = tmp_path / "bk"
        outcome = store.install(source, target.path, plan.writes, check.replaces, str(backup))
        assert (outcome.written, outcome.backed_up, outcome.error) == (1, 1, None)
        assert (game / "a.png").read_bytes() == b"new"
        assert (backup / "a.png").read_bytes() == b"old"

    def test_a_file_not_planned_as_replaced_is_never_overwritten(self, store, downloads, tmp_path):
        game = tmp_path / "Textures" / "GALE01"
        game.mkdir(parents=True)
        (game / "a.png").write_bytes(b"old")
        source = _zip(downloads / "pack.zip", {"a.png": b"new"})
        outcome = store.install(source, str(game), (PlannedWrite("a.png", "a.png", 3),), frozenset(), "bk")
        assert outcome.error is not None
        assert (game / "a.png").read_bytes() == b"old"

    def test_size_lie_stops_and_leaves_no_part_file(self, store, downloads, tmp_path):
        source = _zip(downloads / "pack.zip", {"a.png": b"0123456789"})
        game = tmp_path / "G"
        outcome = store.install(source, str(game), (PlannedWrite("a.png", "a.png", 3),), frozenset(), "bk")
        assert outcome.error is not None
        assert os.listdir(game) == []

    def test_folder_source(self, store, downloads, tmp_path):
        folder = downloads / "Mod"
        folder.mkdir()
        (folder / "metadata.json").write_text("{}")
        target = ModTarget("graphic_mods", "g", "shared", str(tmp_path / "GraphicMods"))
        plan, check = _install(store, str(folder), target)
        outcome = store.install(str(folder), target.path, plan.writes, check.replaces, "bk")
        assert outcome.error is None
        assert (tmp_path / "GraphicMods" / "Mod" / "metadata.json").read_text() == "{}"

    def test_patch_file_is_renamed_after_the_rom(self, store, downloads, tmp_path):
        (downloads / "hack.ips").write_bytes(b"PATCHxxEOF")
        roms = tmp_path / "snes"
        roms.mkdir()
        target = ModTarget(TARGET_SOFT_PATCH, "p", SCOPE_PATCH, str(roms), patch_stem="Game (USA)")
        plan, check = _install(store, str(downloads / "hack.ips"), target)
        outcome = store.install(str(downloads / "hack.ips"), target.path, plan.writes, check.replaces, "bk")
        assert outcome.error is None
        assert (roms / "Game (USA).ips").read_bytes() == b"PATCHxxEOF"

    def test_probe_kinds(self, store, tmp_path):
        (tmp_path / "d").mkdir()
        (tmp_path / "f").write_bytes(b"")
        assert store.probe_kinds(str(tmp_path), ("d", "f", "m", "../x")) == {
            "d": "dir",
            "f": "file",
            "m": "missing",
            "../x": "other",
        }


class TestListing:
    def test_list_folder_totals(self, store, tmp_path):
        folder = tmp_path / "GALE01"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "a").write_bytes(b"12")
        (folder / "sub" / "b").write_bytes(b"345")
        (folder / "z.txt").write_bytes(b"1")
        entries, truncated = store.list_folder(str(folder), 10)
        assert [(e.name, e.is_dir, e.size, e.files) for e in entries] == [("sub", True, 5, 2), ("z.txt", False, 1, 1)]
        assert truncated is False

    def test_list_missing_folder(self, store, tmp_path):
        assert store.list_folder(str(tmp_path / "nope"), 10) == ([], False)

    def test_stat_names(self, store, tmp_path):
        (tmp_path / "g.ips").write_bytes(b"1")
        assert [e.name for e in store.stat_names(str(tmp_path), ("g.ips", "g.bps"))] == ["g.ips"]


class TestBackups:
    def test_move_entry_and_whole_folder(self, store, tmp_path):
        game = tmp_path / "GALE01"
        (game / "sub").mkdir(parents=True)
        (game / "sub" / "a").write_bytes(b"1")
        store.move_to_backup(str(game), "sub", str(tmp_path / "bk" / "sub"))
        assert (tmp_path / "bk" / "sub" / "a").exists()
        assert not (game / "sub").exists()
        store.move_to_backup(str(game), "", str(tmp_path / "bk2" / "GALE01"))
        assert not game.exists()
        assert (tmp_path / "bk2" / "GALE01").is_dir()

    @pytest.mark.parametrize("name", ["..", "a/b", "C:x"])
    def test_move_refuses_non_plain_names(self, store, tmp_path, name):
        with pytest.raises(ValueError):
            store.move_to_backup(str(tmp_path), name, str(tmp_path / "bk"))

    def test_move_refuses_an_existing_backup(self, store, tmp_path):
        (tmp_path / "a").write_bytes(b"1")
        (tmp_path / "bk").write_bytes(b"2")
        with pytest.raises(FileExistsError):
            store.move_to_backup(str(tmp_path), "a", str(tmp_path / "bk"))
        assert (tmp_path / "a").exists()


class TestText:
    def test_load_text_drops_bom_and_refuses_binary(self, store, tmp_path):
        (tmp_path / "a.ini").write_bytes(b"\xef\xbb\xbf[S]\n")
        (tmp_path / "b.ini").write_bytes(b"\xff\xfe\x00")
        assert store.load_text(str(tmp_path / "a.ini")) == "[S]\n"
        assert store.load_text(str(tmp_path / "b.ini")) is None
        assert store.load_text(str(tmp_path / "c.ini")) is None

    def test_replace_text_backs_up_and_keeps_bom(self, store, tmp_path):
        ini = tmp_path / "GFX.ini"
        ini.write_bytes(b"\xef\xbb\xbf[Settings]\r\nHiresTextures = False\r\n")
        backup = tmp_path / "bk" / "GFX.ini"
        assert store.replace_text(str(ini), "[Settings]\r\nHiresTextures = False\r\n", "NEW\r\n", str(backup))
        assert ini.read_bytes() == b"\xef\xbb\xbfNEW\r\n"
        assert backup.read_bytes() == b"\xef\xbb\xbf[Settings]\r\nHiresTextures = False\r\n"

    def test_replace_text_refuses_when_content_moved(self, store, tmp_path):
        ini = tmp_path / "GFX.ini"
        ini.write_text("changed")
        assert store.replace_text(str(ini), "expected", "new", str(tmp_path / "bk")) is False
        assert ini.read_text() == "changed"
        assert not (tmp_path / "bk").exists()


class TestOpenAndProcesses:
    def test_open_folder_uses_the_opener_only_for_a_folder(self, downloads, tmp_path):
        opened: list[str] = []
        store = GameModFilesAdapter(
            downloads_dir=str(downloads), running_executable_names=lambda: None, open_folder=opened.append
        )
        assert store.open_folder(str(tmp_path)) is True
        assert store.open_folder(str(tmp_path / "missing")) is False
        assert opened == [str(tmp_path)]

    def test_open_folder_failure(self, downloads, tmp_path):
        def boom(_path):
            raise OSError("no shell")

        store = GameModFilesAdapter(
            downloads_dir=str(downloads), running_executable_names=lambda: None, open_folder=boom
        )
        assert store.open_folder(str(tmp_path)) is False

    def test_running_names_pass_through(self, store):
        assert store.running_executable_names() == frozenset({"x.exe"})
        assert store.downloads_folder().endswith("Downloads")


class TestToggleFiles:
    def test_list_file_names_skips_folders_and_respects_the_limit(self, store, tmp_path):
        folder = tmp_path / "patches"
        folder.mkdir()
        for name in ("b.pnach", "A.pnach", "c.pnach"):
            (folder / name).write_text("x")
        (folder / "sub").mkdir()
        assert store.list_file_names(str(folder), 10) == ["A.pnach", "b.pnach", "c.pnach"]
        assert store.list_file_names(str(folder), 2) == ["A.pnach", "b.pnach"]
        assert store.list_file_names(str(tmp_path / "missing"), 10) == []

    def test_read_zip_text(self, store, tmp_path):
        path = tmp_path / "patches.zip"
        _zip(path, {"SLUS-20946_ABCD1234.pnach": "﻿[60 FPS]\n".encode()})
        assert store.read_zip_text(str(path), "SLUS-20946_ABCD1234.pnach") == "[60 FPS]\n"
        assert store.read_zip_text(str(path), "other.pnach") is None
        assert store.read_zip_text(str(tmp_path / "none.zip"), "x") is None
        (tmp_path / "bad.zip").write_bytes(b"not a zip")
        assert store.read_zip_text(str(tmp_path / "bad.zip"), "x") is None

    def test_create_text_never_overwrites(self, store, tmp_path):
        path = tmp_path / "gamesettings" / "SLUS-20946_ABCD1234.ini"
        assert store.create_text(str(path), "[Patches]\r\nEnable = A\r\n") is True
        assert path.read_bytes() == b"[Patches]\r\nEnable = A\r\n"
        assert store.create_text(str(path), "other") is False
        assert path.read_bytes() == b"[Patches]\r\nEnable = A\r\n"


class TestContentHelpers:
    def test_read_bytes(self, store, tmp_path):
        path = tmp_path / "PARAM.SFO"
        path.write_bytes(b"\x00PSF1234")
        assert store.read_bytes(str(path), 4) == b"\x00PSF"
        assert store.read_bytes(str(tmp_path), 4) is None
        assert store.read_bytes(str(tmp_path / "gone"), 4) is None

    def test_find_files_stops_at_the_first_match_per_branch(self, store, tmp_path):
        root = tmp_path / "graphicPacks"
        (root / "A" / "nested").mkdir(parents=True)
        (root / "A" / "rules.txt").write_text("x")
        (root / "A" / "nested" / "rules.txt").write_text("x")
        (root / "B").mkdir()
        (root / "B" / "Rules.txt").write_text("x")
        assert sorted(store.find_files(str(root), "rules.txt", 10)) == ["A\\rules.txt", "B\\rules.txt"]
        assert store.find_files(str(tmp_path / "missing"), "rules.txt", 10) == []

    def test_copy_to_backup_keeps_the_original(self, store, tmp_path):
        src = tmp_path / "title"
        (src / "content").mkdir(parents=True)
        (src / "content" / "00000000.app").write_bytes(b"data")
        backup = tmp_path / "backup" / "Update"
        store.copy_to_backup(str(src), str(backup))
        assert (backup / "content" / "00000000.app").read_bytes() == b"data"
        assert (src / "content" / "00000000.app").exists()
        with pytest.raises(FileExistsError):
            store.copy_to_backup(str(src), str(backup))

    def test_run_installer_reports_code_and_output(self, store, tmp_path):
        import sys

        code, output = store.run_installer(sys.executable, ("-c", "print('Installed CIA successfully.')"), 30)
        assert code == 0
        assert "Installed CIA successfully." in output
        code, _ = store.run_installer(sys.executable, ("-c", "import sys; sys.exit(7)"), 30)
        assert code == 7
        assert store.run_installer(str(tmp_path / "missing.exe"), (), 5)[0] is None
