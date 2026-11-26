"""Tests for ``SteamCollectionOwnershipService`` over the fake unit of work."""

from __future__ import annotations

import pytest
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory

from domain.owned_steam_collection import ADOPTION_DONE_KEY, OwnedSteamCollection
from services.steam_collections import (
    SteamCollectionOwnershipService,
    SteamCollectionOwnershipServiceConfig,
    name_style_of,
)


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def settings() -> dict[str, object]:
    return {}


@pytest.fixture
def logs() -> list[str]:
    return []


@pytest.fixture
def service(uow, settings, logs) -> SteamCollectionOwnershipService:
    return SteamCollectionOwnershipService(
        config=SteamCollectionOwnershipServiceConfig(
            uow_factory=FakeUnitOfWorkFactory(uow=uow),
            settings=settings,
            log_debug=logs.append,
        )
    )


class TestNameStyle:
    @pytest.mark.parametrize(("stored", "expected"), [(None, "classic"), ("clean", "clean"), ("fancy", "classic")])
    def test_unknown_or_missing_reads_classic(self, stored, expected):
        settings = {} if stored is None else {"collection_name_style": stored}
        assert name_style_of(settings) == expected


class TestGet:
    def test_empty_answer(self, service):
        assert service.get_owned_steam_collections() == {
            "success": True,
            "name_style": "classic",
            "adoption_done": False,
            "collections": [],
        }

    def test_reports_records_style_and_adoption(self, service, uow, settings):
        settings["collection_name_style"] = "clean"
        with uow:
            uow.owned_steam_collections.save(
                OwnedSteamCollection.claim(
                    collection_id="uc-1", family="platform", source_name="Nintendo 64", display_name="Nintendo 64"
                )
            )
            uow.kv_config.set(ADOPTION_DONE_KEY, "1")

        answer = service.get_owned_steam_collections()

        assert answer["name_style"] == "clean"
        assert answer["adoption_done"] is True
        assert answer["collections"] == [
            {
                "collection_id": "uc-1",
                "family": "platform",
                "source_name": "Nintendo 64",
                "display_name": "Nintendo 64",
                "yielded_to": None,
            }
        ]


class TestRecord:
    def test_records_and_logs(self, service, uow, logs):
        result = service.record_owned_steam_collection("uc-1", "romm", "Favourites", "Favourites (RomM)", "Favourites")

        assert result == {"success": True}
        record = uow.owned_steam_collections.get("uc-1")
        assert record is not None
        assert record.yielded_to == "Favourites"
        assert any("uc-1" in line for line in logs)

    def test_rerecording_a_source_moves_it(self, service, uow):
        service.record_owned_steam_collection("uc-old", "platform", "Nintendo 64", "RomM: Nintendo 64 (htpc)", None)
        service.record_owned_steam_collection("uc-new", "platform", "Nintendo 64", "Nintendo 64", None)
        assert [r.collection_id for r in uow.owned_steam_collections.iter_all()] == ["uc-new"]

    @pytest.mark.parametrize(
        "args",
        [
            (1, "platform", "N64", "N64", None),
            ("uc-1", None, "N64", "N64", None),
            ("uc-1", "platform", "N64", 5, None),
            ("uc-1", "platform", "N64", "N64", 7),
            ("", "platform", "N64", "N64", None),
            ("uc-1", "shelf", "N64", "N64", None),
            ("uc-1", "platform", "", "N64", None),
        ],
    )
    def test_rejects_a_bad_record(self, service, uow, args):
        result = service.record_owned_steam_collection(*args)

        assert result["success"] is False
        assert result["reason"] == "invalid_record"
        assert result["message"]
        assert list(uow.owned_steam_collections.iter_all()) == []


class TestForget:
    def test_forgets(self, service, uow):
        service.record_owned_steam_collection("uc-1", "platform", "Nintendo 64", "Nintendo 64", None)
        assert service.forget_owned_steam_collection("uc-1") == {"success": True}
        assert uow.owned_steam_collections.get("uc-1") is None

    def test_forgetting_an_unknown_id_is_fine(self, service):
        assert service.forget_owned_steam_collection("uc-none") == {"success": True}

    @pytest.mark.parametrize("bad", ["", None, 3])
    def test_rejects_a_bad_id(self, service, bad):
        result = service.forget_owned_steam_collection(bad)
        assert result["success"] is False
        assert result["reason"] == "invalid_record"


class TestAdoption:
    def test_marks_adoption_done(self, service):
        assert service.finish_steam_collection_adoption() == {"success": True}
        assert service.get_owned_steam_collections()["adoption_done"] is True
