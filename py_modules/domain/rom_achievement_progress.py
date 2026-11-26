"""RomAchievementProgress — the user's RetroAchievements progress in one ROM, as RomM last reported it.

One per ROM the user has progress in (referenced by id). The whole set is a snapshot
of one ``/api/users/me`` answer, replaced wholesale, so a record is never mutated in
place: :meth:`RomAchievementProgress.observed` is the one way in. ``build_snapshot``
turns RomM's ``ra_progression`` plus the ROMs' ``ra_id`` values into that set.

Invariants enforced here:

1. ``0 <= earned_hardcore <= earned <= total`` and ``total > 0``.
2. ``fetched_at`` is the ISO-8601 instant RomM's answer was read, never empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from domain._aggregate import cosmic_aggregate

if TYPE_CHECKING:
    from collections.abc import Iterable

# kv_config key holding the ISO-8601 instant the snapshot was last replaced. Kept
# beside the rows because an answer with no progress at all leaves no row to date.
SNAPSHOT_FETCHED_AT_KEY = "achievement_snapshot_fetched_at"


@cosmic_aggregate
class RomAchievementProgress:
    """Progress counts for one ROM's achievement set at ``fetched_at``."""

    earned: int
    earned_hardcore: int
    total: int
    highest_award_kind: str | None
    fetched_at: str

    @classmethod
    def observed(
        cls,
        *,
        earned: int,
        earned_hardcore: int,
        total: int,
        highest_award_kind: str | None,
        fetched_at: str,
    ) -> RomAchievementProgress:
        """Record progress as RomM reported it; raises ``ValueError`` on an impossible shape."""
        if total <= 0:
            raise ValueError(f"achievement total must be positive, got {total}")
        if not 0 <= earned_hardcore <= earned <= total:
            raise ValueError(
                f"achievement counts out of order: hardcore={earned_hardcore} earned={earned} total={total}"
            )
        if not fetched_at:
            raise ValueError("achievement progress needs the instant it was fetched")
        return cls(
            earned=earned,
            earned_hardcore=earned_hardcore,
            total=total,
            highest_award_kind=highest_award_kind or None,
            fetched_at=fetched_at,
        )


def _as_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _progress_from_entry(entry: dict[str, Any], fetched_at: str) -> RomAchievementProgress | None:
    total = _as_count(entry.get("max_possible"))
    earned = _as_count(entry.get("num_awarded") or 0)
    hardcore = _as_count(entry.get("num_awarded_hardcore") or 0)
    if total is None or earned is None or hardcore is None:
        return None
    award = entry.get("highest_award_kind")
    try:
        return RomAchievementProgress.observed(
            earned=earned,
            earned_hardcore=hardcore,
            total=total,
            highest_award_kind=award if isinstance(award, str) else None,
            fetched_at=fetched_at,
        )
    except ValueError:
        return None


def build_snapshot(
    ra_progression: object,
    rom_ra_ids: Iterable[tuple[int, int]],
    fetched_at: str,
) -> dict[int, RomAchievementProgress]:
    """Map each ROM to its progress from RomM's ``ra_progression`` payload.

    *rom_ra_ids* is ``(rom_id, ra_id)`` for every ROM that has a set; several ROMs may
    share one ``ra_id`` (versions of one game) and each gets the same record. A ROM
    whose game is absent from the payload, and an entry whose counts are missing or
    impossible, yield no record: "no progress yet" rather than a guessed zero.
    """
    results = ra_progression.get("results") if isinstance(ra_progression, dict) else None
    by_ra_id: dict[int, RomAchievementProgress] = {}
    for entry in results if isinstance(results, list) else []:
        if not isinstance(entry, dict):
            continue
        ra_id = _as_count(entry.get("rom_ra_id"))
        if ra_id is None or ra_id in by_ra_id:
            continue
        progress = _progress_from_entry(entry, fetched_at)
        if progress is not None:
            by_ra_id[ra_id] = progress
    return {rom_id: by_ra_id[ra_id] for rom_id, ra_id in rom_ra_ids if ra_id in by_ra_id}
