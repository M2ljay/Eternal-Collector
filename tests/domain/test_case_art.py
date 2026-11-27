"""Tests for domain/case_art.py — the Game case ranking and letterbox rules."""

from __future__ import annotations

import json
import pathlib
import struct
import zlib
from typing import Any

import pytest

from domain.case_art import (
    CASE_GRID_DIMENSIONS,
    COVER_STYLE_CASE,
    COVER_STYLE_PLAIN,
    CaseAuthor,
    CaseSidecar,
    aspect_distance,
    case_art_filenames,
    case_grids_path,
    cover_style,
    dump_case_sidecar,
    letterbox_rect,
    parse_case_authors,
    parse_case_sidecar,
    png_size,
    rank_case_grids,
)

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sgdb"
_DEFAULTS = pathlib.Path(__file__).resolve().parents[2] / "defaults" / "case_art_authors.json"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text())


def _grid(
    grid_id: int, width: int, height: int, score: int = 0, author: str = "Anyone", **flags: Any
) -> dict[str, Any]:
    entry = {
        "id": grid_id,
        "score": score,
        "width": width,
        "height": height,
        "nsfw": False,
        "humor": False,
        "mime": "image/png",
        "url": f"https://cdn2.steamgriddb.com/grid/{grid_id}.png",
        "thumb": f"https://cdn2.steamgriddb.com/thumb/{grid_id}.png",
        "author": {"name": author, "steam64": "0", "avatar": None},
    }
    entry.update(flags)
    return entry


CASTCODER = {"ngc": (CaseAuthor(name="Castcoder", steam64=None),)}


class TestCoverStyle:
    def test_defaults_to_game_case(self):
        assert cover_style({}) == COVER_STYLE_CASE

    def test_reads_plain(self):
        assert cover_style({"cover_style": "plain"}) == COVER_STYLE_PLAIN

    def test_unknown_value_reads_as_game_case(self):
        assert cover_style({"cover_style": "glossy"}) == COVER_STYLE_CASE


class TestQueryPath:
    def test_asks_for_portrait_and_square_static_grids_without_nsfw_or_humor(self):
        path = case_grids_path(4242)
        assert path.startswith("/grids/game/4242?")
        assert "dimensions=" + ",".join(CASE_GRID_DIMENSIONS) in path
        assert "types=static" in path
        assert "nsfw=false" in path
        assert "humor=false" in path

    def test_never_asks_for_the_wide_capsule_sizes(self):
        assert "460x215" not in case_grids_path(1)
        assert "920x430" not in case_grids_path(1)


class TestRanking:
    def test_fixture_order_curated_then_shape_then_score_and_never_nsfw(self):
        ranked = rank_case_grids(_fixture("case_grids_gamecube.json"), "ngc", CASTCODER)
        assert [g.grid_id for g in ranked] == [102, 105, 103, 101]
        assert ranked[0].curated is True
        assert all(not g.curated for g in ranked[1:])

    def test_nsfw_humor_and_animated_grids_are_dropped_whatever_their_score(self):
        ranked = rank_case_grids(_fixture("case_grids_gamecube.json"), "ngc", CASTCODER)
        assert {104, 106, 107}.isdisjoint(g.grid_id for g in ranked)

    def test_a_grid_without_an_nsfw_flag_is_treated_as_unsafe(self):
        entry = _grid(1, 600, 900)
        del entry["nsfw"]
        assert rank_case_grids({"success": True, "data": [entry]}, "ngc", {}) == []

    def test_curated_author_wins_over_a_higher_score(self):
        payload = {"success": True, "data": [_grid(1, 600, 900, score=500), _grid(2, 600, 900, author="castcoder")]}
        assert [g.grid_id for g in rank_case_grids(payload, "ngc", CASTCODER)] == [2, 1]

    def test_curated_author_only_counts_for_its_platform(self):
        payload = {"success": True, "data": [_grid(1, 600, 900, score=500), _grid(2, 600, 900, author="Castcoder")]}
        assert [g.grid_id for g in rank_case_grids(payload, "ps2", CASTCODER)] == [1, 2]

    def test_wildcard_authors_apply_to_every_platform(self):
        authors = {"*": (CaseAuthor(name="", steam64="765"),)}
        entry = _grid(2, 600, 900)
        entry["author"]["steam64"] = "765"
        payload = {"success": True, "data": [_grid(1, 600, 900, score=500), entry]}
        assert [g.grid_id for g in rank_case_grids(payload, "snes", authors)] == [2, 1]

    def test_ds_prefers_the_square_grid_its_near_square_case_matches(self):
        payload = {"success": True, "data": [_grid(1, 600, 900, score=90), _grid(2, 512, 512, score=1)]}
        assert [g.grid_id for g in rank_case_grids(payload, "nds", {})] == [2, 1]

    def test_psp_prefers_the_tallest_grid(self):
        payload = {"success": True, "data": [_grid(1, 512, 512, score=90), _grid(2, 600, 900, score=1)]}
        assert [g.grid_id for g in rank_case_grids(payload, "psp", {})] == [2, 1]

    def test_unknown_platform_ranks_against_steams_2_by_3(self):
        payload = {"success": True, "data": [_grid(1, 660, 930, score=90), _grid(2, 600, 900, score=1)]}
        assert [g.grid_id for g in rank_case_grids(payload, "amiga", {})] == [2, 1]

    def test_score_decides_between_shapes_equally_close(self):
        payload = {"success": True, "data": [_grid(1, 660, 930, score=1), _grid(2, 342, 482, score=5)]}
        assert [g.grid_id for g in rank_case_grids(payload, "ps2", {})] == [2, 1]

    @pytest.mark.parametrize("payload", [None, {}, {"success": False}, {"success": True, "data": "x"}])
    def test_failed_or_malformed_payload_ranks_nothing(self, payload):
        assert rank_case_grids(payload, "ngc", CASTCODER) == []

    def test_malformed_entries_are_skipped(self):
        payload = {"success": True, "data": ["x", _grid(1, 0, 900), {"id": "2"}, _grid(3, 600, 900)]}
        assert [g.grid_id for g in rank_case_grids(payload, "ngc", {})] == [3]

    def test_aspect_distance_is_zero_on_a_match(self):
        assert aspect_distance(600, 900, "unknown") == pytest.approx(0.0)


class TestAuthors:
    def test_shipped_file_parses_and_lists_castcoder_for_gamecube_and_psp(self):
        authors = parse_case_authors(_DEFAULTS.read_bytes())
        assert [a.name for a in authors["ngc"]] == ["Castcoder"]
        assert [a.name for a in authors["psp"]] == ["Castcoder"]
        assert "ps2" not in authors

    @pytest.mark.parametrize("raw", [None, b"", b"{not json", b"[]", b'{"platforms": []}'])
    def test_missing_or_malformed_file_is_empty(self, raw):
        assert parse_case_authors(raw) == {}

    def test_comment_keys_and_bad_entries_are_skipped(self):
        raw = json.dumps({"platforms": {"_note": [{"name": "x"}], "psx": [{"name": " A "}, {}, 3, {"steam64": "9"}]}})
        assert parse_case_authors(raw) == {"psx": (CaseAuthor("A", None), CaseAuthor("", "9"))}


class TestLetterbox:
    @pytest.mark.parametrize(
        ("size", "rect"),
        [
            ((600, 900), (0, 0, 600, 900)),
            ((1024, 1024), (0, 150, 600, 600)),
            ((512, 512), (0, 150, 600, 600)),
            ((660, 930), (0, 27, 600, 845)),
            ((342, 482), (0, 27, 600, 846)),
            ((300, 900), (150, 0, 300, 900)),
        ],
    )
    def test_fits_inside_the_capsule_and_centres(self, size, rect):
        assert letterbox_rect(*size) == rect

    @pytest.mark.parametrize("size", [(512, 512), (660, 930), (300, 900), (1920, 620)])
    def test_never_stretches(self, size):
        x, y, w, h = letterbox_rect(*size)
        assert w <= 600 and h <= 900 and x >= 0 and y >= 0
        assert w / h == pytest.approx(size[0] / size[1], rel=0.01)
        assert w == 600 or h == 900

    def test_rejects_an_empty_image(self):
        with pytest.raises(ValueError):
            letterbox_rect(0, 10)


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


class TestPngAndSidecar:
    def test_png_size_reads_ihdr(self):
        assert png_size(_png(600, 900)) == (600, 900)

    @pytest.mark.parametrize("data", [b"", b"GIF89a" + b"\0" * 30, b"\x89PNG\r\n\x1a\n" + b"\0" * 8])
    def test_png_size_refuses_other_bytes(self, data):
        assert png_size(data) is None

    def test_sidecar_round_trips(self):
        sidecar = CaseSidecar(grid_id=7, manual=True, published=COVER_STYLE_PLAIN)
        assert parse_case_sidecar(dump_case_sidecar(sidecar)) == sidecar

    @pytest.mark.parametrize("raw", [None, b"", b"{", b'{"grid_id": "7"}'])
    def test_bad_sidecar_is_none(self, raw):
        assert parse_case_sidecar(raw) is None

    def test_filenames_share_the_rom_prefix_the_cache_pruner_keys_on(self):
        assert all(name.startswith("41_") for name in case_art_filenames(41))
