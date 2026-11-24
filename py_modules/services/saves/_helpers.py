"""Logging wrappers around pure domain helpers consumed by the saves package."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from domain.iso_time import parse_iso_to_epoch
from domain.save_path import compute_local_save_target
from domain.standalone_saves import STANDALONE_EMULATOR_TAGS, standalone_target_for

if TYPE_CHECKING:
    from collections.abc import Mapping

    from domain.rom_save_sync_state import FileSyncState

_logger = logging.getLogger(__name__)


def local_save_target(server_save: dict[str, Any], rom_name: str) -> str:
    """Resolve the local filename for *server_save*, logging any sanitization."""
    result = compute_local_save_target(server_save, rom_name)
    if result.fallback_extension is not None:
        _logger.warning(
            "Sanitized server-supplied save target — invalid file_extension=%r; falling back to 'srm'",
            result.fallback_extension,
        )
    elif result.sanitized_from is not None:
        _logger.warning(
            "Sanitized server-supplied save target from %r to %r (file_extension=%r)",
            result.sanitized_from,
            result.filename,
            server_save.get("file_extension", "srm"),
        )
    return result.filename


def save_target(
    server_save: dict[str, Any],
    info: Mapping[str, Any],
    files: Mapping[str, FileSyncState] | None = None,
) -> str | None:
    """The local filename *server_save* belongs to for the ROM described by *info*, or ``None``.

    *info* is a ``RomInfoService.get_rom_save_info`` result. With a standalone
    ``save_set`` the record must carry that emulator's tag and name one of the
    set's exact files (:func:`domain.standalone_saves.standalone_target_for`;
    *files*, the ROM's per-file baselines, lets a record this device uploaded
    stay mapped by its tracked id). Without one it is the RetroArch canonical
    ``<rom_name>.<ext>`` (:func:`local_save_target`) — except that a record a
    standalone emulator wrote is never claimed, so it cannot land in the
    RetroArch save folder. ``None`` means the record is not this ROM's save
    under its current emulator and every flow leaves it alone.
    """
    save_set = info.get("save_set")
    if save_set is None:
        if server_save.get("emulator") in STANDALONE_EMULATOR_TAGS:
            return None
        return local_save_target(server_save, info["rom_name"])
    tracked = {fs.tracked_save_id: name for name, fs in (files or {}).items() if fs.tracked_save_id is not None}
    return standalone_target_for(server_save, save_set, tracked)


def newest_server_saves_by_target(
    server_saves: list[dict[str, Any]], info: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Pick the newest server save per canonical local target.

    Groups *server_saves* by the canonical on-disk filename each would download
    into (:func:`save_target` — independent of the server row's own filename for
    RetroArch, one of the save set's exact names for a standalone emulator) and
    keeps only the newest by ``updated_at`` per target, so a target's carried
    save is deterministic rather than server-list-order dependent (#1058).
    Records that map to no target are dropped. Keyed by the canonical target
    filename. Shared by the slot-switch state sync and the setup wizard's
    legacy migration.
    """
    newest: dict[str, dict[str, Any]] = {}
    for ss in server_saves:
        target = save_target(ss, info)
        if target is None:
            continue
        current = newest.get(target)
        if current is None or (parse_iso_to_epoch(ss.get("updated_at")) or 0.0) > (
            parse_iso_to_epoch(current.get("updated_at")) or 0.0
        ):
            newest[target] = ss
    return newest
