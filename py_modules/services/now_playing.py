"""NowPlayingService — publishes the running ROM for other plugins (Discord Rich Presence).

Owns the shared "now playing" file: one record per running RomM game, written
when the frontend's session manager sees the game start and removed when it
ends. The record's shape and its privacy rule (nothing that points at the RomM
server) live in ``domain/now_playing.py``; the contract readers rely on is
``docs/architecture/now-playing-presence.md``.

Publishing never affects play: a failed write is logged and the frontend still
gets the record for its in-page copy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.now_playing import build_record, public_cover_url, record_for, with_record, without_record
from domain.platform_names import decode_platform_names

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from services.protocols import DebugLogger, NowPlayingStore, RommRomReader, UnitOfWorkFactory

# kv_config key of the offline ``platform_slug → display_name`` cache the library
# sync refreshes. Mirrors ``library.reporter._PLATFORM_NAMES_KEY``.
_PLATFORM_NAMES_KEY = "platform_names"


@dataclass(frozen=True)
class NowPlayingServiceConfig:
    """Frozen wiring bundle handed to ``NowPlayingService.__init__``.

    The Unit-of-Work factory reads the ROM's name and platform; the RomM reader
    is asked once per session for the ROM's external cover URL; the store is
    the shared file.
    """

    loop: asyncio.AbstractEventLoop
    uow_factory: UnitOfWorkFactory
    romm_api: RommRomReader
    store: NowPlayingStore
    logger: logging.Logger
    log_debug: DebugLogger


class NowPlayingService:
    """Writes and clears the records of the shared "now playing" file."""

    def __init__(self, *, config: NowPlayingServiceConfig) -> None:
        self._loop = config.loop
        self._uow_factory = config.uow_factory
        self._romm_api = config.romm_api
        self._store = config.store
        self._logger = config.logger
        self._log_debug = config.log_debug
        # Every read-modify-write of the file holds this lock. Callables are
        # dispatched in arrival order, so a clear sent after a publish waits for it.
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        """Delete the file: at startup no session of ours can be live yet.

        The frontend's reload adoption republishes the games still running.
        """
        try:
            self._store.remove()
        except OSError as e:
            self._logger.warning(f"Could not clear the now-playing file: {e}")

    async def publish(self, rom_id: int, app_id: int, started_at_ms: int) -> dict[str, Any]:
        """Record that *rom_id* is running as Steam app *app_id* since *started_at_ms*.

        Returns ``{"success": True, "record": {...}}`` — without a cover; see
        :meth:`resolve_cover` — or a ``not_found`` failure for an unknown ROM.
        """
        async with self._lock:
            rom_id, app_id = int(rom_id), int(app_id)
            found = await self._loop.run_in_executor(None, self._read_rom_io, rom_id)
            if found is None:
                return {"success": False, "reason": "not_found", "message": f"ROM {rom_id} is not in the library"}
            name, platform = found
            record = build_record(
                app_id=app_id, rom_id=rom_id, name=name, platform=platform, started_at_ms=int(started_at_ms)
            )
            await self._write(lambda doc: with_record(doc, record))
            self._log_debug(f"now playing: published romId={rom_id} appId={app_id}")
            return {"success": True, "record": record}

    async def resolve_cover(self, rom_id: int, app_id: int) -> dict[str, Any]:
        """Add the ROM's public cover URL to *app_id*'s record, when RomM has one.

        Asks RomM once (short timeout) for the ROM's ``url_cover``; only a
        public metadata-provider URL is kept. Returns ``{"success": True,
        "record": <the current record or None>}`` — ``None`` once the session
        has ended. RomM being unreachable only means no cover.
        """
        rom_id, app_id = int(rom_id), int(app_id)
        cover = None
        try:
            fetched = await self._loop.run_in_executor(None, self._romm_api.get_rom_once, rom_id)
            cover = public_cover_url(fetched.get("url_cover"))
        except Exception as e:
            self._log_debug(f"now playing: no cover for romId={rom_id}: {e}")
        async with self._lock:
            current = record_for(await self._loop.run_in_executor(None, self._store.read), app_id)
            if current is None or current.get("rom_id") != rom_id:
                return {"success": True, "record": None}
            if cover is None or current.get("cover_url") == cover:
                return {"success": True, "record": current}
            updated = {**current, "cover_url": cover}
            await self._write(lambda doc: with_record(doc, updated))
            return {"success": True, "record": updated}

    async def clear(self, app_id: int) -> dict[str, Any]:
        """Remove *app_id*'s record; the file goes when no record is left."""
        app_id = int(app_id)
        async with self._lock:
            await self._write(lambda doc: without_record(doc, app_id))
        return {"success": True}

    def _read_rom_io(self, rom_id: int) -> tuple[str, str] | None:
        """``(name, platform display name)`` of *rom_id*, or ``None`` when unknown."""
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            platform_names = decode_platform_names(uow.kv_config.get(_PLATFORM_NAMES_KEY))
        if rom is None:
            return None
        return rom.name, platform_names.get(rom.platform_slug) or rom.platform_slug

    async def _write(self, change: Callable[[object], dict[str, Any]]) -> None:
        """Apply *change* to the stored document and write it back (lock held)."""
        try:
            doc = change(await self._loop.run_in_executor(None, self._store.read))
            if doc["records"]:
                await self._loop.run_in_executor(None, self._store.write, doc)
            else:
                await self._loop.run_in_executor(None, self._store.remove)
        except OSError as e:
            self._logger.warning(f"Could not update the now-playing file: {e}")
