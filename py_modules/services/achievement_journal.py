"""AchievementJournalService — the user's RetroAchievements goals, notes and unlock timeline.

Owns every callable behind the achievements tab's Goals and Notes views and the QAM's
goals list and unlock timeline: reading and writing the ``RaGameJournal`` aggregate,
ticking goals off from unlocks seen in RomM's data or RetroAchievements' Web API, and
the RetroAchievements Web API settings (username plus a key the user stores in The
Collector's settings for this purpose).

Goals and notes are local and work without the Web API. The timeline, cross-game goal
refresh and guide links need the Web API key; without one those answers say so in a
``no_web_api_key`` failure instead of guessing. The key itself never passes through
here: the adapter reads it from settings, and this service only tests it for presence,
writes a new one through the settings persister, and reports it masked.

An emulator's own RetroAchievements login is out of scope by construction: nothing
here holds a ``RetroAchievementsConfigReader``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from domain.achievement_highlights import (
    MAX_BRIDGE_ITEMS,
    LibraryRom,
    closest_to_complete,
    library_by_ra_game,
)
from domain.iso_time import epoch_to_iso
from domain.platform_names import decode_platform_names
from domain.ra_game_journal import AchievementGoal, RaGameJournal
from domain.ra_web import (
    TIMELINE_RANGES_DAYS,
    GameUnlock,
    achievement_page_url,
    game_page_url,
    normalize_ra_date,
    parse_game_progress,
    parse_timeline,
    public_badge_url,
    web_api_failure,
)
from domain.rom_achievement_progress import SNAPSHOT_FETCHED_AT_KEY
from lib.errors import RaWebApiError, classify_error

if TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Callable

    from domain.ra_web import TimelineEntry
    from services.protocols import (
        Clock,
        DebugLogger,
        RetroAchievementsWebApi,
        SettingsPersister,
        UnitOfWorkFactory,
    )

USERNAME_SETTING: Final = "ra_web_username"
API_KEY_SETTING: Final = "ra_web_api_key"
MASK_PLACEHOLDER: Final = "••••"

TIMELINE_CACHE_SECONDS: Final = 10 * 60
GUIDE_CACHE_SECONDS: Final = 24 * 3600
# Goal refresh asks RetroAchievements once per game; capping the games per refresh
# keeps one press from turning into a burst of requests.
MAX_REFRESH_GAMES: Final = 10
MAX_UNLOCKS_PER_CALL: Final = 500
# The timeline windows the bridge's recent-unlocks read walks, shortest first; the
# longer one is read only when the shorter held fewer library unlocks than asked for.
RECENT_UNLOCK_WINDOWS_DAYS: Final[tuple[int, ...]] = (30, 365)
# kv_config key of the offline platform_slug -> display name cache the library sync
# refreshes every run; also read by console_shelf, library.reporter and game_detail.
_PLATFORM_NAMES_KEY: Final = "platform_names"

_USERNAME_RE: Final = re.compile(r"^[A-Za-z0-9_.-]{2,40}$")
_API_KEY_RE: Final = re.compile(r"^[A-Za-z0-9]{16,64}$")

_NO_KEY: Final = {
    "success": False,
    "reason": "no_web_api_key",
    "message": "Add a RetroAchievements Web API key in Settings to use this.",
}


@dataclass(frozen=True)
class AchievementJournalServiceConfig:
    """Frozen wiring bundle handed to ``AchievementJournalService.__init__``.

    Carries the Unit-of-Work factory (the ``ra_game_journals`` aggregate and the
    ``roms`` reads that resolve a ROM to its RetroAchievements game), the
    RetroAchievements Web API adapter, the live settings dict and its persister (for
    the Web API username and key), and the loop, logger, clock and debug logger.
    """

    uow_factory: UnitOfWorkFactory
    ra_web: RetroAchievementsWebApi
    settings: dict[str, Any]
    settings_persister: SettingsPersister
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    clock: Clock
    log_debug: DebugLogger


@dataclass(frozen=True)
class _RomGame:
    ra_game_id: int
    game_title: str


def _failure(reason: str, message: str) -> dict[str, Any]:
    return {"success": False, "reason": reason, "message": message}


def _as_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _bridge_limit(value: object) -> int | None:
    """A bridge list length: an int from 1 to ``MAX_BRIDGE_ITEMS``, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BRIDGE_ITEMS:
        return None
    return value


def _bad_limit() -> dict[str, Any]:
    return _failure("invalid_argument", f"limit must be an integer from 1 to {MAX_BRIDGE_ITEMS}")


def _as_points(value: object) -> int:
    """Points as an int; anything that is not a non-negative integer becomes -1, which ``pinned`` refuses."""
    if isinstance(value, bool) or not isinstance(value, int):
        return -1
    return value


class AchievementJournalService:
    """Goals, notes, the unlock timeline and the RetroAchievements Web API settings."""

    def __init__(self, *, config: AchievementJournalServiceConfig) -> None:
        self._uow_factory = config.uow_factory
        self._ra_web = config.ra_web
        self._settings = config.settings
        self._settings_persister = config.settings_persister
        self._loop = config.loop
        self._logger = config.logger
        self._clock = config.clock
        self._log_debug = config.log_debug
        self._timeline_cache: dict[int, tuple[float, list[TimelineEntry]]] = {}
        self._guide_cache: dict[int, tuple[float, str | None]] = {}

    # ── Web API settings ─────────────────────────────────────────────────

    def web_api_configured(self) -> bool:
        """Whether both a username and a key are stored (the key is only tested for presence)."""
        return bool(self._username()) and bool(self._settings.get(API_KEY_SETTING))

    def _username(self) -> str:
        value = self._settings.get(USERNAME_SETTING, "")
        return value.strip() if isinstance(value, str) else ""

    def save_web_api(self, username: object, api_key: object) -> dict[str, Any]:
        """Persist the Web API username and key.

        ``api_key`` equal to the mask placeholder keeps the stored key (the settings
        page never holds the real one). A malformed username or key is refused with
        the canonical failure shape and nothing is written.
        """
        if not isinstance(username, str) or not _USERNAME_RE.match(username.strip()):
            return _failure("invalid_username", "Enter your RetroAchievements username.")
        keep_key = api_key == MASK_PLACEHOLDER
        if not keep_key and (not isinstance(api_key, str) or not _API_KEY_RE.match(api_key.strip())):
            return _failure("invalid_api_key", "Enter the Web API key from your RetroAchievements settings page.")
        if keep_key and not self._settings.get(API_KEY_SETTING):
            return _failure("invalid_api_key", "Enter the Web API key from your RetroAchievements settings page.")
        self._settings[USERNAME_SETTING] = username.strip()
        if not keep_key and isinstance(api_key, str):
            self._settings[API_KEY_SETTING] = api_key.strip()
        self._settings_persister.save_settings()
        self._forget_web_answers()
        self._log_debug("achievement journal: RetroAchievements Web API settings saved")
        return {"success": True}

    def clear_web_api(self) -> dict[str, Any]:
        """Forget the stored Web API username and key."""
        self._settings[USERNAME_SETTING] = ""
        self._settings[API_KEY_SETTING] = ""
        self._settings_persister.save_settings()
        self._forget_web_answers()
        return {"success": True}

    async def verify_web_api(self, username: object, api_key: object) -> dict[str, Any]:
        """Check a username and key against RetroAchievements without saving them.

        The mask placeholder (or an empty key) means the stored key; an empty username
        the stored username.
        """
        name = username.strip() if isinstance(username, str) and username.strip() else self._username()
        if not _USERNAME_RE.match(name):
            return _failure("invalid_username", "Enter your RetroAchievements username.")
        key = api_key.strip() if isinstance(api_key, str) else ""
        if not key or key == MASK_PLACEHOLDER:
            stored = self._settings.get(API_KEY_SETTING, "")
            key = stored if isinstance(stored, str) else ""
        if not _API_KEY_RE.match(key):
            return _failure("invalid_api_key", "Enter the Web API key from your RetroAchievements settings page.")
        try:
            await self._loop.run_in_executor(None, self._ra_web.verify_credentials, name, key)
        except RaWebApiError as e:
            reason, message = web_api_failure(e.status_code)
            return _failure(reason, message)
        except Exception as e:
            self._logger.warning(f"RetroAchievements Web API check failed: {type(e).__name__}")
            reason, message = classify_error(e)
            return _failure(reason, message)
        return {"success": True, "message": "RetroAchievements accepted the key"}

    def _forget_web_answers(self) -> None:
        self._timeline_cache.clear()
        self._guide_cache.clear()

    # ── Journal reads and writes ─────────────────────────────────────────

    def _read_rom_game(self, rom_id: object) -> _RomGame | dict[str, Any]:
        rid = _as_positive_int(rom_id)
        if rid is None:
            return _failure("invalid_rom", f"Invalid ROM id: {rom_id!r}")
        with self._uow_factory() as uow:
            rom = uow.roms.get(rid)
        if rom is None:
            return _failure("not_found", "This game is not in The Collector's library")
        if not rom.ra_id:
            return _failure("no_ra_id", "This game has no RetroAchievements set")
        return _RomGame(ra_game_id=rom.ra_id, game_title=rom.name)

    def _now_iso(self) -> str:
        return epoch_to_iso(self._clock.time())

    def get_journal(self, rom_id: object) -> dict[str, Any]:
        """Return the journal of the ROM's game: notes and goals, empty when there is none yet."""
        game = self._read_rom_game(rom_id)
        if isinstance(game, dict):
            return game
        with self._uow_factory() as uow:
            journal = uow.ra_game_journals.get(game.ra_game_id)
        if journal is None:
            journal = RaGameJournal.opened(ra_game_id=game.ra_game_id, game_title=game.game_title)
        return {
            "success": True,
            **journal.to_wire(),
            "game_url": game_page_url(game.ra_game_id),
            "web_api_configured": self.web_api_configured(),
        }

    def _write_journal(self, game: _RomGame, change: Callable[[RaGameJournal], object]) -> RaGameJournal:
        """Apply *change* to the game's journal in one write UoW; an emptied journal is deleted."""
        with self._uow_factory() as uow:
            journal = uow.ra_game_journals.get(game.ra_game_id) or RaGameJournal.opened(
                ra_game_id=game.ra_game_id, game_title=game.game_title
            )
            journal.retitle(game.game_title)
            change(journal)
            if journal.is_empty:
                uow.ra_game_journals.delete(game.ra_game_id)
            else:
                uow.ra_game_journals.save(journal)
        return journal

    def save_notes(self, rom_id: object, text: object) -> dict[str, Any]:
        """Replace the game's notes; empty text clears them. Over-long notes are refused whole."""
        if not isinstance(text, str):
            return _failure("invalid_notes", "Notes must be text")
        game = self._read_rom_game(rom_id)
        if isinstance(game, dict):
            return game
        at = self._now_iso()
        try:
            journal = self._write_journal(game, lambda j: j.write_notes(text, at=at))
        except ValueError as e:
            return _failure("notes_too_long", str(e))
        return {"success": True, **journal.to_wire()}

    def pin_goal(self, rom_id: object, achievement: object) -> dict[str, Any]:
        """Pin one achievement of the ROM's game as a goal.

        *achievement* is ``{achievement_id, title, description, points}`` from the list
        the tab shows; it is validated here, as everything from the frontend wire is.
        Pinning an achievement twice is not an error.
        """
        if not isinstance(achievement, dict):
            return _failure("invalid_achievement", "Achievement details are missing")
        game = self._read_rom_game(rom_id)
        if isinstance(game, dict):
            return game
        title = achievement.get("title")
        description = achievement.get("description")
        try:
            goal = AchievementGoal.pinned(
                achievement_id=_as_positive_int(achievement.get("achievement_id")) or 0,
                title=title if isinstance(title, str) else "",
                description=description if isinstance(description, str) else "",
                points=_as_points(achievement.get("points", 0)),
                pinned_at=self._now_iso(),
            )
            journal = self._write_journal(game, lambda j: j.pin_goal(goal))
        except ValueError as e:
            return _failure("invalid_achievement", str(e))
        return {"success": True, **journal.to_wire()}

    def unpin_goal(self, rom_id: object, achievement_id: object) -> dict[str, Any]:
        """Remove a goal from the ROM's game. Unpinning a goal that is not pinned is not an error."""
        aid = _as_positive_int(achievement_id)
        if aid is None:
            return _failure("invalid_achievement", f"Invalid achievement id: {achievement_id!r}")
        game = self._read_rom_game(rom_id)
        if isinstance(game, dict):
            return game
        journal = self._write_journal(game, lambda j: j.unpin_goal(aid))
        return {"success": True, **journal.to_wire()}

    def record_goal_unlocks(self, rom_id: object, unlocks: object) -> dict[str, Any]:
        """Tick off the ROM's goals from unlocks the tab saw in RomM's progress data.

        *unlocks* is a list of ``{achievement_id, unlocked_at, hardcore}``; entries
        without a valid id or date are skipped. Returns how many goals changed. Nothing
        is written for a game without a journal.
        """
        if not isinstance(unlocks, list):
            return _failure("invalid_unlocks", "Unlocks must be a list")
        game = self._read_rom_game(rom_id)
        if isinstance(game, dict):
            return game
        parsed: list[tuple[int, str, bool]] = []
        for raw in unlocks[:MAX_UNLOCKS_PER_CALL]:
            if not isinstance(raw, dict):
                continue
            aid = _as_positive_int(raw.get("achievement_id"))
            at = normalize_ra_date(raw.get("unlocked_at"))
            if aid is not None and at is not None:
                parsed.append((aid, at, raw.get("hardcore") is True))
        with self._uow_factory() as uow:
            journal = uow.ra_game_journals.get(game.ra_game_id)
            if journal is None:
                return {"success": True, "changed": 0}
            changed = sum(journal.record_unlock(aid, unlocked_at=at, hardcore=hc) for aid, at, hc in parsed)
            if changed:
                uow.ra_game_journals.save(journal)
        return {"success": True, "changed": changed}

    # ── Cross-game goals ─────────────────────────────────────────────────

    def get_goals_overview(self) -> dict[str, Any]:
        """Every goal across games, open ones first (oldest pin first), then done ones (newest first).

        Each goal carries its game's title, a ``rom_id`` of the game (preferring the
        version with a Steam shortcut; ``None`` once no ROM points at the game) and,
        when the game has a shortcut, the ``app_id`` that opens its page.
        """
        with self._uow_factory() as uow:
            journals = list(uow.ra_game_journals.iter_all())
            app_ids: dict[int, int] = {}
            rom_ids: dict[int, int] = {}
            for rom in uow.roms.iter_all():
                if not rom.ra_id:
                    continue
                if rom.shortcut_app_id is not None and rom.ra_id not in app_ids:
                    app_ids[rom.ra_id] = rom.shortcut_app_id
                    rom_ids[rom.ra_id] = rom.rom_id
                rom_ids.setdefault(rom.ra_id, rom.rom_id)
        goals = [
            {
                **goal.to_wire(),
                "ra_game_id": journal.ra_game_id,
                "game_title": journal.game_title,
                "app_id": app_ids.get(journal.ra_game_id),
                "rom_id": rom_ids.get(journal.ra_game_id),
                "achievement_url": achievement_page_url(goal.achievement_id),
            }
            for journal in journals
            for goal in journal.goals
        ]
        open_goals = sorted((g for g in goals if g["unlocked_at"] is None), key=lambda g: g["pinned_at"])
        done_goals = sorted((g for g in goals if g["unlocked_at"] is not None), key=lambda g: g["unlocked_at"])
        done_goals.reverse()
        return {
            "success": True,
            "goals": open_goals + done_goals,
            "open_count": len(open_goals),
            "web_api_configured": self.web_api_configured(),
        }

    def _apply_unlocks(self, unlocks_by_game: dict[int, list[GameUnlock]]) -> int:
        changed_total = 0
        with self._uow_factory() as uow:
            for game_id, unlocks in unlocks_by_game.items():
                journal = uow.ra_game_journals.get(game_id)
                if journal is None:
                    continue
                changed = sum(
                    journal.record_unlock(u.achievement_id, unlocked_at=u.unlocked_at, hardcore=u.hardcore)
                    for u in unlocks
                )
                if changed:
                    uow.ra_game_journals.save(journal)
                    changed_total += changed
        return changed_total

    def _open_goal_games(self) -> list[int]:
        with self._uow_factory() as uow:
            return [j.ra_game_id for j in uow.ra_game_journals.iter_all() if j.open_goal_ids()]

    async def refresh_goals(self) -> dict[str, Any]:
        """Ask RetroAchievements which open goals are unlocked now, for up to ten games.

        Returns the goals overview plus ``refreshed`` / ``failed`` game counts. A refused
        key fails the whole refresh; other per-game failures are counted and skipped.
        """
        if not self.web_api_configured():
            return dict(_NO_KEY)
        username = self._username()
        game_ids = (await self._loop.run_in_executor(None, self._open_goal_games))[:MAX_REFRESH_GAMES]
        unlocks_by_game: dict[int, list[GameUnlock]] = {}
        failed = 0
        for game_id in game_ids:
            try:
                payload = await self._loop.run_in_executor(
                    None, self._ra_web.get_game_info_and_user_progress, username, game_id
                )
            except RaWebApiError as e:
                reason, message = web_api_failure(e.status_code)
                if reason in ("auth_failed", "not_found"):
                    return _failure(reason, message)
                failed += 1
                continue
            progress = parse_game_progress(payload)
            self._guide_cache[game_id] = (self._clock.time(), progress.guide_url)
            unlocks_by_game[game_id] = list(progress.unlocks)
        changed = await self._loop.run_in_executor(None, self._apply_unlocks, unlocks_by_game)
        self._log_debug(f"achievement journal: goal refresh over {len(game_ids)} games, {changed} goals ticked off")
        overview = await self._loop.run_in_executor(None, self.get_goals_overview)
        return {**overview, "refreshed": len(game_ids) - failed, "failed": failed, "changed": changed}

    # ── Unlock timeline ──────────────────────────────────────────────────

    async def _timeline_entries(self, span: int, force: bool) -> tuple[list[TimelineEntry], float] | dict[str, Any]:
        """The unlocks of the last *span* days and when they were read, or the failure shape.

        Served from a ten-minute cache unless *force*. Unlocks of pinned goals are
        ticked off on the way through.
        """
        if not self.web_api_configured():
            return dict(_NO_KEY)
        now = self._clock.time()
        cached = self._timeline_cache.get(span)
        if cached is not None and not force and now - cached[0] < TIMELINE_CACHE_SECONDS:
            return cached[1], cached[0]
        try:
            payload = await self._loop.run_in_executor(
                None,
                self._ra_web.get_achievements_earned_between,
                self._username(),
                int(now) - span * 86400,
                int(now),
            )
        except RaWebApiError as e:
            reason, message = web_api_failure(e.status_code)
            return _failure(reason, message)
        entries = parse_timeline(payload)
        self._timeline_cache[span] = (now, entries)
        await self._tick_goals_from_timeline(entries)
        return entries, now

    async def get_unlock_timeline(self, days: object, force: object = False) -> dict[str, Any]:
        """The user's unlocks over the last *days* (30, 90 or 365), newest first.

        Served from a ten-minute cache unless *force*. Unlocks of pinned goals are
        ticked off on the way through.
        """
        if isinstance(days, bool) or not isinstance(days, int) or days not in TIMELINE_RANGES_DAYS:
            return _failure("invalid_range", f"Timeline range must be one of {list(TIMELINE_RANGES_DAYS)} days")
        read = await self._timeline_entries(days, force is True)
        if isinstance(read, dict):
            return read
        entries, fetched_at = read
        return {
            "success": True,
            "days": days,
            "entries": [entry.to_wire() for entry in entries],
            "fetched_at": epoch_to_iso(fetched_at),
        }

    async def _tick_goals_from_timeline(self, entries: list[TimelineEntry]) -> None:
        unlocks_by_game: dict[int, list[GameUnlock]] = {}
        for entry in entries:
            unlocks_by_game.setdefault(entry.game_id, []).append(
                GameUnlock(achievement_id=entry.achievement_id, unlocked_at=entry.unlocked_at, hardcore=entry.hardcore)
            )
        try:
            await self._loop.run_in_executor(None, self._apply_unlocks, unlocks_by_game)
        except Exception as e:
            self._logger.warning(f"Failed to tick goals off from the unlock timeline: {e}")

    # ── Links ────────────────────────────────────────────────────────────

    async def get_game_links(self, rom_id: object) -> dict[str, Any]:
        """The RetroAchievements game page and, with the Web API, the game's guide link.

        The guide is whatever RetroAchievements lists for the game, opened only when it
        is on RetroAchievements' own sites; a failed lookup just leaves it out.
        """
        game = await self._loop.run_in_executor(None, self._read_rom_game, rom_id)
        if isinstance(game, dict):
            return game
        result: dict[str, Any] = {
            "success": True,
            "game_url": game_page_url(game.ra_game_id),
            "guide_url": None,
            "web_api_configured": self.web_api_configured(),
        }
        if not result["web_api_configured"]:
            return result
        cached = self._guide_cache.get(game.ra_game_id)
        if cached is not None and self._clock.time() - cached[0] < GUIDE_CACHE_SECONDS:
            result["guide_url"] = cached[1]
            return result
        try:
            payload = await self._loop.run_in_executor(
                None, self._ra_web.get_game_info_and_user_progress, self._username(), game.ra_game_id
            )
        except RaWebApiError as e:
            self._log_debug(f"achievement journal: guide lookup for game {game.ra_game_id} failed ({e.status_code})")
            return result
        progress = parse_game_progress(payload)
        self._guide_cache[game.ra_game_id] = (self._clock.time(), progress.guide_url)
        result["guide_url"] = progress.guide_url
        if progress.unlocks:
            await self._loop.run_in_executor(None, self._apply_unlocks, {game.ra_game_id: list(progress.unlocks)})
        return result

    # ── Achievements bridge (window.__eternalCollectorAchievements) ──────

    def _read_library(self) -> tuple[dict[int, LibraryRom], dict[str, str]]:
        """Every ROM with a RetroAchievements set, one per RA game, and the platform display names."""
        with self._uow_factory() as uow:
            roms = [
                LibraryRom(
                    rom_id=rom.rom_id,
                    app_id=rom.shortcut_app_id,
                    name=rom.name,
                    platform_slug=rom.platform_slug,
                    ra_game_id=rom.ra_id,
                )
                for rom in uow.roms.iter_all()
                if rom.ra_id
            ]
            names = decode_platform_names(uow.kv_config.get(_PLATFORM_NAMES_KEY))
        return library_by_ra_game(roms), names

    async def get_recent_unlocks(self, limit: object) -> dict[str, Any]:
        """The user's newest unlocks in games of The Collector's library, newest first, at most *limit*.

        ``{success, items: [{rom_id, app_id, game, platform, title, description,
        badge_url, unlocked_at, hardcore}]}``. Read from the unlock timeline (Web API),
        so ``no_web_api_key`` without a key. An unlock in a game the library does not
        hold is left out: it has no ROM to name. ``badge_url`` is ``None`` unless it is a
        plain https URL on RetroAchievements' media host.
        """
        size = _bridge_limit(limit)
        if size is None:
            return _bad_limit()
        if not self.web_api_configured():
            return dict(_NO_KEY)
        library, names = await self._loop.run_in_executor(None, self._read_library)
        items: list[dict[str, Any]] = []
        for days in RECENT_UNLOCK_WINDOWS_DAYS:
            read = await self._timeline_entries(days, force=False)
            if isinstance(read, dict):
                return read
            items = []
            for entry in read[0]:
                rom = library.get(entry.game_id)
                if rom is None:
                    continue
                items.append(
                    {
                        "rom_id": rom.rom_id,
                        "app_id": rom.app_id,
                        "game": rom.name,
                        "platform": names.get(rom.platform_slug) or entry.console_name or rom.platform_slug,
                        "title": entry.title,
                        "description": entry.description,
                        "badge_url": public_badge_url(entry.badge_url),
                        "unlocked_at": entry.unlocked_at,
                        "hardcore": entry.hardcore,
                    }
                )
                if len(items) == size:
                    break
            if len(items) == size:
                break
        return {"success": True, "items": items}

    def get_closest_to_complete(self, limit: object) -> dict[str, Any]:
        """The started, unfinished games closest to 100%, from the achievement snapshot, at most *limit*.

        ``{success, fetched_at, items: [{rom_id, app_id, game, platform, earned, total,
        percent}]}``, highest percent first, games at 0% and 100% left out. The snapshot
        is RomM's ``ra_progression`` (no Web API key involved); before its first refresh
        the answer is the ``no_snapshot`` failure. Synchronous: one short read UoW.
        """
        size = _bridge_limit(limit)
        if size is None:
            return _bad_limit()
        library, names = self._read_library()
        with self._uow_factory() as uow:
            fetched_at = uow.kv_config.get(SNAPSHOT_FETCHED_AT_KEY)
            progress = dict(uow.rom_achievement_progress.iter_all())
        if not fetched_at:
            return _failure("no_snapshot", "RetroAchievements progress has not been read from RomM yet")
        return {
            "success": True,
            "fetched_at": fetched_at,
            "items": [
                {
                    "rom_id": c.rom.rom_id,
                    "app_id": c.rom.app_id,
                    "game": c.rom.name,
                    "platform": names.get(c.rom.platform_slug) or c.rom.platform_slug,
                    "earned": c.earned,
                    "total": c.total,
                    "percent": c.percent,
                }
                for c in closest_to_complete(library, progress, size)
            ],
        }
