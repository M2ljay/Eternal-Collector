"""Tests for ``ConsoleShelfService`` over the fake unit of work."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from domain.playtime import Playtime
from domain.rom import Rom
from domain.rom_achievement_progress import SNAPSHOT_FETCHED_AT_KEY, RomAchievementProgress
from domain.rom_install import RomInstall
from domain.rom_save_sync_state import RomSaveSyncState
from services.console_shelf import MAX_PAGE_SIZE, ConsoleShelfService, ConsoleShelfServiceConfig

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


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
def service(uow, settings, logs) -> ConsoleShelfService:
    return ConsoleShelfService(
        config=ConsoleShelfServiceConfig(
            uow_factory=FakeUnitOfWorkFactory(uow=uow),
            settings=settings,
            clock=FakeClock(now=NOW),
            log_debug=logs.append,
        )
    )


def _rom(
    rom_id: int,
    slug: str,
    *,
    bound: bool = True,
    name: str | None = None,
    group: str | None = None,
    ra_id: int | None = None,
) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug=slug,
        name=name or f"Game {rom_id}",
        fs_name=f"g{rom_id}",
        shortcut_app_id=(5000 + rom_id) if bound else None,
        last_synced_at="2026-01-01T00:00:00",
        ra_id=ra_id,
        sibling_group_key=group,
    )


def _seed(uow, *roms, playtime=None, names=None):
    with uow:
        for rom in roms:
            uow.roms.save(rom)
        for rom_id, (seconds, last) in (playtime or {}).items():
            uow.playtime.save(rom_id, Playtime(total_seconds=seconds, session_count=1, last_played=last))
        if names is not None:
            uow.kv_config.set("platform_names", json.dumps(names))


class TestGetConsoleShelf:
    def test_empty_library(self, service):
        assert service.get_console_shelf() == {"success": True, "enabled": True, "consoles": []}

    def test_ranks_counts_and_names(self, service, uow, logs):
        _seed(
            uow,
            _rom(1, "ps2"),
            _rom(2, "ps2"),
            _rom(3, "ngc"),
            _rom(4, "snes", bound=False),  # unbound: not in Steam
            playtime={1: (100 * 3600, _ago(700)), 3: (3600, _ago(1))},
            names={"ps2": "PlayStation 2", "ngc": "GameCube"},
        )
        result = service.get_console_shelf()
        assert result["consoles"] == [
            {
                "platform_slug": "ngc",
                "name": "GameCube",
                "game_count": 1,
                "last_played": _ago(1),
                "play_seconds": 3600,
                "cover_app_id": 5003,
            },
            {
                "platform_slug": "ps2",
                "name": "PlayStation 2",
                "game_count": 2,
                "last_played": _ago(700),
                "play_seconds": 360000,
                "cover_app_id": 5001,
            },
        ]
        assert logs == ["Console shelf: 2 consoles from 3 games"]

    def test_ps1_is_shown_as_playstation_1_on_the_shelf_and_its_page(self, service, uow):
        _seed(uow, _rom(1, "psx"), names={"psx": "PlayStation"})
        assert service.get_console_shelf()["consoles"][0]["name"] == "PlayStation 1"
        assert service.get_console_games("psx", 0, 30)["name"] == "PlayStation 1"

    def test_name_falls_back_to_slug_on_a_corrupt_cache(self, service, uow):
        _seed(uow, _rom(1, "gba"))
        with uow:
            uow.kv_config.set("platform_names", "{not json")
        assert service.get_console_shelf()["consoles"][0]["name"] == "gba"

    def test_unbound_siblings_play_time_folds_into_the_bound_version(self, service, uow):
        _seed(
            uow,
            _rom(1, "snes", group="g1"),
            _rom(2, "snes", bound=False, group="g1"),
            _rom(3, "snes", bound=False),  # orphan without a group: ignored
            playtime={1: (60, _ago(5)), 2: (40, _ago(1)), 3: (999, _ago(0))},
        )
        [console] = service.get_console_shelf()["consoles"]
        assert console["play_seconds"] == 100
        assert console["last_played"] == _ago(1)

    def test_disabled_toggle_is_reported(self, service, settings):
        settings["collector_home_shelf"] = False
        assert service.get_console_shelf()["enabled"] is False
        assert service.home_shelf_enabled() is False


class TestGetConsoleGames:
    def test_page_shape_continue_first_and_chips(self, service, uow, settings):
        settings["save_sync_enabled"] = True
        _seed(
            uow,
            _rom(1, "ps2", name="Zone of the Enders", ra_id=100),
            _rom(2, "ps2", name="Okami", ra_id=200),
            _rom(3, "ps2", name="Ape Escape"),
            _rom(9, "ngc"),
            playtime={2: (7200, _ago(1)), 1: (60, _ago(30))},
            names={"ps2": "PlayStation 2"},
        )
        with uow:
            uow.rom_installs.save(
                RomInstall(
                    rom_id=2,
                    file_path="/roms/okami.iso",
                    rom_dir=None,
                    platform_slug="ps2",
                    system="ps2",
                    installed_at="t",
                )
            )
            state = RomSaveSyncState()
            state.adopt_baseline("okami.ps2", tracked_save_id=1, last_sync_hash="h")
            state.mark_sync_evaluated("2026-11-25T00:00:00+00:00")
            uow.rom_save_sync_states.save(2, state)
            uow.rom_achievement_progress.replace_all(
                {
                    1: RomAchievementProgress.observed(
                        earned=5, earned_hardcore=5, total=30, highest_award_kind="beaten-hardcore", fetched_at="T"
                    )
                }
            )
            uow.kv_config.set(SNAPSHOT_FETCHED_AT_KEY, "T")

        result = service.get_console_games("ps2", 0, 100)

        assert {k: v for k, v in result.items() if k != "games"} == {
            "success": True,
            "platform_slug": "ps2",
            "name": "PlayStation 2",
            "total": 3,
            "offset": 0,
            "continue_rom_id": 2,
            "save_sync_enabled": True,
            "achievements_fetched_at": "T",
        }
        assert [g["rom_id"] for g in result["games"]] == [2, 3, 1]
        okami, ape, zone = result["games"]
        assert okami == {
            "rom_id": 2,
            "app_id": 5002,
            "name": "Okami",
            "last_played": _ago(1),
            "play_seconds": 7200,
            "installed": True,
            "save_sync": {"status": "synced", "label": None, "last_sync_check_at": "2026-11-25T00:00:00+00:00"},
            "achievements": None,
            "has_ra_set": True,
        }
        assert ape["save_sync"] is None
        assert ape["has_ra_set"] is False
        assert ape["installed"] is False
        assert zone["achievements"] == {
            "earned": 5,
            "total": 30,
            "earned_hardcore": 5,
            "hardcore": True,
            "award": "beaten",
            "fetched_at": "T",
        }

    def test_paging_windows(self, service, uow):
        _seed(uow, *[_rom(i, "gba", name=f"G{i:03d}") for i in range(1, 6)])
        first = service.get_console_games("gba", 0, 2)
        rest = service.get_console_games("gba", 4, 2)
        beyond = service.get_console_games("gba", 10, 2)
        assert [g["rom_id"] for g in first["games"]] == [1, 2]
        assert [g["rom_id"] for g in rest["games"]] == [5]
        assert beyond["games"] == []
        assert first["total"] == rest["total"] == beyond["total"] == 5
        assert first["continue_rom_id"] is None
        assert first["achievements_fetched_at"] is None

    def test_unknown_console_is_an_empty_page(self, service):
        result = service.get_console_games("dreamcast", 0, 10)
        assert result["success"] is True
        assert result["total"] == 0
        assert result["games"] == []
        assert result["name"] == "dreamcast"

    @pytest.mark.parametrize(
        ("slug", "offset", "limit", "reason"),
        [
            ("", 0, 10, "invalid_platform"),
            (None, 0, 10, "invalid_platform"),
            ("ps2", -1, 10, "invalid_page"),
            ("ps2", "0", 10, "invalid_page"),
            ("ps2", True, 10, "invalid_page"),
            ("ps2", 0, 0, "invalid_page"),
            ("ps2", 0, MAX_PAGE_SIZE + 1, "invalid_page"),
            ("ps2", 0, None, "invalid_page"),
        ],
    )
    def test_invalid_input_answers_with_the_failure_shape(self, service, slug, offset, limit, reason):
        result = service.get_console_games(slug, offset, limit)
        assert set(result) == {"success", "reason", "message"}
        assert result["success"] is False
        assert result["reason"] == reason

    def test_reads_only(self, service, uow):
        _seed(uow, _rom(1, "ps2"))
        before = uow.rom_achievement_progress.replace_count
        service.get_console_shelf()
        service.get_console_games("ps2", 0, 10)
        assert uow.rom_achievement_progress.replace_count == before


class _Pack:
    """An icon pack holding generated bytes per path, recording every read."""

    def __init__(self, files: dict[tuple[str, ...], bytes]) -> None:
        self.files = files
        self.reads: list[tuple[tuple[str, ...], int]] = []

    def read_art(self, parts: tuple[str, ...], limit: int) -> bytes | None:
        self.reads.append((parts, limit))
        return self.files.get(parts)


class TestFamilyArt:
    def _service(self, uow, settings, logs, pack):
        return ConsoleShelfService(
            config=ConsoleShelfServiceConfig(
                uow_factory=FakeUnitOfWorkFactory(uow=uow),
                settings=settings,
                clock=FakeClock(now=NOW),
                log_debug=logs.append,
                icon_pack=pack,
            )
        )

    def test_serves_the_file_base64_encoded(self, uow, settings, logs):
        pack = _Pack({("families", "sega", "hero.png"): b"\x89PNG fixture"})
        answer = self._service(uow, settings, logs, pack).get_family_art("sega", "hero")
        assert answer == {"success": True, "family": "sega", "kind": "hero", "base64": "iVBORyBmaXh0dXJl"}
        assert pack.reads == [(("families", "sega", "hero.png"), 8 * 1024 * 1024)]

    def test_a_missing_file_is_an_answer_not_a_failure(self, uow, settings, logs):
        answer = self._service(uow, settings, logs, _Pack({})).get_family_art("xbox", "logo")
        assert answer == {"success": True, "family": "xbox", "kind": "logo", "base64": None}

    def test_no_pack_at_all_answers_no_art(self, uow, settings, logs):
        answer = self._service(uow, settings, logs, None).get_family_art("retro", "hero")
        assert answer["success"] is True
        assert answer["base64"] is None

    @pytest.mark.parametrize(
        ("family", "kind"),
        [
            ("..", "hero"),
            ("sega/../../x", "hero"),
            ("sega", "../hero"),
            ("snes", "hero"),
            ("sega", "cover"),
            (1, "hero"),
        ],
    )
    def test_refuses_anything_outside_the_allow_lists_before_reading(self, uow, settings, logs, family, kind):
        pack = _Pack({})
        answer = self._service(uow, settings, logs, pack).get_family_art(family, kind)
        assert answer["success"] is False
        assert answer["reason"] == "invalid_argument"
        assert pack.reads == []
