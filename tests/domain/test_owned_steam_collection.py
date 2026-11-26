"""Tests for the ``OwnedSteamCollection`` aggregate."""

from __future__ import annotations

import pytest

from domain.owned_steam_collection import OwnedSteamCollection


def _claim(**overrides: object) -> OwnedSteamCollection:
    fields: dict[str, object] = {
        "collection_id": "uc-1",
        "family": "platform",
        "source_name": "PlayStation 2",
        "display_name": "PlayStation 2",
    }
    fields.update(overrides)
    return OwnedSteamCollection.claim(**fields)  # pyright: ignore[reportArgumentType]


class TestClaim:
    def test_records_every_field(self):
        record = _claim(yielded_to="VR")
        assert record.collection_id == "uc-1"
        assert record.family == "platform"
        assert record.source_name == "PlayStation 2"
        assert record.display_name == "PlayStation 2"
        assert record.yielded_to == "VR"

    def test_empty_yielded_to_is_none(self):
        assert _claim(yielded_to="").yielded_to is None

    def test_source_key_folds_case(self):
        assert _claim(source_name="Nintendo 64").source_key == _claim(source_name="NINTENDO 64").source_key

    def test_romm_family_is_accepted(self):
        assert _claim(family="romm", source_name="Favourites").family == "romm"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"collection_id": ""},
            {"family": "shelf"},
            {"family": ""},
            {"source_name": ""},
            {"display_name": ""},
        ],
    )
    def test_rejects_an_incomplete_record(self, overrides: dict[str, object]):
        with pytest.raises(ValueError):
            _claim(**overrides)

    def test_wire_shape(self):
        assert _claim().to_wire() == {
            "collection_id": "uc-1",
            "family": "platform",
            "source_name": "PlayStation 2",
            "display_name": "PlayStation 2",
            "yielded_to": None,
        }
