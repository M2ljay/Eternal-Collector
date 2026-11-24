"""Tests for domain.save_bundles — bundle layouts, entry-name rules and member ownership."""

import pytest

from domain.save_bundles import (
    DIR_MEMBERS,
    GCI_MEMBERS,
    BundleLayout,
    MemberSource,
    bundle_entries,
    bundle_entry_name,
    gci_header_matches,
    member_of_entry,
    safe_component,
)


class TestBundleEntryName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("SlotParam_0.bin", "SlotParam_0.bin"),
            ("game_dir/MK9PSET", "game_dir/MK9PSET"),
            ("empty/", "empty/"),
            ("a/b/c.dat", "a/b/c.dat"),
        ],
    )
    def test_accepts_plain_relative_names(self, name, expected):
        assert bundle_entry_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "/etc/passwd",
            "../escape",
            "a/../../escape",
            "a/./b",
            "a//b",
            "C:\\Windows\\x",
            "C:x",
            "D:/x",
            "dir\\file",
            "nul\x00byte",
            "..",
            ".",
            "a/..",
        ],
    )
    def test_rejects_anything_that_could_escape(self, name):
        assert bundle_entry_name(name) is None


class TestBundleEntries:
    def test_sorted_with_only_empty_dirs_listed(self):
        assert bundle_entries(["system.bin", "game_dir/MK9PSET", "SlotParam_0.bin"], ["empty"]) == [
            "SlotParam_0.bin",
            "empty/",
            "game_dir/MK9PSET",
            "system.bin",
        ]

    def test_order_independent_of_input_order(self):
        assert bundle_entries(["b", "a"], []) == bundle_entries(["a", "b"], [])


_PPSSPP = MemberSource("saves", "", DIR_MEMBERS, "ULUS10234.*")
_CARD_A = MemberSource("GC/USA/Card A", "Card A/", GCI_MEMBERS, "GALE")
_CARD_B = MemberSource("GC/USA/Card B", "Card B/", GCI_MEMBERS, "GALE")
_GC = BundleLayout(label="GALE01.dolphin-gc", sources=(_CARD_A, _CARD_B))
_PSP = BundleLayout(label="ULUS10234.ppsspp", sources=(_PPSSPP,))


class TestSafeComponent:
    @pytest.mark.parametrize("name", ["memcard.ps2", "Mcd001.ps2", "a b"])
    def test_plain(self, name):
        assert safe_component(name) == name

    @pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "C:", "x\x00"])
    def test_rejected(self, name):
        assert safe_component(name) is None


class TestOwnsName:
    def test_dir_pattern_is_a_full_match(self):
        assert _PPSSPP.owns_name("ULUS10234DATA00")
        assert _PPSSPP.owns_name("ULUS10234")
        assert not _PPSSPP.owns_name("ULUS10235DATA00")
        assert not _PPSSPP.owns_name("xULUS10234")

    def test_gci_needs_the_extension(self):
        assert _CARD_A.owns_name("01-GALE-SuperSmashBros0110290334.gci")
        assert _CARD_A.owns_name("x.GCI")
        assert not _CARD_A.owns_name("SRAM.raw")
        assert not _CARD_A.owns_name("MemoryCardA.USA.raw")
        assert not _CARD_A.owns_name(".gci")

    def test_unsafe_names_never_match(self):
        assert not _PPSSPP.owns_name("ULUS10234/../x")
        assert not _CARD_A.owns_name("..")


class TestMemberOfEntry:
    def test_dir_member_files_and_dir_entry(self):
        assert member_of_entry(_PSP, "ULUS10234DATA00/PARAM.SFO") == (_PPSSPP, "ULUS10234DATA00")
        assert member_of_entry(_PSP, "ULUS10234DATA00/") == (_PPSSPP, "ULUS10234DATA00")

    def test_loose_file_next_to_members_belongs_to_nothing(self):
        assert member_of_entry(_PSP, "ULUS10234DATA00") is None
        assert member_of_entry(_PSP, "_pcsx2_superblock") is None

    def test_other_game_folder(self):
        assert member_of_entry(_PSP, "ULES01234DATA00/PARAM.SFO") is None

    def test_gci_member_under_its_prefix(self):
        assert member_of_entry(_GC, "Card A/01-GALE-x.gci") == (_CARD_A, "01-GALE-x.gci")
        assert member_of_entry(_GC, "Card B/01-GALE-x.gci") == (_CARD_B, "01-GALE-x.gci")

    @pytest.mark.parametrize(
        "entry", ["01-GALE-x.gci", "Card A/SRAM.raw", "Card A/sub/x.gci", "Card A/", "Card C/x.gci"]
    )
    def test_gci_misplaced(self, entry):
        assert member_of_entry(_GC, entry) is None


class TestGciHeaderMatches:
    def test_match(self):
        assert gci_header_matches(_CARD_A, b"GALE01")

    def test_other_game(self):
        assert not gci_header_matches(_CARD_A, b"GOBE4Z")

    def test_dir_source_never_matches(self):
        assert not gci_header_matches(_PPSSPP, b"ULUS")


class TestBundleLayout:
    def test_folder_flag(self):
        assert BundleLayout(label="x", folder="a/b").is_folder
        assert not _PSP.is_folder
