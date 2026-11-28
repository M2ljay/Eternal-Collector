"""Tests for ``SteamCollectionOwnershipService`` over the fake unit of work."""

from __future__ import annotations

import pytest
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory

from domain.owned_steam_collection import ADOPTION_DONE_KEY, OwnedSteamCollection
from domain.rom import Rom
from domain.rom_install import RomInstall
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
            "platform_renames": {},
        }

    def test_reports_platform_renames_from_the_romm_name_cache(self, service, uow):
        with uow:
            uow.kv_config.set("platform_names", '{"psx": "PlayStation", "ps2": "PlayStation 2"}')

        assert service.get_owned_steam_collections()["platform_renames"] == {"PlayStation": "PlayStation 1"}

    def test_reports_the_original_xbox_rename(self, service, uow):
        with uow:
            uow.kv_config.set("platform_names", '{"xbox": "Xbox", "xbox360": "Xbox 360", "psx": "PlayStation"}')

        assert service.get_owned_steam_collections()["platform_renames"] == {
            "Xbox": "Xbox (Original)",
            "PlayStation": "PlayStation 1",
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


def _rom(rom_id: int, *, bound: bool = True) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug="snes",
        name=f"Game {rom_id}",
        fs_name=f"g{rom_id}",
        shortcut_app_id=(5000 + rom_id) if bound else None,
        last_synced_at="2026-01-01T00:00:00",
    )


def _install(rom_id: int) -> RomInstall:
    return RomInstall.mark_installed(
        rom_id=rom_id,
        file_path=f"/roms/snes/g{rom_id}.sfc",
        rom_dir=None,
        platform_slug="snes",
        system="snes",
        installed_at="2026-11-27T10:00:00+00:00",
    )


class TestInstalledRomAppIds:
    def test_empty_library_is_enabled_with_nothing_installed(self, service):
        assert service.get_installed_rom_app_ids() == {"success": True, "enabled": True, "app_ids": []}

    def test_only_installed_and_bound_roms_count(self, service, uow):
        with uow:
            for rom in (_rom(1), _rom(2), _rom(3, bound=False), _rom(4)):
                uow.roms.save(rom)
            uow.rom_installs.save(_install(4))
            uow.rom_installs.save(_install(1))
            uow.rom_installs.save(_install(3))  # an installed sibling the shortcut is not bound to

        assert service.get_installed_rom_app_ids()["app_ids"] == [5001, 5004]

    def test_reports_the_setting(self, service, settings):
        settings["installed_roms_collection"] = False
        assert service.get_installed_rom_app_ids()["enabled"] is False

    def test_the_installed_family_can_be_recorded(self, service, uow):
        assert service.record_owned_steam_collection("uc-9", "installed", "Installed ROMs", "Installed ROMs", None) == {
            "success": True
        }
        record = uow.owned_steam_collections.get("uc-9")
        assert record is not None
        assert record.family == "installed"


class TestFamilyCollectionGames:
    def test_lists_every_rom_shortcut_with_its_platform(self, service, uow):
        with uow:
            uow.roms.save(_rom(2))
            uow.roms.save(_rom(1))
            uow.roms.save(_rom(3, bound=False))
        assert service.get_family_collection_games() == {
            "success": True,
            "enabled": True,
            "games": [{"app_id": 5001, "platform_slug": "snes"}, {"app_id": 5002, "platform_slug": "snes"}],
        }

    def test_an_empty_library_has_no_games(self, service):
        assert service.get_family_collection_games()["games"] == []

    def test_reports_the_setting(self, service, settings):
        settings["family_collections"] = False
        assert service.get_family_collection_games()["enabled"] is False

    def test_the_console_family_family_can_be_recorded(self, service, uow):
        assert service.record_owned_steam_collection("uc-7", "console_family", "Sega", "Sega (RomM)", "Sega") == {
            "success": True
        }
        record = uow.owned_steam_collections.get("uc-7")
        assert record is not None
        assert (record.family, record.display_name, record.yielded_to) == ("console_family", "Sega (RomM)", "Sega")


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
