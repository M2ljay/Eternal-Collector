"""Tests for RetroAchievementsCheckService — session-start config check and session-end log check."""

from __future__ import annotations

import asyncio

import pytest
from fakes.fake_retroachievements_config import FakeRetroAchievementsConfigReader
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from domain.retroachievements import RaStatus
from domain.rom import Rom
from services.retroachievements_check import RetroAchievementsCheckService, RetroAchievementsCheckServiceConfig

PCSX2_DIR = r"C:\Users\v\AppData\Roaming\emudeck\Emulators\PCSX2-Qt"
PCSX2_CMD = rf'"{PCSX2_DIR}\pcsx2-qtx64.exe" -nogui -fullscreen "C:\Emulation\roms\ps2\game.chd"'
DUCK_CMD = r'"C:\E\duckstation\duckstation-qt-x64-ReleaseLTCG.exe" "C:\Emulation\roms\psx\g.chd"'
DOLPHIN_CMD = r'"C:\E\Dolphin-x64\Dolphin.exe" -b -e "C:\Emulation\roms\wii\g.rvz"'
AZAHAR_CMD = r'"C:\E\azahar\azahar.exe" "C:\Emulation\roms\n3ds\g.3ds"'

OK = RaStatus(enabled=True, signed_in=True)
SIGNED_OUT = RaStatus(enabled=True, signed_in=False)
OFF = RaStatus(enabled=False, signed_in=False)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _seed(uow: FakeUnitOfWork, *, rom_id: int = 1, platform_slug: str = "ps2", command: str | None = PCSX2_CMD) -> None:
    uow.roms.save(
        Rom(
            rom_id=rom_id,
            platform_slug=platform_slug,
            name="g",
            fs_name="g",
            shortcut_app_id=42,
            last_synced_at="2026-01-01T00:00:00+00:00",
            applied_launch_options=command,
        )
    )


def _make(event_loop, *, reader, settings=None, seed=None):
    uow = FakeUnitOfWork()
    (seed or _seed)(uow)
    debug: list[str] = []
    service = RetroAchievementsCheckService(
        config=RetroAchievementsCheckServiceConfig(
            loop=event_loop,
            uow_factory=FakeUnitOfWorkFactory(uow),
            settings=settings if settings is not None else {},
            config_reader=reader,
            clock=FakeClock(),
            log_debug=debug.append,
        )
    )
    return service, debug


def _run(loop, coro):
    return loop.run_until_complete(coro)


class TestSessionStart:
    def test_signed_out(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=SIGNED_OUT)
        service, _ = _make(event_loop, reader=reader)
        assert _run(event_loop, service.check_session_start(1)) == {
            "warning": "RetroAchievements isn't working in PCSX2: not signed in."
        }
        assert reader.status_calls == [("pcsx2", PCSX2_DIR)]

    def test_turned_off(self, event_loop):
        service, _ = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=OFF))
        warning = _run(event_loop, service.check_session_start(1))["warning"]
        assert warning == "RetroAchievements isn't working in PCSX2: achievements are turned off."

    def test_working_gives_no_warning(self, event_loop):
        service, _ = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=OK))
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}

    def test_missing_settings_file_gives_no_warning(self, event_loop):
        service, debug = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=None))
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert any("no PCSX2 settings" in m for m in debug)

    def test_switched_off_by_the_user(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=OFF)
        service, _ = _make(event_loop, reader=reader, settings={"retroachievements_warning": False})
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert reader.status_calls == []

    def test_emulator_without_ra_is_not_checked(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=OFF)
        service, _ = _make(event_loop, reader=reader, seed=lambda u: _seed(u, platform_slug="n3ds", command=AZAHAR_CMD))
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert reader.status_calls == []

    def test_dolphin_wii_is_not_checked(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=OFF)
        service, _ = _make(event_loop, reader=reader, seed=lambda u: _seed(u, platform_slug="wii", command=DOLPHIN_CMD))
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert reader.status_calls == []

    @pytest.mark.parametrize("command", [None, "", "flatpak run net.retrodeck.retrodeck x"])
    def test_no_windows_command(self, event_loop, command):
        reader = FakeRetroAchievementsConfigReader(status=OFF)
        service, _ = _make(event_loop, reader=reader, seed=lambda u: _seed(u, command=command))
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}

    def test_unknown_rom(self, event_loop):
        service, _ = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=OFF))
        assert _run(event_loop, service.check_session_start(99)) == {"warning": None}

    def test_reader_error_never_reaches_the_caller(self, event_loop):
        class Boom(FakeRetroAchievementsConfigReader):
            def read_status(self, emulator_id, emulator_dir):
                raise OSError("disk gone")

        service, debug = _make(event_loop, reader=Boom())
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert any("start check for rom 1 failed" in m for m in debug)

    def test_debug_log_carries_booleans_only(self, event_loop):
        service, debug = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=SIGNED_OUT))
        _run(event_loop, service.check_session_start(1))
        assert any("enabled=True signed_in=False" in m for m in debug)


class TestSessionEnd:
    def test_login_failure_after_a_clean_start(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=OK, login_failed=True)
        service, _ = _make(event_loop, reader=reader)
        assert _run(event_loop, service.check_session_start(1)) == {"warning": None}
        assert _run(event_loop, service.check_session_end(1)) == {
            "warning": "RetroAchievements didn't work in PCSX2 last session: login failed."
        }
        assert reader.log_calls == [("pcsx2", PCSX2_DIR, FakeClock().time())]

    def test_only_one_end_check_per_session(self, event_loop):
        service, _ = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=OK, login_failed=True))
        _run(event_loop, service.check_session_start(1))
        assert _run(event_loop, service.check_session_end(1))["warning"] is not None
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}

    def test_no_second_notice_after_a_start_warning(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=SIGNED_OUT, login_failed=True)
        service, _ = _make(event_loop, reader=reader)
        assert _run(event_loop, service.check_session_start(1))["warning"] is not None
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}
        assert reader.log_calls == []

    def test_emulator_without_a_log_check(self, event_loop):
        reader = FakeRetroAchievementsConfigReader(status=OK, login_failed=True)
        service, _ = _make(event_loop, reader=reader, seed=lambda u: _seed(u, platform_slug="psx", command=DUCK_CMD))
        _run(event_loop, service.check_session_start(1))
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}
        assert reader.log_calls == []

    def test_end_without_a_start(self, event_loop):
        service, _ = _make(event_loop, reader=FakeRetroAchievementsConfigReader(status=OK, login_failed=True))
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}

    def test_switched_off_between_start_and_end(self, event_loop):
        settings: dict = {}
        reader = FakeRetroAchievementsConfigReader(status=OK, login_failed=True)
        service, _ = _make(event_loop, reader=reader, settings=settings)
        _run(event_loop, service.check_session_start(1))
        settings["retroachievements_warning"] = False
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}

    def test_log_read_error_never_reaches_the_caller(self, event_loop):
        class Boom(FakeRetroAchievementsConfigReader):
            def login_failed_since(self, emulator_id, emulator_dir, since):
                raise OSError("gone")

        service, _ = _make(event_loop, reader=Boom(status=OK))
        _run(event_loop, service.check_session_start(1))
        assert _run(event_loop, service.check_session_end(1)) == {"warning": None}
