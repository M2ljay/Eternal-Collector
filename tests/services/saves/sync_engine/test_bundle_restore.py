"""Tests for services.saves.sync_engine.bundle_restore — staging, installing and enumerating bundled saves."""

import logging
import os
import zipfile

import pytest

from adapters.save_file import SaveFileAdapter
from domain.save_bundles import DIR_MEMBERS, BundleLayout, MemberSource
from lib.path_safety import PathTraversalError
from services.saves.sync_engine import bundle_restore

_STORE = SaveFileAdapter(logger=logging.getLogger("test"))
_WII = BundleLayout(label="SMOX.dolphin-wii", folder="Wii/title/00010000/534d4f58/data")
_PSP = BundleLayout(label="ULUS10234.ppsspp", sources=(MemberSource("saves", "", DIR_MEMBERS, "ULUS10234.*"),))


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return str(path)


class TestFolderBundle:
    def test_stage_and_install_create_missing_parents(self, tmp_path):
        bundle = _zip(tmp_path / "b.zip", {"save.bin": b"s"})
        staging = bundle_restore.stage(_STORE, str(tmp_path), _WII, bundle)
        assert staging == str(tmp_path / ".SMOX.dolphin-wii.romm-unpack")
        bundle_restore.install(_STORE, str(tmp_path), _WII, staging)
        assert (tmp_path / "Wii" / "title" / "00010000" / "534d4f58" / "data" / "save.bin").read_bytes() == b"s"
        assert not os.path.exists(staging)

    def test_symlinked_folder_is_not_the_save(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (tmp_path / "Wii" / "title" / "00010000" / "534d4f58").mkdir(parents=True)
        os.symlink(real, tmp_path / "Wii" / "title" / "00010000" / "534d4f58" / "data")
        assert bundle_restore.local_entries(_STORE, str(tmp_path), _WII) == []

    def test_stale_staging_is_replaced(self, tmp_path):
        (tmp_path / ".SMOX.dolphin-wii.romm-unpack" / "old").mkdir(parents=True)
        staging = bundle_restore.stage(_STORE, str(tmp_path), _WII, _zip(tmp_path / "b.zip", {"new": b"n"}))
        assert os.listdir(staging) == ["new"]


class TestMemberBundle:
    def test_install_moves_members_into_their_directory(self, tmp_path):
        (tmp_path / "saves" / "ULES01234DATA00").mkdir(parents=True)
        bundle = _zip(tmp_path / "b.zip", {"ULUS10234DATA00/DATA.BIN": b"d", "ULUS10234SYS/S": b"s"})
        staging = bundle_restore.stage(_STORE, str(tmp_path), _PSP, bundle)
        bundle_restore.install(_STORE, str(tmp_path), _PSP, staging)
        assert sorted(os.listdir(tmp_path / "saves")) == ["ULES01234DATA00", "ULUS10234DATA00", "ULUS10234SYS"]
        assert not os.path.exists(staging)

    def test_stage_refuses_before_writing(self, tmp_path):
        bundle = _zip(tmp_path / "b.zip", {"ULES01234DATA00/DATA.BIN": b"other"})
        with pytest.raises(PathTraversalError):
            bundle_restore.stage(_STORE, str(tmp_path), _PSP, bundle)
        assert not (tmp_path / ".ULUS10234.ppsspp.romm-unpack").exists()

    def test_local_entries_and_move_aside(self, tmp_path):
        (tmp_path / "saves" / "ULUS10234DATA00").mkdir(parents=True)
        (tmp_path / "saves" / "ULUS10234DATA00" / "DATA.BIN").write_bytes(b"d")
        entries = bundle_restore.local_entries(_STORE, str(tmp_path), _PSP)
        assert entries == [(str(tmp_path / "saves" / "ULUS10234DATA00"), "ULUS10234DATA00")]
        bundle_restore.move_aside(_STORE, entries, str(tmp_path / "backup"))
        assert (tmp_path / "backup" / "ULUS10234DATA00" / "DATA.BIN").read_bytes() == b"d"
        assert not (tmp_path / "saves" / "ULUS10234DATA00").exists()

    def test_discard_removes_staging(self, tmp_path):
        staging = bundle_restore.stage(_STORE, str(tmp_path), _PSP, _zip(tmp_path / "b.zip", {"ULUS10234X/a": b""}))
        bundle_restore.discard(_STORE, str(tmp_path), staging)
        assert not os.path.exists(staging)
        bundle_restore.discard(_STORE, str(tmp_path), staging)  # idempotent
