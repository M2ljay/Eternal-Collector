"""Pure RetroAchievements readiness rules for the standalone emulators and RetroArch.

What belongs here: which emulator a baked launch command runs, whether that
emulator and the ROM's platform support RetroAchievements at all, where each
emulator keeps its RetroAchievements settings relative to its own folder, and
turning the text of those files into booleans — enabled, signed in, login failed.

Credentials stay out of every result. A parser here answers only whether a
username or token key holds a non-empty value; the value never leaves the
function that tested it, and nothing here returns, stores or logs it.
Reading the files is ``adapters/retroachievements_config.py``'s job.
"""

from __future__ import annotations

import ntpath
from dataclasses import dataclass

PCSX2 = "pcsx2"
DUCKSTATION = "duckstation"
DOLPHIN = "dolphin"
PPSSPP = "ppsspp"
RETROARCH = "retroarch"


@dataclass(frozen=True)
class RaEmulator:
    """One emulator that speaks RetroAchievements, as The Collector recognises it."""

    emulator_id: str
    display_name: str
    exe_prefix: str


# Matched against the lowercased file name of the exe a launch command runs.
# EmuDeck for Windows ships pcsx2-qtx64.exe, duckstation-qt-x64-ReleaseLTCG.exe,
# Dolphin.exe, PPSSPPWindows64.exe and retroarch.exe.
RA_EMULATORS: tuple[RaEmulator, ...] = (
    RaEmulator(PCSX2, "PCSX2", "pcsx2"),
    RaEmulator(DUCKSTATION, "DuckStation", "duckstation"),
    RaEmulator(DOLPHIN, "Dolphin", "dolphin"),
    RaEmulator(PPSSPP, "PPSSPP", "ppsspp"),
    RaEmulator(RETROARCH, "RetroArch", "retroarch"),
)

# RetroAchievements has a GameCube console but no Wii one, so Dolphin is only
# checked for GameCube ROMs (RomM's slug is ``ngc``; the others are the folder
# names front ends use).
_DOLPHIN_RA_PLATFORMS = frozenset({"ngc", "gc", "gamecube"})
# Systems RetroAchievements has no console for, which a RetroArch core can
# still run.
_NO_RA_PLATFORMS = frozenset(
    {
        "3ds",
        "n3ds",
        "new-nintendo-3ds",
        "wii",
        "wiiu",
        "switch",
        "ps3",
        "ps4",
        "psvita",
        "xbox",
        "xbox360",
        "win",
    }
)

# Settings files, relative to the folder holding the emulator's exe. These are
# the portable layouts EmuDeck for Windows sets up (emudeck-we
# functions/EmuScripts/emuDeck<Emu>.ps1).
PCSX2_INI = ("inis", "PCSX2.ini")
# PCSX2 moves the token out of PCSX2.ini into inis\secrets.ini on start
# (pcsx2 Achievements.cpp Achievements::Initialize; QtHost.cpp secrets layer).
PCSX2_SECRETS_INI = ("inis", "secrets.ini")
PCSX2_LOG = ("logs", "emulog.txt")
DUCKSTATION_INI = ("settings.ini",)
DOLPHIN_RA_INI = ("User", "Config", "RetroAchievements.ini")
PPSSPP_INI = ("memstick", "PSP", "SYSTEM", "ppsspp.ini")
# PPSSPP keeps the token in its own file, never in ppsspp.ini
# (ppsspp UI/NativeApp.cpp GetSecretPath: SYSTEM/ppsspp_<name>.dat).
PPSSPP_TOKEN_FILE = ("memstick", "PSP", "SYSTEM", "ppsspp_retroachievements.dat")
RETROARCH_CFG = ("retroarch.cfg",)

# pcsx2 Achievements.cpp: ClientLoginWithTokenCallback -> ReportFmtError("Login
# failed: {}") -> ReportError prefixes "Achievements error: ". File logging is on
# by default (VMManager.cpp, Logging/EnableFileLogging = true). The other
# emulators do not log to a file by default, so only PCSX2 gets the post-session
# check.
_PCSX2_LOGIN_FAILED = "achievements error: login failed"

_TRUE_WORDS = frozenset({"true", "1", "yes", "on"})


@dataclass(frozen=True)
class RaStatus:
    """Whether RetroAchievements is switched on, and whether a login is stored. Booleans only."""

    enabled: bool
    signed_in: bool


def emulator_exe_from_command(command: str | None) -> str | None:
    """The quoted ``.exe`` a baked Windows launch command runs, or ``None``.

    The EmuDeck for Windows bake always quotes the emulator's path; a leading
    ``rom-launcher`` flag such as ``--title-id-file`` is skipped.
    """
    if not command:
        return None
    rest = command
    while True:
        start = rest.find('"')
        if start < 0:
            return None
        end = rest.find('"', start + 1)
        if end < 0:
            return None
        token = rest[start + 1 : end]
        if token.lower().endswith(".exe"):
            return token
        rest = rest[end + 1 :]


def identify_emulator(exe_path: str) -> RaEmulator | None:
    """The RetroAchievements-capable emulator *exe_path* is, or ``None``."""
    name = ntpath.basename(exe_path).lower()
    return next((e for e in RA_EMULATORS if name.startswith(e.exe_prefix)), None)


def platform_supports_ra(emulator_id: str, platform_slug: str) -> bool:
    """Whether RetroAchievements has achievements for *platform_slug* on this emulator."""
    slug = platform_slug.lower()
    if emulator_id == DOLPHIN:
        return slug in _DOLPHIN_RA_PLATFORMS
    return slug not in _NO_RA_PLATFORMS


def has_login_log_check(emulator_id: str) -> bool:
    """Whether the emulator writes a RetroAchievements login failure to a log file by default."""
    return emulator_id == PCSX2


def _is_true(value: str) -> bool:
    return value.strip().strip('"').strip().lower() in _TRUE_WORDS


def _ini_lines(text: str, section: str | None):
    """Yield ``(key_lower, raw_value)`` for every ``key = value`` line in *section*.

    *section* ``None`` means a file without sections (``retroarch.cfg``).
    """
    wanted = section.lower() if section is not None else None
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().lower()
            continue
        if wanted is not None and current != wanted:
            continue
        key, sep, value = stripped.partition("=")
        if sep:
            yield key.strip().lower(), value


def ini_flag(text: str, section: str | None, key: str, *, default: bool = False) -> bool:
    """The boolean *key* holds in *section* (last occurrence wins), or *default* when absent."""
    wanted = key.lower()
    result = default
    for name, value in _ini_lines(text, section):
        if name == wanted:
            result = _is_true(value)
    return result


def ini_has_value(text: str, section: str | None, key: str) -> bool:
    """Whether *key* in *section* holds a non-empty value. Returns only that answer."""
    wanted = key.lower()
    present = False
    for name, value in _ini_lines(text, section):
        if name == wanted:
            present = bool(value.strip().strip('"').strip())
    return present


def pcsx2_status(ini_text: str, secrets_text: str | None) -> RaStatus:
    """PCSX2: ``[Achievements] Enabled``; signed in = ``Username`` plus a ``Token`` in either file."""
    section = "Achievements"
    token = ini_has_value(ini_text, section, "Token") or (
        secrets_text is not None and ini_has_value(secrets_text, section, "Token")
    )
    return RaStatus(
        enabled=ini_flag(ini_text, section, "Enabled"),
        signed_in=ini_has_value(ini_text, section, "Username") and token,
    )


def duckstation_status(ini_text: str) -> RaStatus:
    """DuckStation: ``[Cheevos] Enabled``, ``Username`` and ``Token`` (achievements.cpp ``has_saved_credentials``)."""
    section = "Cheevos"
    return RaStatus(
        enabled=ini_flag(ini_text, section, "Enabled"),
        signed_in=ini_has_value(ini_text, section, "Username") and ini_has_value(ini_text, section, "Token"),
    )


def dolphin_status(ini_text: str) -> RaStatus:
    """Dolphin: ``RetroAchievements.ini [Achievements] Enabled``, ``Username`` and ``ApiToken``."""
    section = "Achievements"
    return RaStatus(
        enabled=ini_flag(ini_text, section, "Enabled"),
        signed_in=ini_has_value(ini_text, section, "Username") and ini_has_value(ini_text, section, "ApiToken"),
    )


def ppsspp_status(ini_text: str, *, token_file_nonempty: bool) -> RaStatus:
    """PPSSPP: ``[Achievements] AchievementsEnable`` and ``AchievementsUserName``, plus a non-empty token file."""
    section = "Achievements"
    return RaStatus(
        enabled=ini_flag(ini_text, section, "AchievementsEnable"),
        signed_in=ini_has_value(ini_text, section, "AchievementsUserName") and token_file_nonempty,
    )


def retroarch_status(cfg_text: str) -> RaStatus:
    """RetroArch: ``cheevos_enable``; signed in = ``cheevos_username`` plus a token or a password."""
    token = ini_has_value(cfg_text, None, "cheevos_token") or ini_has_value(cfg_text, None, "cheevos_password")
    return RaStatus(
        enabled=ini_flag(cfg_text, None, "cheevos_enable"),
        signed_in=ini_has_value(cfg_text, None, "cheevos_username") and token,
    )


def pcsx2_login_failed(log_text: str) -> bool:
    """Whether a PCSX2 ``emulog.txt`` records a failed RetroAchievements login."""
    return _PCSX2_LOGIN_FAILED in log_text.lower()


def ra_warning(display_name: str, status: RaStatus) -> str | None:
    """The one-line notice for a status that will not earn achievements, or ``None`` when it will."""
    if not status.enabled:
        return f"RetroAchievements isn't working in {display_name}: achievements are turned off."
    if not status.signed_in:
        return f"RetroAchievements isn't working in {display_name}: not signed in."
    return None


def login_failed_warning(display_name: str) -> str:
    """The notice for a session whose RetroAchievements login failed."""
    return f"RetroAchievements didn't work in {display_name} last session: login failed."
