"""CaseArtService — the Game case cover style: pick, fetch and keep a ROM's case art.

Owns the per-ROM case image in the SteamGridDB artwork cache (``{rom_id}_case.png``,
already letterboxed to Steam's 2:3 capsule) and its sidecar, and answers which
cover stands for a ROM (``CoverChoiceReader``) so ``ArtworkService`` publishes the
case image instead of the plain RomM cover when the setting asks for it.

The letterboxing itself happens in the frontend: Decky's Python has no image
decoder, so the service hands the raw grid to the frontend and stores the PNG it
draws back. Ranking rules live in ``domain.case_art``.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from domain.case_art import (
    CAPSULE_HEIGHT,
    CAPSULE_WIDTH,
    COVER_STYLE_CASE,
    COVER_STYLE_PLAIN,
    CaseAuthor,
    CaseGrid,
    CaseSidecar,
    case_art_filenames,
    case_grids_path,
    cover_style,
    dump_case_sidecar,
    parse_case_authors,
    parse_case_sidecar,
    png_size,
    rank_case_grids,
)
from lib.errors import SgdbApiError
from lib.list_result import ErrorCode

if TYPE_CHECKING:
    import asyncio
    import logging

    from services.protocols import (
        DebugLogger,
        PendingSyncReader,
        SgdbArtworkCache,
        SteamGridDbApi,
        UnitOfWorkFactory,
    )

AUTHORS_FILENAME = "case_art_authors.json"
_LIST_LIMIT = 30


@dataclass(frozen=True)
class CaseArtServiceConfig:
    """Frozen wiring bundle handed to ``CaseArtService.__init__``.

    ``plugin_dir`` locates ``case_art_authors.json`` (the plugin root in a
    packaged install, ``defaults/`` in a dev deploy).
    """

    sgdb_api: SteamGridDbApi
    sgdb_artwork_cache: SgdbArtworkCache
    settings: dict[str, Any]
    plugin_dir: str
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    log_debug: DebugLogger
    get_pending_sync: PendingSyncReader
    uow_factory: UnitOfWorkFactory


class CaseArtService:
    """Game case cover art from SteamGridDB, and the cover choice it implies."""

    def __init__(self, *, config: CaseArtServiceConfig) -> None:
        self._sgdb_api = config.sgdb_api
        self._cache = config.sgdb_artwork_cache
        self._settings = config.settings
        self._plugin_dir = config.plugin_dir
        self._loop = config.loop
        self._logger = config.logger
        self._log_debug = config.log_debug
        self._get_pending_sync = config.get_pending_sync
        self._uow_factory = config.uow_factory
        self._authors: dict[str, tuple[CaseAuthor, ...]] | None = None

    # ── Paths and sidecar ────────────────────────────────────────────────

    def _paths(self, rom_id: int | str) -> tuple[str, str, str]:
        art_dir = self._cache.cache_dir()
        image, sidecar, source = case_art_filenames(rom_id)
        return (os.path.join(art_dir, image), os.path.join(art_dir, sidecar), os.path.join(art_dir, source))

    def _read_sidecar(self, rom_id: int | str) -> CaseSidecar | None:
        image, sidecar, _ = self._paths(rom_id)
        if not self._cache.exists(image) or not self._cache.exists(sidecar):
            return None
        try:
            return parse_case_sidecar(self._cache.read_bytes(sidecar))
        except OSError:
            return None

    def _write_sidecar(self, rom_id: int | str, sidecar: CaseSidecar) -> None:
        _, path, _ = self._paths(rom_id)
        self._cache.write_bytes_atomic(path, dump_case_sidecar(sidecar).encode())

    # ── CoverChoiceReader (consumed by ArtworkService) ───────────────────

    def do_choose_cover_path(self, rom_id: int | str, plain_path: str) -> str:
        """Return the case image when the style is Game case and one is cached, else *plain_path*."""
        if cover_style(self._settings) != COVER_STYLE_CASE:
            return plain_path
        image, _, _ = self._paths(rom_id)
        return image if self._cache.exists(image) else plain_path

    def do_has_case_cover(self, rom_id: int | str) -> bool:
        """Return whether a case image is cached for *rom_id*, whatever the style."""
        image, _, _ = self._paths(rom_id)
        return self._cache.exists(image)

    def do_restyle_candidates(self, rom_ids: list[int]) -> list[int]:
        """ROMs with cached case art whose Steam tile last got the other cover style.

        Only ROMs that ever had case art qualify: a ROM without one shows the
        plain cover under either style, so it never needs re-applying.
        """
        style = cover_style(self._settings)
        out: list[int] = []
        for rom_id in rom_ids:
            sidecar = self._read_sidecar(rom_id)
            if sidecar is not None and sidecar.published != style:
                out.append(rom_id)
        return out

    def do_mark_published(self, rom_id: int) -> None:
        """Record the configured style as the one on *rom_id*'s Steam tile."""
        sidecar = self._read_sidecar(rom_id)
        style = cover_style(self._settings)
        if sidecar is not None and sidecar.published != style:
            self._write_sidecar(rom_id, replace(sidecar, published=style))

    # ── Lookup ───────────────────────────────────────────────────────────

    def _load_authors(self) -> dict[str, tuple[CaseAuthor, ...]]:
        if self._authors is None:
            raw: bytes | None = None
            for path in (
                os.path.join(self._plugin_dir, AUTHORS_FILENAME),
                os.path.join(self._plugin_dir, "defaults", AUTHORS_FILENAME),
            ):
                if self._cache.exists(path):
                    try:
                        raw = self._cache.read_bytes(path)
                    except OSError as e:
                        self._logger.warning(f"Case art: cannot read {AUTHORS_FILENAME}: {e}")
                    break
            self._authors = parse_case_authors(raw)
        return self._authors

    def _rom_target(self, rom_id: int) -> tuple[int | None, str] | None:
        """``(sgdb_id, platform_slug)`` from local state, or ``None`` for an unsynced ROM."""
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
        if rom is None:
            return None
        sgdb_id = rom.sgdb_id or self._get_pending_sync().get(rom_id, {}).get("sgdb_id")
        return (int(sgdb_id) if sgdb_id else None, rom.platform_slug)

    def _ranked_grids_io(self, rom_id: int) -> tuple[list[CaseGrid], str | None]:
        """Ranked grids for *rom_id*, or ``([], reason)`` when there is nothing to rank."""
        target = self._rom_target(rom_id)
        if target is None:
            return [], "not_synced"
        sgdb_id, platform_slug = target
        if sgdb_id is None:
            return [], "no_sgdb_game"
        payload = self._sgdb_api.request(case_grids_path(sgdb_id))
        return rank_case_grids(payload, platform_slug, self._load_authors()), None

    def _failure(self, e: Exception) -> dict[str, Any]:
        if isinstance(e, SgdbApiError) and e.status_code in (401, 403):
            return {"success": False, "reason": ErrorCode.AUTH_FAILED.value, "message": "SteamGridDB rejected the key"}
        return {
            "success": False,
            "reason": ErrorCode.SERVER_UNREACHABLE.value,
            "message": f"SteamGridDB request failed: {e}",
        }

    def _no_key(self) -> dict[str, Any] | None:
        if self._settings.get("steamgriddb_api_key"):
            return None
        return {"success": False, "reason": "no_api_key", "message": "No SteamGridDB API key configured"}

    # ── Callables ────────────────────────────────────────────────────────

    async def list_case_art(self, rom_id: int) -> dict[str, Any]:
        """List the grids the user may choose from, best case cover first.

        ``{success, grids: [{id, thumb, width, height, author, score, curated}],
        selected_grid_id}``; ``selected_grid_id`` is the grid the cached case
        image came from, or ``None``.
        """
        rom_id = int(rom_id)
        if (no_key := self._no_key()) is not None:
            return no_key
        try:
            grids, reason = await self._loop.run_in_executor(None, self._ranked_grids_io, rom_id)
        except Exception as e:
            self._logger.warning(f"Case art: grid list failed for rom {rom_id}: {e}")
            return self._failure(e)
        if reason is not None:
            return {"success": False, "reason": reason, "message": "No SteamGridDB game is known for this ROM"}
        sidecar = await self._loop.run_in_executor(None, self._read_sidecar, rom_id)
        return {
            "success": True,
            "grids": [
                {
                    "id": g.grid_id,
                    "thumb": g.thumb,
                    "width": g.width,
                    "height": g.height,
                    "author": g.author,
                    "score": g.score,
                    "curated": g.curated,
                }
                for g in grids[:_LIST_LIMIT]
            ],
            "selected_grid_id": sidecar.grid_id if sidecar is not None else None,
        }

    async def get_case_art_source(
        self, rom_id: int, grid_id: int | None = None, refresh: bool = False
    ) -> dict[str, Any]:
        """Decide what the frontend applies to *rom_id*'s portrait capsule.

        ``state`` in the answer:

        - ``"plain"`` — the style is Plain cover (and no grid was chosen); keep the RomM cover.
        - ``"current"`` — the cached case image is already on the Steam tile; nothing to do.
        - ``"cached"`` — the cached case image (``base64``, 600x900) should be put on the tile;
          the service records it as published when it answers.
        - ``"none"`` — SteamGridDB has no usable grid; keep the plain cover.
        - ``"fetched"`` — the raw grid (``base64``, ``width``, ``height``, ``grid_id``,
          ``manual``) for the frontend to letterbox and hand to ``save_case_art``.

        A cached image is reused unless *refresh* is set or a different *grid_id* is
        asked for. A grid the user chose earlier is kept by an automatic pass and
        re-downloaded on *refresh*.
        """
        rom_id = int(rom_id)
        chosen = int(grid_id) if grid_id is not None else None
        if chosen is None and cover_style(self._settings) == COVER_STYLE_PLAIN:
            return {"success": True, "state": "plain"}
        sidecar = await self._loop.run_in_executor(None, self._read_sidecar, rom_id)
        if sidecar is not None and not refresh and chosen in (None, sidecar.grid_id):
            return await self._answer_cached(rom_id, sidecar)
        if (no_key := self._no_key()) is not None:
            return no_key
        if chosen is None and sidecar is not None and sidecar.manual:
            chosen = sidecar.grid_id
        manual = grid_id is not None or (sidecar is not None and sidecar.manual and chosen == sidecar.grid_id)
        try:
            return await self._loop.run_in_executor(None, self._fetch_source_io, rom_id, chosen, manual)
        except Exception as e:
            self._logger.warning(f"Case art: fetch failed for rom {rom_id}: {e}")
            return self._failure(e)

    async def _answer_cached(self, rom_id: int, sidecar: CaseSidecar) -> dict[str, Any]:
        if sidecar.published == COVER_STYLE_CASE:
            return {"success": True, "state": "current", "grid_id": sidecar.grid_id}
        image, _, _ = self._paths(rom_id)
        data = await self._loop.run_in_executor(None, self._cache.read_bytes, image)
        await self._loop.run_in_executor(
            None, self._write_sidecar, rom_id, replace(sidecar, published=COVER_STYLE_CASE)
        )
        return {
            "success": True,
            "state": "cached",
            "grid_id": sidecar.grid_id,
            "base64": base64.b64encode(data).decode("ascii"),
        }

    def _fetch_source_io(self, rom_id: int, chosen: int | None, manual: bool) -> dict[str, Any]:
        grids, reason = self._ranked_grids_io(rom_id)
        if reason is not None:
            return {"success": True, "state": "none", "reason": reason}
        pick = next((g for g in grids if g.grid_id == chosen), None) if chosen is not None else None
        if pick is None and chosen is not None and manual:
            return {"success": False, "reason": ErrorCode.NOT_FOUND.value, "message": "That grid is no longer listed"}
        pick = pick or (grids[0] if grids else None)
        if pick is None:
            self._log_debug(f"Case art: no usable grid for rom {rom_id}; keeping the plain cover")
            return {"success": True, "state": "none"}
        _, _, source = self._paths(rom_id)
        failed = {"success": False, "reason": "download_failed", "message": "Could not download the grid"}
        if not self._sgdb_api.download_image(pick.url, source):
            return failed
        try:
            data = self._cache.read_bytes(source)
        except OSError:
            return failed
        self._log_debug(f"Case art: rom {rom_id} grid {pick.grid_id} by {pick.author!r} (curated={pick.curated})")
        return {
            "success": True,
            "state": "fetched",
            "grid_id": pick.grid_id,
            "width": pick.width,
            "height": pick.height,
            "manual": manual and pick.grid_id == chosen,
            "base64": base64.b64encode(data).decode("ascii"),
        }

    async def save_case_art(self, rom_id: int, grid_id: int, png_base64: str, manual: bool = False) -> dict[str, Any]:
        """Store the frontend's letterboxed case image for *rom_id*.

        The PNG must be Steam's 600x900 capsule; anything else is refused so a
        stretched or wrongly sized image never reaches the grid. Records the grid,
        whether the user chose it, and that the case style is now on the tile.
        """
        rom_id = int(rom_id)
        try:
            data = base64.b64decode(png_base64, validate=True)
        except (ValueError, TypeError):
            return {"success": False, "reason": "invalid_payload", "message": "Case image is not valid base64"}
        if png_size(data) != (CAPSULE_WIDTH, CAPSULE_HEIGHT):
            return {"success": False, "reason": "invalid_payload", "message": "Case image must be a 600x900 PNG"}
        sidecar = CaseSidecar(grid_id=int(grid_id), manual=bool(manual), published=COVER_STYLE_CASE)
        try:
            await self._loop.run_in_executor(None, self._save_io, rom_id, data, sidecar)
        except OSError as e:
            self._logger.warning(f"Case art: save failed for rom {rom_id}: {e}")
            return {"success": False, "reason": "write_failed", "message": str(e)}
        return {"success": True}

    def _save_io(self, rom_id: int, data: bytes, sidecar: CaseSidecar) -> None:
        image, _, source = self._paths(rom_id)
        self._cache.write_bytes_atomic(image, data)
        self._write_sidecar(rom_id, sidecar)
        self._cache.remove_file(source)
