"""InstallIntegrityService — whether the installed plugin folder is the build its manifest describes.

Answers one question for the QAM: did the last install finish copying? The
size pass runs at backend start, before any other plugin module is imported;
the hash pass runs once, off the event loop. When files are missing or differ
and the self-update still keeps a verified zip of the running build, the
service restores exactly those files from it (never deleting anything);
otherwise the remedy is a reinstall through Decky Loader, offered by the
frontend.

Imports the standard library and its own domain/adapter halves only, and only
under ``TYPE_CHECKING`` beyond that, so it loads in a half-copied install.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.install_manifest import (
    INCOMPLETE,
    MANIFEST_NAME,
    STALE_FILES,
    UNCHECKED,
    InstallManifest,
    InstallManifestError,
    IntegrityReport,
    compare_sizes,
    content_matches,
    parse_manifest,
    unchecked,
    unreadable_manifest,
    with_hashes,
)

if TYPE_CHECKING:
    import logging

    from services.protocols import InstallFileScanner, InstallRepairStore

_PY_ROOT = "py_modules"
_LOGGED_PATHS = 8


@dataclass(frozen=True)
class InstallIntegrityServiceConfig:
    """Frozen wiring bundle: the event loop, the logger, the folder scanner, the running build's version and
    the store that restores files from a kept release zip.

    ``loop`` is ``None`` only for the synchronous pass ``main.py`` runs before importing the rest of the plugin,
    which never starts the hash pass; ``repair_store`` is ``None`` where no repair is wired.
    """

    loop: asyncio.AbstractEventLoop | None
    logger: logging.Logger
    scanner: InstallFileScanner
    current_version: str
    repair_store: InstallRepairStore | None = None


class InstallIntegrityService:
    """Compares the plugin folder with ``install-manifest.json`` and reports the verdict."""

    def __init__(self, *, config: InstallIntegrityServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._scanner = config.scanner
        self._current = config.current_version
        self._repair = config.repair_store
        self._manifest_raw: bytes | None = None
        self._manifest: InstallManifest | None = None
        self._report: IntegrityReport | None = None
        self._hash_task: asyncio.Future[None] | None = None
        self._import_error: str | None = None
        self._repaired: list[str] = []
        self._repair_source: str | None = None
        self._restart_needed = False

    def check_sizes(self) -> IntegrityReport:
        """Run the size pass now (stat calls only) and remember its verdict."""
        return self._log_size_pass(self._size_pass())

    def check_sizes_and_repair(self) -> IntegrityReport:
        """Run the size pass, restore what it finds missing or resized from the kept zip, and log the outcome.

        For the pass before the rest of the plugin is imported: a file restored
        here is imported fresh, so no restart is needed.
        """
        report = self._size_pass()
        if report.status == INCOMPLETE and self._repair_io(report):
            report = self._size_pass()
        return self._log_size_pass(report)

    def note_repaired(self, paths: tuple[str, ...], source: str | None) -> None:
        """Carry the repair an earlier pass did (before the plugin's import) into this service's report."""
        if paths:
            self._repaired.extend(p for p in paths if p not in self._repaired)
            self._repair_source = source

    @property
    def repaired(self) -> tuple[str, ...]:
        return tuple(self._repaired)

    @property
    def repair_source(self) -> str | None:
        return self._repair_source

    def _size_pass(self) -> IntegrityReport:
        try:
            raw = self._scanner.read_file(MANIFEST_NAME)
        except OSError as e:
            self._report = unreadable_manifest(f"{MANIFEST_NAME} could not be read: {e}")
            return self._report
        if raw is None:
            self._report = unchecked(f"no {MANIFEST_NAME} (a development install)")
            return self._report
        try:
            manifest = parse_manifest(raw)
        except InstallManifestError as e:
            self._report = unreadable_manifest(str(e))
            return self._report
        self._manifest_raw = raw
        self._manifest = manifest
        sizes = self._scanner.sizes([e.path for e in manifest.entries])
        present_py, present_dirs = self._scanner.python_tree(_PY_ROOT)
        self._report = compare_sizes(manifest, sizes, present_py, present_dirs)
        return self._report

    def start_hash_check(self) -> None:
        """Hash every file whose size matched, in an executor; a second call is a no-op."""
        if self._hash_task is not None or self._manifest is None or self._report is None:
            return
        loop = self._loop or asyncio.get_running_loop()
        self._hash_task = loop.run_in_executor(None, self._hash_io)

    def record_import_failure(self, error: str) -> None:
        """Note that the plugin's own modules failed to import, which only a broken copy explains."""
        self._import_error = error

    async def get_report(self) -> dict[str, Any]:
        """The verdict as ``{success: True, status, expected_version, current_version, ...}``.

        Waits for the hash pass when it is still running. ``status`` is ``ok``,
        ``incomplete``, ``stale_files`` or ``unchecked``; an import failure with
        an otherwise clean folder still reports ``incomplete``. ``repaired``
        lists the files restored from the kept zip (named by ``repair_source``),
        and ``restart_needed`` is True when that happened after the plugin's
        modules were already imported.
        """
        if self._report is None:
            self.check_sizes()
        self.start_hash_check()
        if self._hash_task is not None:
            try:
                await asyncio.shield(self._hash_task)
            except Exception as e:
                self._logger.warning(f"Install check: the hash pass failed: {e}")
        report = self._report
        assert report is not None
        out: dict[str, Any] = {
            "success": True,
            "current_version": self._current,
            **report.to_dict(),
            "repaired": list(self._repaired),
            "repair_source": self._repair_source,
            "restart_needed": self._restart_needed,
        }
        if self._import_error is not None:
            out["import_error"] = self._import_error
            if report.status != INCOMPLETE:
                out["status"] = INCOMPLETE
        return out

    def _hash_io(self) -> None:
        report = self._hash_pass()
        if report.status == INCOMPLETE and self._repair_io(report):
            self._restart_needed = True
            self._size_pass()
            report = self._hash_pass()
        self._report = self._log(report)

    def _hash_pass(self) -> IntegrityReport:
        manifest, report = self._manifest, self._report
        assert manifest is not None and report is not None
        skip = set(report.missing) | set(report.mismatched)
        digests = {e.path: self._scanner.sha256(e.path) for e in manifest.entries if e.path not in skip}
        self._report = with_hashes(report, manifest, digests)
        return self._report

    def _repair_io(self, report: IntegrityReport) -> bool:
        """Restore *report*'s missing and differing files from the kept zip of this build; True if any was written.

        The zip counts as this build only when its ``install-manifest.json`` is
        byte-identical to the installed one, and each file is written only when
        its size and SHA-256 are the manifest's.
        """
        manifest, raw, store = self._manifest, self._manifest_raw, self._repair
        wanted = sorted(set(report.missing) | set(report.mismatched))
        if manifest is None or raw is None or store is None or not wanted:
            return False
        archive = store.cached_release(manifest.version)
        if archive is None:
            return False
        members = store.read_members(archive, [MANIFEST_NAME, *wanted])
        if members.get(MANIFEST_NAME) != raw:
            self._logger.warning(f"Install check: {os.path.basename(archive)} is not this build; not restoring from it")
            return False
        entries = {e.path: e for e in manifest.entries}
        restored: list[str] = []
        failed: list[str] = []
        for path in wanted:
            data = members.get(path)
            if data is None or not content_matches(entries[path], data):
                failed.append(path)
                continue
            try:
                store.write_file(path, data)
            except OSError as e:
                self._logger.warning(f"Install check: could not restore {path}: {e}")
                failed.append(path)
                continue
            restored.append(path)
        if restored:
            self.note_repaired(tuple(restored), os.path.basename(archive))
            self._logger.info(
                f"Install check: restored {len(restored)} file(s) from {os.path.basename(archive)}: "
                f"{restored[:_LOGGED_PATHS]}"
            )
        if failed:
            self._logger.warning(f"Install check: could not restore {failed[:_LOGGED_PATHS]}")
        return bool(restored)

    def _log_size_pass(self, report: IntegrityReport) -> IntegrityReport:
        return report if report.status == UNCHECKED else self._log(report)

    def _log(self, report: IntegrityReport) -> IntegrityReport:
        if report.status == INCOMPLETE:
            self._logger.error(
                "Install check: this copy of the plugin is incomplete "
                f"(expected {report.expected_version}, running {self._current}); "
                f"missing {list(report.missing[:_LOGGED_PATHS])}, differing {list(report.mismatched[:_LOGGED_PATHS])}"
                + (f"; {report.detail}" if report.detail else "")
            )
        elif report.status == STALE_FILES:
            self._logger.warning(
                f"Install check: leftover files from an older build: {list(report.extra[:_LOGGED_PATHS])}"
                + (f" (shadowing packages: {list(report.shadowing)})" if report.shadowing else "")
            )
        elif report.hashes_checked:
            self._logger.info(f"Install check: {report.status}")
        return report
