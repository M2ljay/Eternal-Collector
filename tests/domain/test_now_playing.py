"""Tests for the "now playing" record (domain/now_playing.py)."""

from __future__ import annotations

import pytest

from domain.now_playing import (
    build_record,
    display_text,
    empty_document,
    normalize_document,
    public_cover_url,
    record_for,
    with_record,
    without_record,
)

IGDB = "https://images.igdb.com/igdb/image/upload/t_cover_big/co3nnx.jpg"


def _record(app_id: int = 3_000_000_123, **over):
    fields = {
        "app_id": app_id,
        "rom_id": 7,
        "name": "The Legend of Zelda: Ocarina of Time",
        "platform": "Nintendo 64",
        "started_at_ms": 1_764_190_000_000,
    }
    fields.update(over)
    return build_record(**fields)


class TestPublicCoverUrl:
    @pytest.mark.parametrize(
        "url",
        [
            IGDB,
            "https://cdn2.steamgriddb.com/grid/abc.png",
            "https://cdn.mobygames.com/covers/1-x.jpg",
            "https://images.launchbox-app.com/abc.jpg",
            "https://media.retroachievements.org/Images/012345.png",
        ],
    )
    def test_public_metadata_cdns_pass(self, url):
        assert public_cover_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://images.igdb.com/x.jpg",
            "https://romm.home.lan/assets/romm/resources/roms/1/cover/big.png",
            "https://192.168.1.20:8080/assets/romm/resources/x.png",
            "/assets/romm/resources/roms/1/cover/big.png",
            "https://user:pw@images.igdb.com/x.jpg",
            "https://images.igdb.com:8443/x.jpg",
            "https://images.igdb.com/x.jpg?ts=1",
            "https://neoclone.screenscraper.fr/api2/mediaJeu.php?devid=a&devpassword=b&ssid=c",
            "https://images.igdb.com.attacker.example/x.jpg",
            "https://images.igdb.com/",
            "https://images.igdb.com/x.jpg#f",
            "https://images.igdb.com/x\n.jpg",
            "https://images.igdb.com/" + "a" * 600,
            None,
            7,
        ],
    )
    def test_anything_that_could_expose_a_server_or_credential_is_refused(self, url):
        assert public_cover_url(url) is None


class TestRecord:
    def test_record_fields(self):
        assert _record(cover_url=IGDB) == {
            "app_id": 3_000_000_123,
            "rom_id": 7,
            "name": "The Legend of Zelda: Ocarina of Time",
            "platform": "Nintendo 64",
            "started_at": 1_764_190_000_000,
            "cover_url": IGDB,
        }

    def test_a_private_cover_never_enters_the_record(self):
        assert _record(cover_url="https://romm.lan/assets/x.png")["cover_url"] is None

    def test_display_text_is_one_bounded_line(self):
        assert display_text("  Super\nMario\t64 ") == "Super Mario 64"
        assert display_text("x" * 300) == "x" * 128
        assert display_text(None) == ""


class TestDocument:
    def test_add_replace_and_remove(self):
        doc = with_record(None, _record())
        doc = with_record(doc, _record(app_id=5, rom_id=9))
        doc = with_record(doc, _record(platform="N64"))
        assert set(doc["records"]) == {"3000000123", "5"}
        replaced = record_for(doc, 3_000_000_123)
        assert replaced is not None
        assert replaced["platform"] == "N64"
        doc = without_record(doc, 3_000_000_123)
        assert record_for(doc, 3_000_000_123) is None
        assert without_record(doc, 5) == empty_document()

    def test_foreign_versions_and_mismatched_keys_read_as_empty(self):
        assert normalize_document({"v": 2, "records": {"1": {"app_id": 1}}}) == empty_document()
        assert normalize_document("junk") == empty_document()
        assert normalize_document({"v": 1, "records": {"1": {"app_id": 2}, "3": "x"}})["records"] == {}

    def test_input_document_is_not_mutated(self):
        original = with_record(None, _record())
        without_record(original, 3_000_000_123)
        assert record_for(original, 3_000_000_123) is not None
