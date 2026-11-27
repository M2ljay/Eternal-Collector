"""Tests for domain.game_content — where updates and DLC go per emulator, and what an install may do."""

from __future__ import annotations

import pytest

from domain.game_content import (
    AZAHAR_INSTALL_ERRORS,
    INSTALLER_AZAHAR_CIA,
    azahar_content_target,
    ps4_game_root,
    rpcs3_update_target,
    shadps4_targets,
    xenia_content_targets,
)
from domain.game_mods import (
    KIND_DLC,
    KIND_LAYERED_FS,
    KIND_UPDATE,
    SCOPE_INSTALL,
    SCOPE_READONLY,
    SOURCE_CIA,
    InstallPlan,
    PlanRefusal,
    SourceEntry,
    plan_install,
    removable_name,
    source_fits,
    source_kind,
)

_SD = "0" * 32


class TestAzahar:
    def test_watches_the_update_and_dlc_title_folders(self):
        target = azahar_content_target("C:\\Azahar\\user", "0004000000055D00")
        assert (target.scope, target.kind, target.installer) == (SCOPE_INSTALL, KIND_UPDATE, INSTALLER_AZAHAR_CIA)
        root = f"C:\\Azahar\\user\\sdmc\\Nintendo 3DS\\{_SD}\\{_SD}\\title"
        assert target.watch == (("Update", f"{root}\\0004000e\\00055d00"), ("DLC", f"{root}\\0004008c\\00055d00"))

    def test_installs_exactly_one_cia_and_never_removes(self):
        target = azahar_content_target("C:\\A\\user", "0004000000055D00")
        assert source_kind("Game Update.CIA", is_dir=False) == SOURCE_CIA
        assert source_fits(target, SOURCE_CIA)
        assert not source_fits(target, "zip")
        plan = plan_install(target, [SourceEntry("Game Update.cia", False, 100)])
        assert isinstance(plan, InstallPlan)
        two = plan_install(target, [SourceEntry("a.cia", False, 1), SourceEntry("b.cia", False, 1)])
        assert isinstance(two, PlanRefusal)
        assert removable_name(target, "Update") is None

    def test_error_codes_are_install_status_plus_two(self):
        assert "encrypted" in AZAHAR_INSTALL_ERRORS[7]
        assert set(AZAHAR_INSTALL_ERRORS) == {3, 4, 5, 6, 7, 8}


class TestShadPs4:
    @pytest.mark.parametrize(
        ("path", "is_dir", "root"),
        [
            ("D:\\ps4\\CUSA00001", True, "D:\\ps4\\CUSA00001"),
            ("D:\\ps4\\CUSA00001\\eboot.bin", False, "D:\\ps4\\CUSA00001"),
            ("D:\\ps4\\game.zar", False, None),
        ],
    )
    def test_game_root(self, path, is_dir, root):
        assert ps4_game_root(path, is_dir) == root

    def test_update_and_mods_folders_beside_the_game(self):
        update, mods = shadps4_targets("D:\\ps4\\CUSA00001", update_version="01.09", game_version="01.00")
        assert update.path == "D:\\ps4\\CUSA00001-UPDATE"
        assert (update.kind, update.replace_whole) == (KIND_UPDATE, True)
        assert "Installed update: version 01.09." in update.notes
        assert mods.path == "D:\\ps4\\CUSA00001-mods"
        assert mods.kind == KIND_LAYERED_FS

    def test_an_update_dump_named_patch_is_unwrapped(self):
        update, _ = shadps4_targets("D:\\ps4\\CUSA00001", update_version=None, game_version=None)
        plan = plan_install(update, [SourceEntry("CUSA00001-patch/sce_sys/param.sfo", False, 10)])
        assert isinstance(plan, InstallPlan)
        assert [w.dest for w in plan.writes] == ["sce_sys/param.sfo"]
        assert plan.stripped_folder == "CUSA00001-patch"


class TestReadOnlyContent:
    def test_rpcs3_update_shows_the_installed_version(self):
        target = rpcs3_update_target("C:\\RPCS3\\dev_hdd0", "BLUS30443", installed_version="01.04")
        assert (target.scope, target.path) == (SCOPE_READONLY, "C:\\RPCS3\\dev_hdd0\\game\\BLUS30443")
        assert target.notes == ("Installed update: version 01.04.",)
        assert isinstance(plan_install(target, [SourceEntry("x.pkg", False, 1)]), PlanRefusal)

    def test_xenia_title_updates_and_dlc(self):
        updates, dlc = xenia_content_targets("C:\\Xenia\\content", "4D5307E6")
        assert updates.path == "C:\\Xenia\\content\\0000000000000000\\4D5307E6\\000B0000"
        assert dlc.path == "C:\\Xenia\\content\\0000000000000000\\4D5307E6\\00000002"
        assert (updates.kind, dlc.kind) == (KIND_UPDATE, KIND_DLC)
        assert removable_name(dlc, "pack") is None
