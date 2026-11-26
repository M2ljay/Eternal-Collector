"""AchievementsService — RetroAchievements data surfacing for the QAM.

Owns the in-memory achievements cache and every read the game-detail
panel runs against it: per-ROM achievement lists, the user-progress
snapshot, the post-session refresh that keeps cached completion
counts in step with the RomM server after a play session, and the
persisted achievement snapshot (``rom_achievement_progress``) that the
console pages read offline. The snapshot is replaced from every
``/api/users/me`` answer this service reads, so it costs no extra request. HTTP traffic
flows through ``RommAchievementsApi``; cache shape, invalidation
policy, and the pure progress extraction live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.achievements import extract_achievements_from_rom, extract_game_progress
from domain.iso_time import epoch_to_iso
from domain.rom_achievement_progress import SNAPSHOT_FETCHED_AT_KEY, build_snapshot
from lib.errors import classify_error

if TYPE_CHECKING:
    import asyncio
    import logging

    from services.protocols import Clock, DebugLogger, RommAchievementsApi, UnitOfWorkFactory


@dataclass(frozen=True)
class AchievementsServiceConfig:
    """Frozen wiring bundle handed to ``AchievementsService.__init__``.

    Holds the Protocol-typed RomM adapter, the SQLite Unit-of-Work factory
    (the read seam over the ``roms`` aggregate for each ROM's ``ra_id``),
    runtime infrastructure, and the clock/debug-logger seams
    AchievementsService needs at construction time.
    """

    romm_api: RommAchievementsApi
    uow_factory: UnitOfWorkFactory
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    clock: Clock
    log_debug: DebugLogger


class AchievementsService:
    """RetroAchievements data fetching via RomM server."""

    ACHIEVEMENTS_CACHE_TTL = 24 * 3600  # 24h for achievement definitions
    PROGRESS_CACHE_TTL = 3600  # 1h for user progress
    RA_USERNAME_CACHE_TTL = 3600  # 1h for RA username detection

    def __init__(self, *, config: AchievementsServiceConfig) -> None:
        self._romm_api = config.romm_api
        self._uow_factory = config.uow_factory
        self._loop = config.loop
        self._logger = config.logger
        self._clock = config.clock
        self._log_debug = config.log_debug

        self._achievements_cache: dict[str, Any] = {}

    def _read_ra_id(self, rom_id: int) -> int | None:
        """Return the ROM's RetroAchievements id from ``uow.roms``, or ``None``.

        Short synchronous read UoW — a single PK lookup, opened outside the
        executor RomM fetch so no network I/O runs inside the transaction.
        """
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
        return rom.ra_id if rom else None

    def get_ra_username(self):
        """Get RA username from RomM user profile (cached).

        Returns the cached ra_username if fresh, empty string otherwise.
        The cache is populated by _fetch_ra_username() which calls /api/users/me.
        """
        cached = self._achievements_cache.get("_ra_user")
        if cached:
            age = self._clock.time() - cached.get("cached_at", 0)
            if age < self.RA_USERNAME_CACHE_TTL:
                return cached.get("username", "")
        return ""

    async def _fetch_ra_username(self):
        """Fetch RA username from RomM user profile and cache it."""
        try:
            user_data = await self._loop.run_in_executor(None, self._romm_api.get_current_user)
            ra_username = (user_data.get("ra_username") or "").strip()
            self._achievements_cache["_ra_user"] = {
                "username": ra_username,
                "cached_at": self._clock.time(),
            }
            return ra_username
        except Exception as e:
            self._logger.warning(f"Failed to fetch RA username from RomM: {e}")
            # Return stale cache if available
            cached = self._achievements_cache.get("_ra_user")
            if cached:
                return cached.get("username", "")
            return ""

    def _get_achievements_cache_entry(self, rom_id_str):
        """Get cached achievement data for a ROM if not expired."""
        entry = self._achievements_cache.get(rom_id_str)
        if not entry:
            return None
        age = self._clock.time() - entry.get("cached_at", 0)
        if age > self.ACHIEVEMENTS_CACHE_TTL:
            return None
        return entry

    def get_progress_cache_entry(self, rom_id_str):
        """Get cached user progress for a ROM if not expired."""
        entry = self._achievements_cache.get(rom_id_str, {}).get("user_progress")
        if not entry:
            return None
        age = self._clock.time() - entry.get("cached_at", 0)
        if age > self.PROGRESS_CACHE_TTL:
            return None
        return entry

    async def get_achievements(self, rom_id):
        """Fetch achievement list for a ROM from RomM. Returns cached if fresh."""
        rom_id = int(rom_id)
        rom_id_str = str(rom_id)

        # Check cache
        cached = self._get_achievements_cache_entry(rom_id_str)
        if cached and cached.get("achievements"):
            self._log_debug(f"Achievements cache hit for rom_id={rom_id}")
            return {"success": True, "achievements": cached["achievements"], "total": len(cached["achievements"])}

        # Look up ra_id from the ``roms`` aggregate (short read UoW)
        ra_id = self._read_ra_id(rom_id)
        if not ra_id:
            return {"success": True, "achievements": [], "total": 0, "no_ra_id": True}

        # Fetch ROM detail from RomM (includes ra_metadata)
        try:
            rom_data = await self._loop.run_in_executor(None, self._romm_api.get_rom, rom_id)
            achievements = extract_achievements_from_rom(rom_data)

            # Cache it
            if rom_id_str not in self._achievements_cache:
                self._achievements_cache[rom_id_str] = {}
            self._achievements_cache[rom_id_str]["achievements"] = achievements
            self._achievements_cache[rom_id_str]["cached_at"] = self._clock.time()
            self._achievements_cache[rom_id_str]["ra_id"] = ra_id

            return {"success": True, "achievements": achievements, "total": len(achievements)}
        except Exception as e:
            self._logger.warning(f"Failed to fetch achievements for rom_id={rom_id}: {e}")
            # Return stale cache if available
            stale = self._achievements_cache.get(rom_id_str, {})
            if stale.get("achievements"):
                return {
                    "success": True,
                    "achievements": stale["achievements"],
                    "total": len(stale["achievements"]),
                    "stale": True,
                }
            reason, _message = classify_error(e)
            return {
                "success": False,
                "reason": reason,
                "message": str(e),
                "achievements": [],
                "total": 0,
            }

    def _progress_data_response(self, progress_data):
        """Build a success response from progress_data, excluding cached_at."""
        return {"success": True, **{k: v for k, v in progress_data.items() if k != "cached_at"}}

    async def get_achievement_progress(self, rom_id):
        """Fetch user's achievement progress for a ROM from RomM.

        Returns earned/total counts and per-achievement earned status.
        Requires RA username configured in the RomM user profile.
        """
        rom_id = int(rom_id)
        rom_id_str = str(rom_id)

        ra_username = self.get_ra_username() or await self._fetch_ra_username()
        if not ra_username:
            return {
                "success": False,
                "reason": "no_ra_username",
                "message": "No RA username configured in RomM",
                "earned": 0,
                "total": 0,
            }

        cached_progress = self.get_progress_cache_entry(rom_id_str)
        if cached_progress:
            self._log_debug(f"Achievement progress cache hit for rom_id={rom_id}")
            return {"success": True, **cached_progress}

        ra_id = self._read_ra_id(rom_id)
        if not ra_id:
            return {"success": True, "earned": 0, "total": 0, "earned_achievements": [], "no_ra_id": True}

        total = (await self.get_achievements(rom_id)).get("total", 0)

        try:
            user_data = await self._loop.run_in_executor(None, self._romm_api.get_current_user)
            fetched_username = (user_data.get("ra_username") or "").strip()
            if fetched_username:
                self._achievements_cache["_ra_user"] = {"username": fetched_username, "cached_at": self._clock.time()}

            progress_data = extract_game_progress(user_data.get("ra_progression"), ra_id, total, self._clock.time())
            await self._store_snapshot_quietly(user_data)

            if rom_id_str not in self._achievements_cache:
                self._achievements_cache[rom_id_str] = {}
            self._achievements_cache[rom_id_str]["user_progress"] = progress_data

            return self._progress_data_response(progress_data)
        except Exception as e:
            self._logger.warning(f"Failed to fetch achievement progress for rom_id={rom_id}: {e}")
            stale_progress = self._achievements_cache.get(rom_id_str, {}).get("user_progress")
            if stale_progress:
                return {**self._progress_data_response(stale_progress), "stale": True}
            reason, _message = classify_error(e)
            return {
                "success": False,
                "reason": reason,
                "message": str(e),
                "earned": 0,
                "total": 0,
                "earned_achievements": [],
            }

    async def sync_achievements_after_session(self, rom_id):
        """Post-session: force-refresh achievement progress from RomM.

        Called after game session ends to pick up any achievements earned during gameplay.
        Invalidates the progress cache and fetches fresh data.
        """
        rom_id = int(rom_id)
        rom_id_str = str(rom_id)

        # Invalidate progress cache to force fresh fetch
        if rom_id_str in self._achievements_cache and "user_progress" in self._achievements_cache[rom_id_str]:
            del self._achievements_cache[rom_id_str]["user_progress"]

        # Fetch fresh progress
        result = await self.get_achievement_progress(rom_id)
        if result.get("success"):
            self._logger.info(
                f"Post-session achievement sync for rom_id={rom_id}: "
                f"{result.get('earned', 0)}/{result.get('total', 0)} earned"
            )
        return result

    def do_store_progress_snapshot(self, user_data: dict[str, Any]) -> str:
        """Replace the persisted achievement snapshot from one ``/api/users/me`` answer.

        Synchronous: one write UoW reading every ROM's ``ra_id`` and replacing the whole
        ``rom_achievement_progress`` table, plus the ``fetched_at`` stamp in ``kv_config``.
        Returns that stamp. An answer without ``ra_progression`` (no RA username in the
        RomM profile) empties the snapshot: there is no progress to show.
        """
        fetched_at = epoch_to_iso(self._clock.time())
        with self._uow_factory() as uow:
            rom_ra_ids = [(rom.rom_id, rom.ra_id) for rom in uow.roms.iter_all() if rom.ra_id]
            snapshot = build_snapshot(user_data.get("ra_progression"), rom_ra_ids, fetched_at)
            uow.rom_achievement_progress.replace_all(snapshot)
            uow.kv_config.set(SNAPSHOT_FETCHED_AT_KEY, fetched_at)
        self._log_debug(f"Achievement snapshot: {len(snapshot)} of {len(rom_ra_ids)} ROMs with a set have progress")
        return fetched_at

    async def _store_snapshot_quietly(self, user_data: dict[str, Any]) -> None:
        """Store the snapshot from an answer read for another purpose; a failure only logs."""
        try:
            await self._loop.run_in_executor(None, self.do_store_progress_snapshot, user_data)
        except Exception as e:
            self._logger.warning(f"Failed to store the achievement snapshot: {e}")

    async def refresh_progress_snapshot(self) -> dict[str, Any]:
        """Read the user's progress from RomM once and replace the persisted snapshot.

        Returns ``{success: True, refreshed_at}``, or the canonical failure shape when
        RomM cannot be read; the previous snapshot is kept on failure. RomM only updates
        this data on its own RetroAchievements sync, so a refresh can be no fresher than
        that.
        """
        try:
            user_data = await self._loop.run_in_executor(None, self._romm_api.get_current_user)
        except Exception as e:
            self._logger.warning(f"Failed to refresh achievement progress from RomM: {e}")
            reason, _message = classify_error(e)
            return {"success": False, "reason": reason, "message": str(e)}
        ra_username = (user_data.get("ra_username") or "").strip()
        self._achievements_cache["_ra_user"] = {"username": ra_username, "cached_at": self._clock.time()}
        try:
            fetched_at = await self._loop.run_in_executor(None, self.do_store_progress_snapshot, user_data)
        except Exception as e:
            self._logger.warning(f"Failed to store the achievement snapshot: {e}")
            return {"success": False, "reason": "snapshot_failed", "message": str(e)}
        return {"success": True, "refreshed_at": fetched_at}
