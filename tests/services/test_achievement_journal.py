"""Tests for ``AchievementJournalService`` over the fake unit of work and a fake RetroAchievements Web API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fakes.fake_retroachievements_web import FakeRetroAchievementsWeb
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from domain.ra_game_journal import MAX_NOTES_CHARS, AchievementGoal, RaGameJournal
from domain.rom import Rom
from lib.errors import RaWebApiError
from services.achievement_journal import (
    MAX_REFRESH_GAMES,
    AchievementJournalService,
    AchievementJournalServiceConfig,
)

KEY = "AbCdEf0123456789AbCdEf0123456789"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


class _Persister:
    def __init__(self) -> None:
        self.saves = 0

    def save_settings(self) -> None:
        self.saves += 1


def _seed_rom(uow: FakeUnitOfWork, rom_id: int, *, ra_id: int | None, name: str = "Sonic", app_id: int | None = 5000):
    with uow:
        uow.roms.save(
            Rom(
                rom_id=rom_id,
                platform_slug="genesis",
                name=name,
                fs_name=f"{rom_id}.md",
                shortcut_app_id=app_id,
                last_synced_at="2026-01-01T00:00:00",
                ra_id=ra_id,
            )
        )


@pytest.fixture
def uow() -> FakeUnitOfWork:
    u = FakeUnitOfWork()
    _seed_rom(u, 1, ra_id=77)
    _seed_rom(u, 2, ra_id=None, name="Homebrew", app_id=5002)
    _seed_rom(u, 3, ra_id=88, name="Streets of Rage", app_id=None)
    return u


@pytest.fixture
def settings() -> dict[str, Any]:
    return {}


@pytest.fixture
def ra_web() -> FakeRetroAchievementsWeb:
    return FakeRetroAchievementsWeb()


@pytest.fixture
def persister() -> _Persister:
    return _Persister()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(now=NOW)


@pytest.fixture
def logs() -> list[str]:
    return []


@pytest.fixture
async def service(uow, settings, ra_web, persister, clock, logs) -> AchievementJournalService:
    return AchievementJournalService(
        config=AchievementJournalServiceConfig(
            uow_factory=FakeUnitOfWorkFactory(uow=uow),
            ra_web=ra_web,
            settings=settings,
            settings_persister=persister,
            loop=asyncio.get_running_loop(),
            logger=logging.getLogger("test.achievement_journal"),
            clock=clock,
            log_debug=logs.append,
        )
    )


def _configure(settings: dict[str, Any]) -> None:
    settings["ra_web_username"] = "Jamiras"
    settings["ra_web_api_key"] = KEY


def _achievement(achievement_id: object = 11, **overrides: Any) -> dict[str, Any]:
    return {
        "achievement_id": achievement_id,
        "title": f"Goal {achievement_id}",
        "description": "d",
        "points": 10,
    } | overrides


class TestJournal:
    def test_empty_journal_for_a_game_with_a_set(self, service):
        result = service.get_journal(1)
        assert result["success"] is True
        assert result["ra_game_id"] == 77
        assert result["game_title"] == "Sonic"
        assert result["goals"] == []
        assert result["notes"] == ""
        assert result["game_url"] == "https://retroachievements.org/game/77"
        assert result["web_api_configured"] is False

    @pytest.mark.parametrize(
        ("rom_id", "reason"),
        [(2, "no_ra_id"), (999, "not_found"), (0, "invalid_rom"), ("x", "invalid_rom"), (None, "invalid_rom")],
    )
    def test_bad_roms_use_the_canonical_failure_shape(self, service, rom_id, reason):
        result = service.get_journal(rom_id)
        assert result["success"] is False
        assert result["reason"] == reason
        assert isinstance(result["message"], str)

    def test_notes_round_trip_and_clearing_deletes_the_journal(self, service, uow):
        assert service.save_notes(1, "  spin dash  ")["notes"] == "spin dash"
        assert service.get_journal("1")["notes_updated_at"] == "2026-11-26T12:00:00+00:00"
        assert service.save_notes(1, "")["success"] is True
        assert uow.ra_game_journals.get(77) is None

    def test_notes_validation(self, service):
        assert service.save_notes(1, 5)["reason"] == "invalid_notes"
        result = service.save_notes(1, "n" * (MAX_NOTES_CHARS + 1))
        assert result["reason"] == "notes_too_long"
        assert service.save_notes(2, "x")["reason"] == "no_ra_id"

    def test_journal_is_shared_by_every_version_of_a_game(self, service, uow):
        _seed_rom(uow, 4, ra_id=77, name="Sonic (Rev 1)", app_id=None)
        service.save_notes(1, "shared")
        assert service.get_journal(4)["notes"] == "shared"


class TestGoals:
    def test_pin_unpin(self, service, uow):
        result = service.pin_goal(1, _achievement())
        assert result["success"] is True
        assert [g["achievement_id"] for g in result["goals"]] == [11]
        assert service.pin_goal(1, _achievement())["success"] is True
        assert service.unpin_goal(1, 11)["goals"] == []
        assert uow.ra_game_journals.get(77) is None

    def test_unpin_keeps_a_journal_with_notes(self, service, uow):
        service.save_notes(1, "keep")
        service.pin_goal(1, _achievement())
        service.unpin_goal(1, "11")
        journal = uow.ra_game_journals.get(77)
        assert journal is not None
        assert journal.notes == "keep"

    @pytest.mark.parametrize(
        "achievement",
        [
            None,
            "x",
            _achievement(achievement_id=0),
            _achievement(achievement_id="abc"),
            _achievement(title=""),
            _achievement(title=5),
            _achievement(points=-3),
            _achievement(points="10"),
        ],
    )
    def test_pin_validates_the_wire(self, service, achievement):
        result = service.pin_goal(1, achievement)
        assert result["success"] is False
        assert result["reason"] == "invalid_achievement"

    def test_unpin_validates(self, service):
        assert service.unpin_goal(1, "nope")["reason"] == "invalid_achievement"

    def test_record_unlocks_ticks_goals_off(self, service):
        service.pin_goal(1, _achievement(11))
        service.pin_goal(1, _achievement(12))
        result = service.record_goal_unlocks(
            1,
            [
                {"achievement_id": 11, "unlocked_at": "2025-02-14 15:45:38", "hardcore": True},
                {"achievement_id": 99, "unlocked_at": "2025-02-14 15:45:38", "hardcore": False},
                {"achievement_id": 12, "unlocked_at": "garbage"},
                "bad",
            ],
        )
        assert result == {"success": True, "changed": 1}
        goals = {g["achievement_id"]: g for g in service.get_journal(1)["goals"]}
        assert goals[11]["unlocked_at"] == "2025-02-14T15:45:38Z"
        assert goals[11]["unlocked_hardcore"] is True
        assert goals[12]["unlocked_at"] is None
        assert (
            service.record_goal_unlocks(1, [{"achievement_id": 11, "unlocked_at": "2025-02-15 00:00:00"}])["changed"]
            == 0
        )

    def test_record_unlocks_without_a_journal_writes_nothing(self, service, uow):
        assert service.record_goal_unlocks(1, [{"achievement_id": 11, "unlocked_at": "2025-02-14 15:45:38"}]) == {
            "success": True,
            "changed": 0,
        }
        assert uow.ra_game_journals.get(77) is None
        assert service.record_goal_unlocks(1, "x")["reason"] == "invalid_unlocks"

    def test_overview_orders_open_then_done_and_carries_app_ids(self, service, clock):
        service.pin_goal(3, _achievement(31))
        clock.advance(60)
        service.pin_goal(1, _achievement(11))
        service.pin_goal(1, _achievement(12))
        service.record_goal_unlocks(1, [{"achievement_id": 12, "unlocked_at": "2025-01-01 00:00:00"}])

        overview = service.get_goals_overview()
        assert [g["achievement_id"] for g in overview["goals"]] == [31, 11, 12]
        assert overview["open_count"] == 2
        by_id = {g["achievement_id"]: g for g in overview["goals"]}
        assert by_id[11]["app_id"] == 5000
        assert by_id[31]["app_id"] is None
        assert by_id[31]["rom_id"] == 3
        assert by_id[11]["rom_id"] == 1
        assert by_id[31]["game_title"] == "Streets of Rage"
        assert by_id[11]["achievement_url"] == "https://retroachievements.org/achievement/11"


class TestWebApiSettings:
    def test_save_masks_and_persists(self, service, settings, persister):
        assert service.save_web_api(" Jamiras ", KEY) == {"success": True}
        assert settings == {"ra_web_username": "Jamiras", "ra_web_api_key": KEY}
        assert persister.saves == 1
        assert service.web_api_configured() is True

    def test_mask_keeps_the_stored_key(self, service, settings):
        _configure(settings)
        assert service.save_web_api("Other", "••••") == {"success": True}
        assert settings["ra_web_api_key"] == KEY
        assert settings["ra_web_username"] == "Other"

    @pytest.mark.parametrize(
        ("username", "key", "reason"),
        [
            ("", KEY, "invalid_username"),
            ("bad name!", KEY, "invalid_username"),
            (None, KEY, "invalid_username"),
            ("Jamiras", "short", "invalid_api_key"),
            ("Jamiras", "has spaces in it 0123456789", "invalid_api_key"),
            ("Jamiras", None, "invalid_api_key"),
            ("Jamiras", "••••", "invalid_api_key"),
        ],
    )
    def test_save_refuses_malformed_input(self, service, settings, persister, username, key, reason):
        result = service.save_web_api(username, key)
        assert result["reason"] == reason
        assert settings == {}
        assert persister.saves == 0

    def test_clear(self, service, settings):
        _configure(settings)
        assert service.clear_web_api() == {"success": True}
        assert service.web_api_configured() is False

    async def test_verify_with_candidate_and_stored_key(self, service, settings, ra_web):
        assert (await service.verify_web_api("Jamiras", KEY))["success"] is True
        _configure(settings)
        assert (await service.verify_web_api("", "••••"))["success"] is True
        assert ra_web.calls[-1] == ("verify", "Jamiras", KEY)

    @pytest.mark.parametrize(
        ("status", "reason"), [(401, "auth_failed"), (404, "not_found"), (None, "server_unreachable")]
    )
    async def test_verify_failures(self, service, ra_web, status, reason):
        ra_web.verify_error = RaWebApiError(status, "x")
        result = await service.verify_web_api("Jamiras", KEY)
        assert result["reason"] == reason
        assert KEY not in result["message"]

    async def test_verify_refuses_malformed_before_any_request(self, service, ra_web):
        assert (await service.verify_web_api("Jamiras", "nope"))["reason"] == "invalid_api_key"
        assert (await service.verify_web_api("", KEY))["reason"] == "invalid_username"
        assert ra_web.calls == []

    def test_debug_log_never_carries_the_key(self, service, logs):
        service.save_web_api("Jamiras", KEY)
        assert all(KEY not in line for line in logs)


def _timeline_entry(achievement_id: int, game_id: int, date: str, hardcore: int = 0) -> dict[str, Any]:
    return {
        "Date": date,
        "HardcoreMode": hardcore,
        "AchievementID": achievement_id,
        "Title": f"A{achievement_id}",
        "Points": 5,
        "GameID": game_id,
        "GameTitle": "Sonic",
        "ConsoleName": "Genesis/Mega Drive",
    }


class TestTimeline:
    async def test_needs_a_key(self, service, ra_web):
        result = await service.get_unlock_timeline(30, False)
        assert result["reason"] == "no_web_api_key"
        assert ra_web.calls == []

    @pytest.mark.parametrize("days", [0, 7, "30", True, None])
    async def test_range_is_validated(self, service, settings, days):
        _configure(settings)
        assert (await service.get_unlock_timeline(days, False))["reason"] == "invalid_range"

    async def test_window_cache_and_force(self, service, settings, ra_web, clock):
        _configure(settings)
        ra_web.timeline = [_timeline_entry(1, 77, "2026-11-20 10:00:00"), _timeline_entry(2, 77, "2026-11-25 10:00:00")]

        result = await service.get_unlock_timeline(30, False)
        assert [e["achievement_id"] for e in result["entries"]] == [2, 1]
        now = int(NOW.timestamp())
        assert ra_web.calls == [("earned_between", "Jamiras", now - 30 * 86400, now)]

        await service.get_unlock_timeline(30, False)
        assert len(ra_web.calls) == 1
        await service.get_unlock_timeline(30, True)
        assert len(ra_web.calls) == 2
        clock.advance(11 * 60)
        await service.get_unlock_timeline(30, False)
        assert len(ra_web.calls) == 3

    async def test_ticks_pinned_goals_off(self, service, settings, ra_web):
        _configure(settings)
        service.pin_goal(1, _achievement(2))
        ra_web.timeline = [_timeline_entry(2, 77, "2026-11-25 10:00:00", hardcore=1)]
        await service.get_unlock_timeline(90, False)
        [goal] = service.get_journal(1)["goals"]
        assert goal["unlocked_at"] == "2026-11-25T10:00:00Z"
        assert goal["unlocked_hardcore"] is True

    @pytest.mark.parametrize(
        ("status", "reason"), [(401, "auth_failed"), (429, "rate_limited"), (None, "server_unreachable")]
    )
    async def test_failures(self, service, settings, ra_web, status, reason):
        _configure(settings)
        ra_web.error = RaWebApiError(status, "x")
        result = await service.get_unlock_timeline(365, False)
        assert result == {"success": False, "reason": reason, "message": result["message"]}

    async def test_saving_settings_drops_cached_answers(self, service, settings, ra_web):
        _configure(settings)
        await service.get_unlock_timeline(30, False)
        service.save_web_api("Jamiras", "••••")
        await service.get_unlock_timeline(30, False)
        assert len(ra_web.calls) == 2


def _game_payload(*earned: int, guide: str | None = None) -> dict[str, Any]:
    return {
        "GuideURL": guide,
        "Achievements": {str(a): {"ID": a, "DateEarnedHardcore": "2026-11-01 00:00:00"} for a in earned},
    }


class TestRefreshAndLinks:
    async def test_refresh_needs_a_key(self, service):
        assert (await service.refresh_goals())["reason"] == "no_web_api_key"

    async def test_refresh_ticks_off_and_skips_games_without_open_goals(self, service, settings, ra_web, uow):
        _configure(settings)
        service.pin_goal(1, _achievement(11))
        service.pin_goal(3, _achievement(31))
        service.record_goal_unlocks(3, [{"achievement_id": 31, "unlocked_at": "2026-01-01 00:00:00"}])
        ra_web.games[77] = _game_payload(11)

        result = await service.refresh_goals()
        assert result["success"] is True
        assert (result["refreshed"], result["failed"], result["changed"]) == (1, 0, 1)
        assert ra_web.calls == [("game", "Jamiras", 77)]
        assert result["open_count"] == 0

    async def test_refresh_counts_per_game_failures_but_stops_on_a_refused_key(self, service, settings, ra_web):
        _configure(settings)
        service.pin_goal(1, _achievement(11))
        service.pin_goal(3, _achievement(31))
        ra_web.game_errors[77] = RaWebApiError(500, "x")
        result = await service.refresh_goals()
        assert (result["refreshed"], result["failed"]) == (1, 1)

        ra_web.game_errors[77] = RaWebApiError(401, "x")
        assert (await service.refresh_goals())["reason"] == "auth_failed"

    async def test_refresh_is_capped(self, service, settings, ra_web, uow, clock):
        _configure(settings)
        with uow:
            for game_id in range(1000, 1000 + MAX_REFRESH_GAMES + 3):
                journal = RaGameJournal.opened(ra_game_id=game_id, game_title="G")
                journal.pin_goal(
                    AchievementGoal.pinned(achievement_id=1, title="t", description="", points=1, pinned_at="p")
                )
                uow.ra_game_journals.save(journal)
        await service.refresh_goals()
        assert len(ra_web.calls) == MAX_REFRESH_GAMES

    async def test_links_without_a_key(self, service, ra_web):
        result = await service.get_game_links(1)
        assert result == {
            "success": True,
            "game_url": "https://retroachievements.org/game/77",
            "guide_url": None,
            "web_api_configured": False,
        }
        assert ra_web.calls == []

    async def test_links_with_a_key_are_cached_and_only_safe_guides_pass(self, service, settings, ra_web):
        _configure(settings)
        ra_web.games[77] = _game_payload(guide="https://github.com/RetroAchievements/guides/wiki/Sonic")
        assert (await service.get_game_links(1))[
            "guide_url"
        ] == "https://github.com/RetroAchievements/guides/wiki/Sonic"
        await service.get_game_links(1)
        assert len(ra_web.calls) == 1

        ra_web.games[88] = _game_payload(guide="https://some-fan-site.example/guide")
        assert (await service.get_game_links(3))["guide_url"] is None

    async def test_link_lookup_failure_is_quiet(self, service, settings, ra_web):
        _configure(settings)
        ra_web.error = RaWebApiError(None, "x")
        result = await service.get_game_links(1)
        assert result["success"] is True
        assert result["guide_url"] is None

    async def test_links_bad_rom(self, service):
        assert (await service.get_game_links(2))["reason"] == "no_ra_id"


def test_never_holds_an_emulator_login_reader():
    fields = AchievementJournalServiceConfig.__dataclass_fields__
    assert "config_reader" not in fields
    assert all("RetroAchievementsConfigReader" not in str(f.type) for f in fields.values())
