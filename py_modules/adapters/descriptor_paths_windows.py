"""Windows implementation of the claim / remove / rename helpers in ``descriptor_paths``.

The Linux module anchors every step on directory descriptors (``dir_fd``
calls, ``renameat2``, file leases), none of which Windows has. This module
keeps the same contract with path-based calls, so ROM removal and save-file
moves work under Decky on Windows:

- every path is resolved component by component below its safe root, and any
  component that is a reparse point (symlink or junction) or sits on another
  volume is refused — the no-follow, single-mount rule;
- a claim records the same identity fields (``st_dev`` is the volume serial,
  ``st_ino`` the NTFS file index) and, when content-bound, every file's
  SHA-256, in the same ``SourceClaim`` shape the services already handle;
- a removal renames the claimed source to the shared staging name first
  (``os.rename`` never replaces on Windows), re-proves the staged tree against
  the claim, then unlinks file by file, re-proving each file just before it
  goes; a refused claim is renamed back.

Writer exclusion: Linux takes file leases. Windows refuses to delete or rename
a file another process holds open without delete sharing, which is how
emulators open saves and ROMs, so the unlink itself fails rather than racing a
writer. Durability: there is no directory fsync on Windows; NTFS journals the
metadata change.

``open_directory_fd``, ``open_regular_fd``, ``hold_writer_exclusion``,
``rename_noreplace_at`` and ``mount_id_for_fd`` stay descriptor-only and are
not provided here; the recovery-bundle and Steam-recovery flows that use them
are not yet supported on Windows.
"""

from __future__ import annotations

import hashlib
import os
import stat
from typing import TYPE_CHECKING

from lib.errors import OperationAbortedError

if TYPE_CHECKING:
    from collections.abc import Callable

    from models.prune import MutationOutcome, SourceClaim, SourceEntry, SourceIdentity

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_ALREADY_ABSENT = "Source was already absent"


# ── identity ────────────────────────────────────────────────────────────────


def identity_for_stat(value: os.stat_result, mount_id: int = 0) -> SourceIdentity:
    return {
        "exists": True,
        "mount_id": mount_id,
        "device": value.st_dev,
        "inode": value.st_ino,
        "mode": value.st_mode,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def missing_identity() -> SourceIdentity:
    return {"exists": False, "mount_id": 0, "device": 0, "inode": 0, "mode": 0, "size": 0, "mtime_ns": 0, "ctime_ns": 0}


def raise_if_aborted(should_abort: Callable[[], bool] | None) -> None:
    if should_abort is not None and should_abort():
        raise OperationAbortedError("The operation was cancelled before it committed anything.")


def staging_prefix(name: str) -> str:
    return f".{name}.romm-prune-"


def _is_link(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _lstat(path: str) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _identity(value: os.stat_result) -> SourceIdentity:
    # The volume serial doubles as the mount identity on Windows.
    return identity_for_stat(value, value.st_dev)


# ── anchoring ───────────────────────────────────────────────────────────────


def _relative_parts(path: str, safe_root: str) -> list[str]:
    absolute_root = os.path.abspath(safe_root)
    absolute_path = os.path.abspath(path)
    try:
        if os.path.normcase(os.path.commonpath((absolute_root, absolute_path))) != os.path.normcase(absolute_root):
            raise ValueError(f"Path is outside its safe root: {path}")
    except ValueError as exc:
        raise ValueError(f"Path is outside its safe root: {path}") from exc
    relative = os.path.relpath(absolute_path, absolute_root)
    if relative == ".":
        return []
    parts = relative.split(os.sep)
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Unsafe path component: {path}")
    return parts


def _root(safe_root: str) -> tuple[str, int]:
    root = os.path.abspath(safe_root)
    value = os.stat(root)
    if not stat.S_ISDIR(value.st_mode):
        raise NotADirectoryError(f"Safe root is not a directory: {safe_root}")
    return root, value.st_dev


def _walk_directory(path: str, safe_root: str, *, create: bool = False) -> tuple[str, int]:
    """Return *path* as a verified real directory below *safe_root*, and its volume."""
    current, volume = _root(safe_root)
    for component in _relative_parts(path, safe_root):
        current = os.path.join(current, component)
        value = _lstat(current)
        if value is None:
            if not create:
                raise FileNotFoundError(current)
            os.mkdir(current)
            value = os.lstat(current)
        if _is_link(value):
            raise ValueError(f"Path component may not be a link: {current}")
        if not stat.S_ISDIR(value.st_mode):
            raise NotADirectoryError(current)
        if value.st_dev != volume:
            raise ValueError(f"Path crosses a mount boundary: {path}")
    return current, volume


def _parent(path: str, safe_root: str) -> tuple[str, str, int]:
    parts = _relative_parts(path, safe_root)
    if not parts:
        raise ValueError(f"Path must be below its safe root: {path}")
    parent_path = os.path.join(safe_root, *parts[:-1]) if len(parts) > 1 else safe_root
    parent, volume = _walk_directory(parent_path, safe_root)
    return parent, parts[-1], volume


def require_directory(path: str, safe_root: str) -> None:
    _walk_directory(path, safe_root)


def ensure_directory(path: str, safe_root: str, mode: int = 0o700) -> None:  # noqa: ARG001 - POSIX mode has no meaning here
    _walk_directory(path, safe_root, create=True)


# ── inventory ───────────────────────────────────────────────────────────────


def _sha256(path: str, should_abort: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            raise_if_aborted(should_abort)
            digest.update(block)
    return digest.hexdigest()


def _inventory(
    directory: str,
    volume: int,
    prefix: str = "",
    *,
    should_abort: Callable[[], bool] | None = None,
    digest: bool = True,
) -> dict[str, SourceEntry]:
    entries: dict[str, SourceEntry] = {}
    for name in sorted(os.listdir(directory)):
        raise_if_aborted(should_abort)
        full = os.path.join(directory, name)
        value = os.lstat(full)
        relative = f"{prefix}/{name}" if prefix else name
        if _is_link(value):
            raise ValueError(f"Recovery source contains unsupported entry: {relative}")
        if value.st_dev != volume:
            raise ValueError(f"Path crosses a mount boundary: {relative}")
        if stat.S_ISDIR(value.st_mode):
            entries[relative] = {"identity": _identity(value)}
            entries.update(_inventory(full, volume, relative, should_abort=should_abort, digest=digest))
        elif stat.S_ISREG(value.st_mode):
            entry: SourceEntry = {"identity": _identity(value)}
            if digest:
                entry["sha256"] = _sha256(full, should_abort)
                if _identity(os.lstat(full)) != entry["identity"]:
                    raise RuntimeError(f"Recovery source changed while inventorying: {relative}")
            entries[relative] = entry
        else:
            raise ValueError(f"Recovery source contains unsupported entry: {relative}")
    return entries


def _claim(path, safe_root, identity, sha256, entries, content_bound) -> SourceClaim:
    return {
        "source_path": path,
        "safe_root": safe_root,
        "source_identity": identity,
        "sha256": sha256,
        "entries": entries,
        "content_bound": content_bound,
    }


def claim_source(
    path: str,
    safe_root: str,
    should_abort: Callable[[], bool] | None = None,
    *,
    digest: bool = True,
) -> SourceClaim:
    try:
        parent, name, volume = _parent(path, safe_root)
    except FileNotFoundError:
        return _claim(path, safe_root, missing_identity(), None, {}, digest)
    full = os.path.join(parent, name)
    value = _lstat(full)
    if value is None:
        return _claim(path, safe_root, missing_identity(), None, {}, digest)
    if _is_link(value):
        raise ValueError(f"Recovery source may not be a symlink: {path}")
    if value.st_dev != volume:
        raise ValueError(f"Path crosses a mount boundary: {path}")
    identity = _identity(value)
    if stat.S_ISREG(value.st_mode):
        sha = None
        if digest:
            sha = _sha256(full, should_abort)
            if _identity(os.lstat(full)) != identity:
                raise RuntimeError(f"Recovery source changed while it was claimed: {path}")
        return _claim(path, safe_root, identity, sha, {}, digest)
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"Recovery source has unsupported type: {path}")
    entries = _inventory(full, volume, should_abort=should_abort, digest=digest)
    return _claim(path, safe_root, identity, None, entries, digest)


def measure_tree(path: str, safe_root: str) -> int:
    try:
        parent, name, volume = _parent(path, safe_root)
    except FileNotFoundError:
        return 0
    full = os.path.join(parent, name)
    value = _lstat(full)
    if value is None:
        return 0
    if _is_link(value):
        raise ValueError(f"Recovery source may not be a symlink: {path}")
    if stat.S_ISREG(value.st_mode):
        return value.st_size
    if not stat.S_ISDIR(value.st_mode):
        raise ValueError(f"Recovery source has unsupported type: {path}")
    entries = _inventory(full, volume, digest=False)
    return sum(e["identity"]["size"] for e in entries.values() if stat.S_ISREG(e["identity"]["mode"]))


# ── validation ──────────────────────────────────────────────────────────────

_STABLE = ("device", "inode", "mode", "size", "mtime_ns")


def _require_claim_shape(path: str, safe_root: str, claim: SourceClaim) -> None:
    if claim["source_path"] != path or claim["safe_root"] != safe_root:
        raise ValueError(f"Source claim does not match its mutation target: {path}")


def _require_identity(path: str, current: os.stat_result | None, expected: SourceIdentity) -> None:
    if not expected["exists"]:
        if current is not None:
            raise RuntimeError(f"Recovery source appeared after sealing: {path}")
        return
    if current is None:
        raise RuntimeError(f"Recovery source disappeared after sealing: {path}")
    actual = _identity(current)
    if any(actual[f] != expected[f] for f in (*_STABLE, "ctime_ns")):
        raise RuntimeError(f"Recovery source identity changed after sealing: {path}")


def _require_stable(path: str, current: os.stat_result | None, expected: SourceIdentity) -> None:
    if current is None or not expected["exists"] or _is_link(current):
        raise RuntimeError(f"Recovery source identity changed while it was claimed: {path}")
    actual = _identity(current)
    if any(actual[f] != expected[f] for f in _STABLE):
        raise RuntimeError(f"Recovery source identity changed while it was claimed: {path}")


def _require_same_object(path: str, current: os.stat_result | None, expected: SourceIdentity) -> None:
    if current is None or _is_link(current):
        raise RuntimeError(f"Recovery source identity changed while it was claimed: {path}")
    actual = _identity(current)
    if any(actual[f] != expected[f] for f in ("device", "inode", "mode")):
        raise RuntimeError(f"Recovery source identity changed while it was claimed: {path}")


def _require_tree_matches(path: str, location: str, claim: SourceClaim) -> None:
    """Re-prove the whole claimed tree now living at *location*."""
    expected = claim["source_identity"]
    _require_stable(path, _lstat(location), expected)
    if stat.S_ISDIR(expected["mode"]):
        actual = _inventory(location, expected["mount_id"], digest=claim["content_bound"])
        if actual != claim["entries"]:
            raise RuntimeError(f"Recovery source subtree changed after sealing: {path}")
    elif claim["entries"]:
        raise ValueError(f"Regular-file recovery claim has descendants: {path}")
    elif claim["content_bound"] and _sha256(location) != claim["sha256"]:
        raise RuntimeError(f"Recovery source content changed after sealing: {path}")


def _outcome(*, success: bool, changed: bool, ambiguous: bool, message: str) -> MutationOutcome:
    return {"success": success, "changed": changed, "ambiguous": ambiguous, "message": message}


# ── mutations ───────────────────────────────────────────────────────────────


def _claimed_file_count(claim: SourceClaim) -> int:
    if not claim["source_identity"]["exists"]:
        return 0
    if stat.S_ISDIR(claim["source_identity"]["mode"]):
        return sum(1 for e in claim["entries"].values() if stat.S_ISREG(e["identity"]["mode"]))
    return 1


def _rename_back(staged: str, original: str) -> MutationOutcome | None:
    """Undo a staging rename. ``None`` means it was restored and the refusal must surface."""
    try:
        if _lstat(original) is not None:
            raise RuntimeError(f"Cannot restore claimed source because its path was replaced: {original}")
        os.rename(staged, original)
    except Exception as exc:
        return _outcome(
            success=False, changed=True, ambiguous=True, message=f"Source validation failed and rollback was uncertain: {exc}"
        )
    return None


def remove_claimed(
    path: str,
    safe_root: str,
    claim: SourceClaim,
    on_progress: Callable[[int, int], None] | None = None,
) -> MutationOutcome:
    _require_claim_shape(path, safe_root, claim)
    expected = claim["source_identity"]
    try:
        parent, name, _volume = _parent(path, safe_root)
    except FileNotFoundError:
        if expected["exists"]:
            raise RuntimeError(f"Recovery source disappeared after sealing: {path}") from None
        return _outcome(success=True, changed=False, ambiguous=False, message=_ALREADY_ABSENT)
    original = os.path.join(parent, name)
    current = _lstat(original)
    _require_identity(path, current, expected)
    if current is None:
        return _outcome(success=True, changed=False, ambiguous=False, message=_ALREADY_ABSENT)

    staged = os.path.join(parent, f"{staging_prefix(name)}{current.st_ino}")
    if _lstat(staged) is not None:
        raise FileExistsError(f"Prune staging entry already exists: {staged}")
    os.rename(original, staged)
    try:
        _require_tree_matches(path, staged, claim)
    except Exception:
        rollback = _rename_back(staged, original)
        if rollback is not None:
            return rollback
        raise

    total = _claimed_file_count(claim)
    removed = 0

    def tick() -> None:
        nonlocal removed
        removed += 1
        if on_progress is not None:
            on_progress(removed, total)

    try:
        if stat.S_ISDIR(expected["mode"]):
            # Deepest entries first so every directory is empty when it is removed.
            for relative in sorted(claim["entries"], key=lambda r: r.count("/"), reverse=True):
                entry = claim["entries"][relative]
                full = os.path.join(staged, *relative.split("/"))
                value = _lstat(full)
                if stat.S_ISDIR(entry["identity"]["mode"]):
                    # Its own children were just unlinked, which moves its mtime;
                    # identity (volume, file index, type) is what must still hold.
                    _require_same_object(relative, value, entry["identity"])
                    os.rmdir(full)
                else:
                    _require_stable(relative, value, entry["identity"])
                    if claim["content_bound"] and _sha256(full) != entry.get("sha256"):
                        raise RuntimeError(f"Recovery source changed while it was consumed: {relative}")
                    os.unlink(full)
                    tick()
            _require_same_object(path, _lstat(staged), expected)
            os.rmdir(staged)
        else:
            _require_stable(path, _lstat(staged), expected)
            os.unlink(staged)
            tick()
    except Exception as exc:
        summary = (
            "the source was claimed and no file was removed"
            if removed == 0
            else f"{removed} of {total} files were removed"
        )
        return _outcome(success=False, changed=True, ambiguous=True, message=f"Source removal stopped after {summary}: {exc}")
    return _outcome(success=True, changed=True, ambiguous=False, message="Source removed")


def remove_current(path: str, safe_root: str) -> MutationOutcome:
    return remove_claimed(path, safe_root, claim_source(path, safe_root))


def rename_claimed(src: str, dst: str, safe_root: str, claim: SourceClaim) -> MutationOutcome:
    _require_claim_shape(src, safe_root, claim)
    expected = claim["source_identity"]
    source_parent, source_name, volume = _parent(src, safe_root)
    destination_parent, destination_name, destination_volume = _parent(dst, safe_root)
    if destination_volume != volume:
        raise ValueError(f"Path crosses a mount boundary: {dst}")
    source = os.path.join(source_parent, source_name)
    destination = os.path.join(destination_parent, destination_name)
    current = _lstat(source)
    _require_identity(src, current, expected)
    if current is None:
        return _outcome(success=True, changed=False, ambiguous=False, message=_ALREADY_ABSENT)
    _require_tree_matches(src, source, claim)
    if _lstat(destination) is not None:
        raise FileExistsError(f"Recovery destination already exists: {dst}")
    try:
        os.rename(source, destination)  # never replaces an existing destination on Windows
    except FileExistsError:
        raise FileExistsError(f"Recovery destination already exists: {dst}") from None
    try:
        _require_tree_matches(src, destination, claim)
    except Exception as exc:
        if _lstat(source) is not None:
            return _outcome(
                success=False,
                changed=True,
                ambiguous=True,
                message=f"Rename validation failed and the source is still at {dst} because its original path was re-occupied: {exc}",
            )
        try:
            os.rename(destination, source)
        except Exception as restore_exc:
            return _outcome(
                success=False,
                changed=True,
                ambiguous=True,
                message=f"Rename validation failed and rollback was uncertain: {restore_exc}",
            )
        raise
    return _outcome(success=True, changed=True, ambiguous=False, message="Source renamed")
