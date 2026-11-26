"""The savestate backup decision — whether one local savestate goes to the server.

This is **not** a save-sync decision. It never feeds the save matrix, never reaches
the compiled gavel core, and never answers with a download: a savestate backup only
ever uploads, and only a savestate this device has not already accounted for.

The rule has two halves:

- a savestate whose content hash equals the one this device last recorded for that
  slot is unchanged, whatever its timestamps say;
- a changed savestate is uploaded only when it was written at or after the moment
  the user turned the backup on. One written before is recorded as a baseline
  instead, so turning the feature on never sends a backlog of old savestates the
  user did not ask to upload — Ludo re-uploaded 44 untouched savestates the first
  time one device connected, and seeds a baseline since. A missing enable stamp is
  read as "nothing qualifies yet", never as "everything does".
"""

from __future__ import annotations

from dataclasses import dataclass

UPLOAD = "upload"
ADOPT_BASELINE = "adopt_baseline"
UNCHANGED = "unchanged"
TOO_LARGE = "too_large"

# RomM's default ``MAX_ASSET_UPLOAD_SIZE_BYTES`` (512 MiB, utils/uploads.py at
# 5.4.1). A larger savestate would be refused after the whole body was sent.
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def savestate_backup_action(
    *,
    local_hash: str,
    recorded_hash: str | None,
    local_mtime: float,
    local_size: int,
    enabled_at: float | None,
) -> str:
    """Decide what the backup does with one local savestate.

    Returns :data:`UNCHANGED` when *local_hash* equals *recorded_hash* (the content
    this device last uploaded or recorded as a baseline for the slot);
    :data:`ADOPT_BASELINE` when it changed but was written before *enabled_at*, or
    when no enable stamp exists; :data:`TOO_LARGE` for a changed savestate past the
    server's default upload ceiling; otherwise :data:`UPLOAD`.
    """
    if recorded_hash is not None and recorded_hash == local_hash:
        return UNCHANGED
    if enabled_at is None or local_mtime < enabled_at:
        return ADOPT_BASELINE
    if local_size > MAX_UPLOAD_BYTES:
        return TOO_LARGE
    return UPLOAD


@dataclass(frozen=True, slots=True)
class SavestateBackupOutcome:
    """What one post-exit backup run did, counted per savestate.

    ``skipped`` names why the run looked at nothing at all (``disabled``,
    ``not_retroarch``, ``not_installed``, ``no_device``, ``no_states_folder``,
    ``content_dir``); ``None`` when it ran. ``failed`` counts uploads the server did
    not take; those slots stay unrecorded, so the next run tries them again.
    """

    backed_up: int = 0
    baselined: int = 0
    unchanged: int = 0
    failed: int = 0
    too_large: int = 0
    skipped: str | None = None
