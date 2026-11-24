"""Filesystem adapter for local save file operations.

Owns the raw POSIX, ``open()``, ``tempfile``, and ``hashlib``-on-file
calls used by SaveService and its sub-services when reading, writing,
backing up, hashing, and removing local save files under the RetroDECK
saves directory. Path construction, platform-specific extension lookup,
and slot/sync policy remain a service or domain concern; this adapter
exposes only the I/O seams declared by
``services.protocols.SaveFileStore``.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import tempfile
import zipfile
import zlib
from typing import TYPE_CHECKING

from adapters.descriptor_paths import claim_source, ensure_directory, rename_claimed
from domain.save_hash import combine_zip_entry_hashes
from domain.standalone_saves import BUNDLE_ENTRY_EPOCH, bundle_entries, bundle_entry_name
from lib.path_safety import PathTraversalError, safe_join

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterator

    from models.prune import MutationOutcome, SourceClaim

_MD5_CHUNK_SIZE = 8192

# Zip-decode failures a positive ``zipfile.is_zipfile`` sniff can still hit once
# the archive is actually read (the sniff only inspects the End-Of-Central-
# Directory record): a corrupt / truncated central directory or a bad entry CRC
# (``BadZipFile``), a compressed stream ``zlib`` cannot inflate (``zlib.error``),
# or an entry this runtime cannot decode — an encrypted member or a compression
# method the stdlib lacks (``RuntimeError``; the unknown-method
# ``NotImplementedError`` is a ``RuntimeError`` subclass, e.g. a save zipped with
# zstd, which ``zipfile`` only learns to read in 3.14). ``OSError`` is
# deliberately excluded so a genuine I/O fault (a vanished / unreadable file)
# still surfaces, matching the non-zip branch and ``checksum_md5``;
# ``LargeZipFile`` is excluded as an unreachable write-time ZIP64 guard.
_ZIP_READ_ERRORS = (zipfile.BadZipFile, zlib.error, RuntimeError)

# Stored, not deflated: zlib's output is not guaranteed identical across zlib
# builds (CPython on Windows bundles its own), and a bundle must be byte-stable
# for one folder on every device. Entry attributes are pinned for the same
# reason — ``ZipInfo.create_system`` otherwise follows the host OS.
_BUNDLE_FILE_ATTR = 0o100644 << 16
_BUNDLE_DIR_ATTR = (0o040755 << 16) | 0x10


class SaveFileAdapter:
    """Synchronous filesystem operations for local save files.

    Implements the ``SaveFileStore`` Protocol. Methods are
    synchronous — services that call from an async context offload via
    ``loop.run_in_executor``.
    """

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger
        # Per-run content-hash memo, live only inside ``hash_memo_scope``.
        # ``None`` outside a scope so non-sync callers never populate a
        # process-lifetime cache; a fresh dict per outermost scope bounds it to
        # one sync run. Keyed ``(path, mtime_ns, size)`` so a save overwritten
        # mid-run (a download) re-hashes on its new stat instead of returning a
        # stale digest. ``_hash_memo_depth`` makes nested scopes share one memo.
        self._hash_memo: dict[tuple[str, int, int], str] | None = None
        self._hash_memo_depth = 0

    def exists(self, path: str) -> bool:
        """Return True when *path* refers to an existing file or directory."""
        return os.path.exists(path)

    def is_file(self, path: str) -> bool:
        """Return True when *path* exists and is a regular file."""
        return os.path.isfile(path)

    def is_dir(self, path: str) -> bool:
        """Return True when *path* exists and is a directory."""
        return os.path.isdir(path)

    def is_symlink(self, path: str) -> bool:
        return os.path.islink(path)

    def canonical_path(self, path: str) -> str:
        return os.path.realpath(path)

    def is_within(self, path: str, root: str) -> bool:
        try:
            return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
        except ValueError:
            return False

    def make_dirs(self, path: str) -> None:
        """Create *path* and any missing parents. Idempotent."""
        os.makedirs(path, exist_ok=True)

    def remove_file(self, path: str) -> None:
        """Delete *path*. Idempotent: a missing file is not an error."""
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)

    def listdir(self, directory: str) -> list[str]:
        """Return the entry names in *directory*; empty list if it does not exist."""
        try:
            return os.listdir(directory)
        except FileNotFoundError:
            return []

    def rename(self, src: str, dst: str) -> None:
        """Atomically rename *src* to *dst*, replacing any existing file at *dst*."""
        os.replace(src, dst)

    def claim_source(self, path: str, safe_root: str) -> SourceClaim:
        return claim_source(path, safe_root)

    def ensure_directory(self, path: str, safe_root: str) -> None:
        ensure_directory(path, safe_root)

    def rename_claimed(self, src: str, dst: str, safe_root: str, claim: SourceClaim) -> MutationOutcome:
        return rename_claimed(src, dst, safe_root, claim)

    def get_mtime(self, path: str) -> float:
        """Return the mtime of *path* as a Unix timestamp."""
        return os.path.getmtime(path)

    def get_size(self, path: str) -> int:
        """Return the size of *path* in bytes."""
        return os.path.getsize(path)

    def checksum_md5(self, path: str) -> str:
        """Return the hex-encoded MD5 digest of *path*'s contents.

        Streams the file in fixed-size chunks so memory use stays
        bounded for large save files. Non-security use: MD5 here is the
        drift baseline that ``compute_sync_action`` compares against
        ``last_sync_hash`` to decide whether a local save changed since
        the last sync. ``usedforsecurity=False`` documents this and
        silences Sonar S4790.
        """
        h = hashlib.md5(usedforsecurity=False)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_MD5_CHUNK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()

    def content_hash(self, path: str) -> str:
        """Return RomM's content hash for *path* — zip-aware, MD5-based.

        Matches the server's ``compute_content_hash`` so a save's local and
        server hashes agree and save-sync converges. Dispatch mirrors RomM
        exactly: a file that *is* a zip archive (``zipfile.is_zipfile`` — a
        content sniff, not the extension) is hashed per entry and combined via
        :func:`domain.save_hash.combine_zip_entry_hashes`; any other file is the
        plain streamed MD5 of :meth:`checksum_md5`. Directory entries inside the
        archive are skipped. A positive sniff over a file that cannot be read as
        a zip falls back to the plain MD5 rather than raising (see
        :meth:`_compute_content_hash`). Non-security use, like ``checksum_md5``.

        Inside a :meth:`hash_memo_scope` the digest is memoized by the file's
        ``(path, mtime_ns, size)`` so one sync run's repeated hashings of the
        same save (negotiate inventory, the newest-wins matrix, the post-op
        baseline write) read it once. Outside a scope every call reads the file.
        """
        memo = self._hash_memo
        if memo is None:
            return self._compute_content_hash(path)
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        cached = memo.get(key)
        if cached is not None:
            return cached
        digest = self._compute_content_hash(path)
        memo[key] = digest
        return digest

    def _compute_content_hash(self, path: str) -> str:
        """Read *path* and compute its zip-aware RomM content hash (no memo).

        A file that ``zipfile.is_zipfile`` accepts but that cannot be read as a
        zip (``_ZIP_READ_ERRORS``) falls back to the plain streamed MD5 of
        :meth:`checksum_md5`. RomM's server degrades the same file to
        ``content_hash=None``, so the kernel's truthiness guards reject a
        ``None``-side identity match and the fallback can never manufacture a
        false byte-identical match — it only keeps the local drift baseline
        working. Both sides of the memo see the fallback value: the public
        :meth:`content_hash` memoizes whatever this method returns under the
        file's stat key.
        """
        if not zipfile.is_zipfile(path):
            return self.checksum_md5(path)
        try:
            with zipfile.ZipFile(path, "r") as zf:
                entries = [
                    (name, hashlib.md5(zf.read(name), usedforsecurity=False).hexdigest())
                    for name in zf.namelist()
                    if not name.endswith("/")
                ]
        except _ZIP_READ_ERRORS as exc:
            self._logger.debug("content_hash: %s sniffed as zip but unreadable (%s); MD5 fallback", path, exc)
            return self.checksum_md5(path)
        return combine_zip_entry_hashes(entries)

    @contextlib.contextmanager
    def hash_memo_scope(self) -> Iterator[None]:
        """Bound a :meth:`content_hash` memo to a single sync run.

        Within the scope, ``content_hash`` caches each save's digest keyed by
        ``(path, mtime_ns, size)`` so the several passes of one run that hash the
        same file read it once. The memo is discarded when the outermost scope
        exits, so it is never a process-lifetime cache; a file overwritten
        mid-run gets a new stat key and re-hashes. Reentrant — nested scopes
        share one memo and only the outermost clears it — so the engine can open
        it at both the sweep and per-ROM levels. The engine opens exactly one
        (outermost) scope per device-gated save-sync run, so within-scope hashing
        is single-threaded; callers outside a scope hash directly and never touch
        the memo.
        """
        self._hash_memo_depth += 1
        if self._hash_memo is None:
            self._hash_memo = {}
        try:
            yield
        finally:
            self._hash_memo_depth -= 1
            if self._hash_memo_depth == 0:
                self._hash_memo = None

    def make_temp_path(self, suffix: str = "") -> str:
        """Return a fresh, unique path safe to write to.

        Backed by ``tempfile.mkstemp`` so the file is created atomically
        (``O_EXCL``) before the fd is closed. The caller owns the file
        and is responsible for removing it.
        """
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        return path

    def read_bytes(self, path: str) -> bytes:
        """Return the contents of *path* as raw bytes."""
        with open(path, "rb") as f:
            return f.read()

    def pack_save_folder(self, folder: str, bundle_path: str) -> None:
        """Write *folder* as a deterministic zip at *bundle_path*.

        Entries are the folder's files and empty directories, relative and
        ``/``-separated, in :func:`domain.standalone_saves.bundle_entries`
        order, stored uncompressed with one fixed timestamp and fixed
        attributes — so an unchanged folder always yields identical bytes.
        Symlinks inside the folder are not followed or packed. The file is
        rewritten (atomically, via a sibling temp) only when its bytes would
        change, and then stamped with the newest mtime in the folder tree, so
        an untouched save keeps both its hash and its mtime between syncs.
        """
        files: list[str] = []
        empty_dirs: list[str] = []
        newest = os.path.getmtime(folder)
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            rel_root = os.path.relpath(root, folder).replace(os.sep, "/")
            prefix = "" if rel_root == "." else rel_root + "/"
            regular = [n for n in names if _is_regular(os.path.join(root, n))]
            for name in [*regular, *dirs]:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            files.extend(prefix + n for n in regular)
            if prefix and not regular and not dirs:
                empty_dirs.append(prefix)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
            for entry in bundle_entries(files, empty_dirs):
                info = zipfile.ZipInfo(entry, date_time=BUNDLE_ENTRY_EPOCH)
                info.create_system = 3
                if entry.endswith("/"):
                    info.external_attr = _BUNDLE_DIR_ATTR
                    zf.writestr(info, b"")
                else:
                    info.external_attr = _BUNDLE_FILE_ATTR
                    with open(os.path.join(folder, *entry.split("/")), "rb") as f:
                        zf.writestr(info, f.read())
        data = buffer.getvalue()
        if os.path.isfile(bundle_path):
            with open(bundle_path, "rb") as f:
                if f.read() == data:
                    return
        tmp = bundle_path + ".pack"
        with open(tmp, "wb") as f:
            f.write(data)
        os.utime(tmp, (newest, newest))
        os.replace(tmp, bundle_path)

    def unpack_save_bundle(self, bundle_path: str, dest_dir: str) -> None:
        """Extract the bundle at *bundle_path* into the new directory *dest_dir*.

        Every entry name is server-supplied: each must pass
        :func:`domain.standalone_saves.bundle_entry_name` and then resolve
        strictly inside *dest_dir* through :func:`lib.path_safety.safe_join`,
        and no name may repeat — otherwise :class:`PathTraversalError` is raised
        before anything is written. *dest_dir* must not exist yet; on any
        failure it is removed again, so the caller never sees a partial folder.
        Raises :class:`zipfile.BadZipFile` for a file that is not a readable zip.
        """
        if os.path.lexists(dest_dir):
            raise FileExistsError(dest_dir)
        with zipfile.ZipFile(bundle_path, "r") as zf:
            infos = zf.infolist()
            seen: set[str] = set()
            for info in infos:
                name = bundle_entry_name(info.filename)
                if name is None or name.rstrip("/") in seen:
                    raise PathTraversalError(f"unsafe or duplicate bundle entry: {info.filename!r}")
                seen.add(name.rstrip("/"))
            os.makedirs(dest_dir)
            try:
                for info in infos:
                    target = safe_join(dest_dir, *info.filename.rstrip("/").split("/"))
                    if info.filename.endswith("/"):
                        os.makedirs(target, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as f:
                        f.write(zf.read(info))
            except BaseException:
                shutil.rmtree(dest_dir, ignore_errors=True)
                raise

    def remove_tree(self, path: str, within: str) -> None:
        """Delete the directory *path* and everything under it, but only inside *within*.

        Refuses (``ValueError``) a *path* that is a symlink, is not a
        directory, or does not resolve strictly below *within* — the guard that
        keeps backup retention from ever reaching outside its own folder.
        """
        if os.path.islink(path) or not os.path.isdir(path):
            raise ValueError(f"not a removable directory: {path!r}")
        safe_join(within, os.path.relpath(path, within))
        shutil.rmtree(path)


def _is_regular(path: str) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)
