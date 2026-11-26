"""ConsoleShelfService — the offline read model behind The Collector's console shelf and console pages.

Answers from this device's own records only — the bound ROMs, their play time, the
cached save-sync state, the install records and the achievement snapshot — so the
Home row and a console page never wait on the network. Read-only by declaration
(``scripts/check_read_only_module.py``): a write belongs with the service that owns
the state, never here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from domain.console_shelf import (
    ShelfGame,
    achievement_badge,
    continue_game,
    newest_instant,
    order_console_games,
    rank_consoles,
)
from domain.platform_names import decode_platform_names
from domain.rom_achievement_progress import SNAPSHOT_FETCHED_AT_KEY
from domain.save_status import compute_save_sync_display

if TYPE_CHECKING:
    from domain.rom import Rom
    from domain.rom_save_sync_state import RomSaveSyncState
    from services.protocols import Clock, DebugLogger, UnitOfWork, UnitOfWorkFactory

# kv_config key of the offline ``platform_slug → display_name`` cache the library sync
# refreshes every run; also read by library.reporter and game_detail.
_PLATFORM_NAMES_KEY = "platform_names"
# Settings key of the "Show The Collector on Home" toggle; on unless switched off.
HOME_SHELF_SETTING = "collector_home_shelf"

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class ConsoleShelfServiceConfig:
    """Frozen wiring bundle handed to ``ConsoleShelfService.__init__``.

    Holds the SQLite Unit-of-Work factory (the read seam over ``roms``, ``playtime``,
    ``rom_installs``, ``rom_save_sync_states``, ``rom_achievement_progress`` and
    ``kv_config``), the live settings dict (the Home toggle and ``save_sync_enabled``),
    the clock that dates "most played", and the debug logger.
    """

    uow_factory: UnitOfWorkFactory
    settings: dict[str, Any]
    clock: Clock
    log_debug: DebugLogger


def _bound_games(uow: UnitOfWork) -> list[ShelfGame]:
    """Every bound ROM as a :class:`ShelfGame`, with its sibling group's play time folded in.

    A version switch rebinds a game to another ROM of the same sibling group, so the
    play time recorded under an unbound sibling still belongs to the game in Steam.
    """
    roms = list(uow.roms.iter_all())
    bound: dict[int, Rom] = {r.rom_id: r for r in roms if r.shortcut_app_id is not None}
    bound_by_group = {r.sibling_group_key: r.rom_id for r in bound.values() if r.sibling_group_key}
    owner_of = {
        r.rom_id: (r.rom_id if r.rom_id in bound else bound_by_group.get(r.sibling_group_key or "")) for r in roms
    }

    seconds: dict[int, int] = {}
    last: dict[int, list[str | None]] = {}
    for rom_id, playtime in uow.playtime.iter_all():
        owner = owner_of.get(rom_id)
        if owner is None:
            continue
        seconds[owner] = seconds.get(owner, 0) + max(0, int(playtime.total_seconds or 0))
        last.setdefault(owner, []).append(playtime.last_played)

    games: list[ShelfGame] = []
    for rom_id, rom in bound.items():
        games.append(
            ShelfGame(
                rom_id=rom_id,
                app_id=rom.shortcut_app_id or 0,
                name=rom.name,
                platform_slug=rom.platform_slug,
                play_seconds=seconds.get(rom_id, 0),
                last_played=newest_instant(last.get(rom_id, [])),
            )
        )
    return games


def _save_sync_display(state: RomSaveSyncState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    files = [{"filename": name, "status": "synced"} for name in state.files]
    return asdict(compute_save_sync_display(files, state.last_sync_check_at))


class ConsoleShelfService:
    """Builds the console shelf and console-page payloads from local state alone."""

    def __init__(self, *, config: ConsoleShelfServiceConfig) -> None:
        self._uow_factory = config.uow_factory
        self._settings = config.settings
        self._clock = config.clock
        self._log_debug = config.log_debug

    def home_shelf_enabled(self) -> bool:
        """Whether the Home row is switched on (it is unless the user turned it off)."""
        return bool(self._settings.get(HOME_SHELF_SETTING, True))

    def get_console_shelf(self) -> dict[str, Any]:
        """Return every console with games in Steam, most played first.

        ``{success, enabled, consoles: [{platform_slug, name, game_count, last_played,
        play_seconds}]}``. Synchronous: one short read UoW, run off the loop by the caller.
        """
        with self._uow_factory() as uow:
            games = _bound_games(uow)
            names = decode_platform_names(uow.kv_config.get(_PLATFORM_NAMES_KEY))
        entries = rank_consoles(games, names, self._clock.time())
        self._log_debug(f"Console shelf: {len(entries)} consoles from {len(games)} games")
        return {
            "success": True,
            "enabled": self.home_shelf_enabled(),
            "consoles": [
                {
                    "platform_slug": e.platform_slug,
                    "name": e.name,
                    "game_count": e.game_count,
                    "last_played": e.last_played,
                    "play_seconds": e.play_seconds,
                }
                for e in entries
            ],
        }

    def get_console_games(
        self, platform_slug: object, offset: object = 0, limit: object = DEFAULT_PAGE_SIZE
    ) -> dict[str, Any]:
        """Return one page of a console's games, "Continue" first, then by name.

        Each game carries its cached save-sync display (``None`` when nothing is
        recorded) and its achievement chip from the snapshot (``None`` when the user has
        no recorded progress; ``has_ra_set`` tells "no progress yet" from "no set").
        ``achievements_fetched_at`` is when the snapshot was last replaced, ``None``
        before the first refresh.
        """
        page = self._validate_page(platform_slug, offset, limit)
        if isinstance(page, dict):
            return page
        slug, start, size = page

        with self._uow_factory() as uow:
            games = [g for g in _bound_games(uow) if g.platform_slug == slug]
            names = decode_platform_names(uow.kv_config.get(_PLATFORM_NAMES_KEY))
            snapshot_at = uow.kv_config.get(SNAPSHOT_FETCHED_AT_KEY)
            ordered = order_console_games(games)
            window = ordered[start : start + size]
            rows = [
                (
                    game,
                    uow.roms.get(game.rom_id),
                    uow.rom_installs.get(game.rom_id) is not None,
                    uow.rom_save_sync_states.get(game.rom_id),
                    uow.rom_achievement_progress.get(game.rom_id),
                )
                for game in window
            ]

        first = continue_game(games)
        return {
            "success": True,
            "platform_slug": slug,
            "name": names.get(slug) or slug,
            "total": len(ordered),
            "offset": start,
            "continue_rom_id": first.rom_id if first else None,
            "save_sync_enabled": bool(self._settings.get("save_sync_enabled", False)),
            "achievements_fetched_at": snapshot_at or None,
            "games": [
                {
                    "rom_id": game.rom_id,
                    "app_id": game.app_id,
                    "name": game.name,
                    "last_played": game.last_played,
                    "play_seconds": game.play_seconds,
                    "installed": installed,
                    "save_sync": _save_sync_display(save_state),
                    "achievements": asdict(badge) if (badge := achievement_badge(progress)) else None,
                    "has_ra_set": bool(rom.ra_id) if rom is not None else False,
                }
                for game, rom, installed, save_state, progress in rows
            ],
        }

    @staticmethod
    def _validate_page(platform_slug: object, offset: object, limit: object) -> tuple[str, int, int] | dict[str, Any]:
        if not isinstance(platform_slug, str) or not platform_slug.strip():
            return {"success": False, "reason": "invalid_platform", "message": "A console is required"}
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return {"success": False, "reason": "invalid_page", "message": "offset must be a non-negative integer"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE_SIZE:
            return {
                "success": False,
                "reason": "invalid_page",
                "message": f"limit must be an integer from 1 to {MAX_PAGE_SIZE}",
            }
        return platform_slug.strip(), offset, limit
