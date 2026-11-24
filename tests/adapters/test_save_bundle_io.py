"""Tests for adapters.save_bundle_io — member bundles: selection, packing, safe unpacking."""

import os
import zipfile

import pytest

from adapters import save_bundle_io
from domain.save_bundles import DIR_MEMBERS, GCI_MEMBERS, BundleLayout, MemberSource
from lib.path_safety import PathTraversalError

_PSP = BundleLayout(label="ULUS10234.ppsspp", sources=(MemberSource("saves", "", DIR_MEMBERS, "ULUS10234.*"),))
_PS2 = BundleLayout(
    label="SLUS-20062.pcsx2",
    sources=(MemberSource("saves/memcard.ps2", "", DIR_MEMBERS, "B[A-Z]SLUS\\-20062.*"),),
)
_GC = BundleLayout(
    label="GALE01.dolphin-gc",
    sources=(
        MemberSource("GC/USA/Card A", "Card A/", GCI_MEMBERS, "GALE"),
        MemberSource("GC/USA/Card B", "Card B/", GCI_MEMBERS, "GALE"),
    ),
)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


@pytest.fixture
def psp_root(tmp_path):
    root = tmp_path / "ppsspp"
    saves = root / "saves"
    _put(str(saves / "ULUS102340000" / "PARAM.SFO"), b"sfo")
    _put(str(saves / "ULUS102340000" / "DATA.BIN"), b"data")
    _put(str(saves / "ULUS10234SYS" / "SYS.BIN"), b"sys")
    os.makedirs(saves / "ULUS10234EMPTY")
    _put(str(saves / "ULES01234DATA00" / "DATA.BIN"), b"other game")
    _put(str(saves / "ULUS10234stray"), b"loose file")
    os.symlink(saves / "ULES01234DATA00", saves / "ULUS10234LINK")
    return str(root)


@pytest.fixture
def gc_root(tmp_path):
    root = tmp_path / "dolphin"
    card_a = root / "GC" / "USA" / "Card A"
    _put(str(card_a / "01-GALE-SuperSmashBros0110290334.gci"), b"GALE01" + b"\x00" * 58)
    _put(str(card_a / "4Z-GOBE-BadBoys.gci"), b"GOBE4Z" + b"\x00" * 58)
    _put(str(card_a / "01-GALE-renamed-but-other.gci"), b"GOBE4Z" + b"\x00" * 58)
    _put(str(card_a / "MemoryCardA.USA.raw"), b"raw card")
    _put(str(root / "GC" / "SRAM.raw"), b"sram")
    _put(str(root / "GC" / "USA" / "Card B" / "01-GALE-second.gci"), b"GALE01" + b"\x01" * 58)
    return str(root)


class TestListMembers:
    def test_dirs_by_pattern_only(self, psp_root):
        assert save_bundle_io.list_members(psp_root, _PSP) == [
            ("saves/ULUS102340000", "ULUS102340000"),
            ("saves/ULUS10234EMPTY", "ULUS10234EMPTY"),
            ("saves/ULUS10234SYS", "ULUS10234SYS"),
        ]

    def test_gci_by_header_not_name(self, gc_root):
        assert save_bundle_io.list_members(gc_root, _GC) == [
            ("GC/USA/Card A/01-GALE-SuperSmashBros0110290334.gci", "Card A/01-GALE-SuperSmashBros0110290334.gci"),
            ("GC/USA/Card B/01-GALE-second.gci", "Card B/01-GALE-second.gci"),
        ]

    def test_missing_directory(self, tmp_path):
        assert save_bundle_io.list_members(str(tmp_path), _PSP) == []

    def test_pcsx2_never_selects_card_files(self, tmp_path):
        card = tmp_path / "pcsx2" / "saves" / "memcard.ps2"
        _put(str(card / "_pcsx2_superblock"), b"sb")
        _put(str(card / "_pcsx2_index"), b"idx")
        _put(str(card / "BASLUS-20062GTA30000" / "_pcsx2_index"), b"i")
        _put(str(card / "BASLUS-21645SD8_0" / "x"), b"other")
        _put(str(tmp_path / "pcsx2" / "saves" / "Mcd001.ps2"), b"file card")
        assert save_bundle_io.list_members(str(tmp_path / "pcsx2"), _PS2) == [
            ("saves/memcard.ps2/BASLUS-20062GTA30000", "BASLUS-20062GTA30000")
        ]


class TestPackMembers:
    def test_entries(self, psp_root, tmp_path):
        bundle = str(tmp_path / "b.zip")
        assert save_bundle_io.pack_members(psp_root, _PSP, bundle)
        with zipfile.ZipFile(bundle) as zf:
            assert zf.namelist() == [
                "ULUS102340000/DATA.BIN",
                "ULUS102340000/PARAM.SFO",
                "ULUS10234EMPTY/",
                "ULUS10234SYS/SYS.BIN",
            ]

    def test_gci_entries(self, gc_root, tmp_path):
        bundle = str(tmp_path / "b.zip")
        assert save_bundle_io.pack_members(gc_root, _GC, bundle)
        with zipfile.ZipFile(bundle) as zf:
            assert zf.namelist() == ["Card A/01-GALE-SuperSmashBros0110290334.gci", "Card B/01-GALE-second.gci"]

    def test_byte_stable_and_untouched_when_unchanged(self, psp_root, tmp_path):
        bundle = str(tmp_path / "b.zip")
        save_bundle_io.pack_members(psp_root, _PSP, bundle)
        first = _read(bundle)
        os.utime(bundle, (5, 5))
        save_bundle_io.pack_members(psp_root, _PSP, bundle)
        assert _read(bundle) == first
        assert os.path.getmtime(bundle) == 5

    def test_nothing_to_pack(self, tmp_path):
        bundle = str(tmp_path / "b.zip")
        assert not save_bundle_io.pack_members(str(tmp_path), _PSP, bundle)
        assert not os.path.exists(bundle)


def _zip(path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class TestUnpackMembers:
    def test_round_trip(self, psp_root, tmp_path):
        bundle = str(tmp_path / "b.zip")
        save_bundle_io.pack_members(psp_root, _PSP, bundle)
        dest = str(tmp_path / "stage")
        save_bundle_io.unpack_members(bundle, dest, _PSP)
        assert sorted(os.listdir(dest)) == ["ULUS102340000", "ULUS10234EMPTY", "ULUS10234SYS"]
        assert _read(os.path.join(dest, "ULUS102340000", "DATA.BIN")) == b"data"

    def test_gci_round_trip(self, gc_root, tmp_path):
        bundle = str(tmp_path / "b.zip")
        save_bundle_io.pack_members(gc_root, _GC, bundle)
        dest = str(tmp_path / "stage")
        save_bundle_io.unpack_members(bundle, dest, _GC)
        assert os.listdir(os.path.join(dest, "Card A")) == ["01-GALE-SuperSmashBros0110290334.gci"]

    @pytest.mark.parametrize(
        ("layout", "entries"),
        [
            (_PS2, {"_pcsx2_superblock": b"sb"}),
            (_PS2, {"BASLUS-21645SD8_0/x": b"other game"}),
            (_PSP, {"ULUS102340000": b"loose file where a folder belongs"}),
            (_PSP, {"../escape/x": b"x"}),
            (_PSP, {"ULUS102340000/../../x": b"x"}),
            (_GC, {"Card A/SRAM.raw": b"x"}),
            (_GC, {"Card A/MemoryCardA.USA.raw": b"x"}),
            (_GC, {"Card A/4Z-GOBE-BadBoys.gci": b"GOBE4Z" + bytes(10)}),
            (_GC, {"Card A/01-GALE-x.gci": b"GOBE4Z" + bytes(10)}),
            (_GC, {"SRAM.raw": b"x"}),
        ],
    )
    def test_rejects_anything_the_layout_does_not_own(self, tmp_path, layout, entries):
        bundle = _zip(str(tmp_path / "b.zip"), entries)
        dest = str(tmp_path / "stage")
        with pytest.raises(PathTraversalError):
            save_bundle_io.unpack_members(bundle, dest, layout)
        assert not os.path.exists(dest)

    def test_one_bad_entry_rejects_the_whole_bundle(self, tmp_path):
        bundle = _zip(str(tmp_path / "b.zip"), {"ULUS102340000/DATA.BIN": b"ok", "ULES01234DATA00/DATA.BIN": b"no"})
        with pytest.raises(PathTraversalError):
            save_bundle_io.unpack_members(bundle, str(tmp_path / "stage"), _PSP)
        assert not os.path.exists(tmp_path / "stage")

    def test_existing_destination(self, tmp_path):
        bundle = _zip(str(tmp_path / "b.zip"), {"ULUS102340000/DATA.BIN": b"ok"})
        os.makedirs(tmp_path / "stage")
        with pytest.raises(FileExistsError):
            save_bundle_io.unpack_members(bundle, str(tmp_path / "stage"), _PSP)

    def test_not_a_zip(self, tmp_path):
        bad = tmp_path / "b.zip"
        bad.write_bytes(b"nope")
        with pytest.raises(zipfile.BadZipFile):
            save_bundle_io.unpack_members(str(bad), str(tmp_path / "stage"), _PSP)


class TestMoveEntry:
    def test_moves_folder(self, tmp_path):
        _put(str(tmp_path / "a" / "f"), b"1")
        save_bundle_io.move_entry(str(tmp_path / "a"), str(tmp_path / "b"))
        assert (tmp_path / "b" / "f").read_bytes() == b"1" and not (tmp_path / "a").exists()

    def test_refuses_an_existing_destination(self, tmp_path):
        _put(str(tmp_path / "a"), b"1")
        _put(str(tmp_path / "b"), b"2")
        with pytest.raises(FileExistsError):
            save_bundle_io.move_entry(str(tmp_path / "a"), str(tmp_path / "b"))
        assert (tmp_path / "b").read_bytes() == b"2"
