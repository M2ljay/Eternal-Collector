"""Tests for domain.retroachievements — emulator detection and boolean-only settings parsing."""

from __future__ import annotations

import dataclasses

import pytest

from domain.retroachievements import (
    DOLPHIN,
    PCSX2,
    RETROARCH,
    RaStatus,
    dolphin_status,
    duckstation_status,
    emulator_exe_from_command,
    identify_emulator,
    ini_flag,
    ini_has_value,
    login_failed_warning,
    pcsx2_login_failed,
    pcsx2_status,
    platform_supports_ra,
    ppsspp_status,
    ra_warning,
    retroarch_status,
)

SECRET = "tok3n-SECRET-value-0123456789"
USER = "vonn-test-user"


class TestEmulatorExeFromCommand:
    def test_reads_the_quoted_exe(self):
        exe = r"C:\Users\v\AppData\Roaming\emudeck\Emulators\PCSX2-Qt\pcsx2-qtx64.exe"
        cmd = f'"{exe}" -nogui -fullscreen "C:\\roms\\ps2\\a.iso"'
        assert emulator_exe_from_command(cmd) == exe

    def test_skips_a_leading_launcher_flag(self):
        cmd = r'--title-id-file "C:\Emu\Vita3K\Vita3K.exe" -F -r "C:\roms\psvita\x.psvita"'
        assert emulator_exe_from_command(cmd) == r"C:\Emu\Vita3K\Vita3K.exe"

    def test_retroarch_core_path_is_not_the_exe(self):
        cmd = r'"C:\Emu\RetroArch\retroarch.exe" -L "C:\Emu\RetroArch\cores\snes9x_libretro.dll" "C:\roms\snes\a.sfc"'
        assert emulator_exe_from_command(cmd) == r"C:\Emu\RetroArch\retroarch.exe"

    @pytest.mark.parametrize(
        "cmd", [None, "", "flatpak run net.retrodeck.retrodeck x", '"/usr/bin/foo" "/rom.iso"', '"C:\\a.exe']
    )
    def test_no_windows_exe(self, cmd):
        assert emulator_exe_from_command(cmd) is None


class TestIdentifyEmulator:
    @pytest.mark.parametrize(
        ("exe", "emulator_id"),
        [
            (r"C:\E\PCSX2-Qt\pcsx2-qtx64.exe", "pcsx2"),
            (r"C:\E\duckstation\duckstation-qt-x64-ReleaseLTCG.exe", "duckstation"),
            (r"C:\E\Dolphin-x64\Dolphin.exe", "dolphin"),
            (r"C:\E\PPSSPP\PPSSPPWindows64.exe", "ppsspp"),
            (r"C:\E\RetroArch\retroarch.exe", "retroarch"),
        ],
    )
    def test_known(self, exe, emulator_id):
        emulator = identify_emulator(exe)
        assert emulator is not None
        assert emulator.emulator_id == emulator_id

    @pytest.mark.parametrize("exe", [r"C:\E\Azahar\azahar.exe", r"C:\E\rpcs3\rpcs3.exe", r"C:\E\Cemu\Cemu.exe"])
    def test_unsupported(self, exe):
        assert identify_emulator(exe) is None


class TestPlatformSupportsRa:
    def test_dolphin_gamecube_only(self):
        assert platform_supports_ra(DOLPHIN, "ngc")
        assert not platform_supports_ra(DOLPHIN, "wii")

    def test_retroarch_skips_systems_without_ra(self):
        assert platform_supports_ra(RETROARCH, "snes")
        assert not platform_supports_ra(RETROARCH, "3ds")

    def test_single_system_emulators(self):
        assert platform_supports_ra(PCSX2, "ps2")


class TestIniParsing:
    TEXT = "[Other]\nEnabled = true\n\n[Achievements]\n; comment\nEnabled = False\nenabled=TRUE\nUsername = \nToken=x\n"

    def test_flag_last_occurrence_case_insensitive(self):
        assert ini_flag(self.TEXT, "achievements", "ENABLED") is True

    def test_flag_default_when_absent(self):
        assert ini_flag(self.TEXT, "Achievements", "Missing") is False
        assert ini_flag(self.TEXT, "Achievements", "Missing", default=True) is True

    def test_section_scoping(self):
        assert ini_flag("[Other]\nEnabled = true\n", "Achievements", "Enabled") is False

    def test_has_value_empty_and_present(self):
        assert ini_has_value(self.TEXT, "Achievements", "Username") is False
        assert ini_has_value(self.TEXT, "Achievements", "Token") is True

    def test_quoted_cfg_values(self):
        cfg = 'cheevos_enable = "true"\ncheevos_username = ""\n'
        assert ini_flag(cfg, None, "cheevos_enable") is True
        assert ini_has_value(cfg, None, "cheevos_username") is False


class TestEmulatorStatus:
    def test_pcsx2_token_in_secrets(self):
        ini = f"[Achievements]\nEnabled = true\nUsername = {USER}\n"
        assert pcsx2_status(ini, f"[Achievements]\nToken = {SECRET}\n") == RaStatus(enabled=True, signed_in=True)
        assert pcsx2_status(ini, None) == RaStatus(enabled=True, signed_in=False)

    def test_pcsx2_token_still_in_main_ini(self):
        ini = f"[Achievements]\nEnabled = true\nUsername = {USER}\nToken = {SECRET}\n"
        assert pcsx2_status(ini, None).signed_in is True

    def test_duckstation(self):
        ini = f"[Cheevos]\nEnabled = true\nUsername = {USER}\nToken = {SECRET}\n"
        assert duckstation_status(ini) == RaStatus(enabled=True, signed_in=True)
        assert duckstation_status("[Cheevos]\nEnabled = false\n") == RaStatus(enabled=False, signed_in=False)

    def test_dolphin(self):
        ini = f"[Achievements]\nEnabled = True\nUsername = {USER}\nApiToken = {SECRET}\n"
        assert dolphin_status(ini) == RaStatus(enabled=True, signed_in=True)

    def test_ppsspp_needs_the_token_file(self):
        ini = f"[Achievements]\nAchievementsEnable = True\nAchievementsUserName = {USER}\n"
        assert ppsspp_status(ini, token_file_nonempty=True).signed_in is True
        assert ppsspp_status(ini, token_file_nonempty=False).signed_in is False

    def test_retroarch_token_or_password(self):
        cfg = (
            f'cheevos_enable = "true"\ncheevos_username = "{USER}"\ncheevos_token = "{SECRET}"\ncheevos_password = ""\n'
        )
        assert retroarch_status(cfg) == RaStatus(enabled=True, signed_in=True)
        assert retroarch_status('cheevos_enable = "true"\ncheevos_username = "u"\n').signed_in is False


class TestNoCredentialLeavesTheParser:
    """The parsers answer with booleans; the credential text appears in no result."""

    def test_status_holds_only_booleans_and_never_the_secret(self):
        ini = f"[Cheevos]\nEnabled = true\nUsername = {USER}\nToken = {SECRET}\n"
        status = duckstation_status(ini)
        for field in dataclasses.fields(status):
            assert type(getattr(status, field.name)) is bool
        assert SECRET not in repr(status)
        assert USER not in repr(status)

    def test_presence_check_returns_a_bool(self):
        result = ini_has_value(f"[A]\nToken = {SECRET}\n", "A", "Token")
        assert result is True
        assert type(result) is bool


class TestLogAndMessages:
    def test_pcsx2_login_failure_line(self):
        assert pcsx2_login_failed("[   12.3] Achievements error: Login failed: Invalid token\n")
        assert not pcsx2_login_failed("Achievements: Achievement Foo (1) for game 2 unlocked\n")

    def test_messages(self):
        assert ra_warning("PCSX2", RaStatus(enabled=False, signed_in=True)) == (
            "RetroAchievements isn't working in PCSX2: achievements are turned off."
        )
        assert ra_warning("PCSX2", RaStatus(enabled=True, signed_in=False)) == (
            "RetroAchievements isn't working in PCSX2: not signed in."
        )
        assert ra_warning("PCSX2", RaStatus(enabled=True, signed_in=True)) is None
        assert "login failed" in login_failed_warning("PCSX2")
