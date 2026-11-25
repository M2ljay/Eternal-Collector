"""InstallIntegrityService — whether the installed plugin folder is the build its manifest describes.

Answers one question for the QAM: did the last install finish copying? The
size pass runs at backend start, before any other plugin module is imported;
the hash pass runs once, off the event loop. Nothing here repairs a folder —
the remedy is a reinstall through Decky Loader, offered by the frontend.

Imports the standard library and its own domain/adapter halves only, and only
under ``TYPE_CHECKING`` beyond that, so it loads in a half-copied install.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.install_manifest import (
    INCOMPLETE,
    MANIFEST_NAME,
    STALE_FILES,
    InstallManifest,
    InstallManifestError,
    IntegrityReport,
    compare_sizes,
    parse_manifest,
    unchecked,
    unreadable_manifest,
    with_hashes,
)

if TYPE_CHECKING:
    import logging

    from services.protocols import InstallFileScanner

_PY_ROOT = "py_modules"
_LOGGED_PATHS = 8


@dataclass(frozen=True)
class InstallIntegrityServiceConfig:
    """Frozen wiring bundle: the event loop, the logger, the folder scanner and the running build's version."""

    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    scanner: InstallFileScanner
    current_version: str


class InstallIntegrityService:
    """Compares the plugin folder with ``install-manifest.json`` and reports the verdict."""

    def __init__(self, *, config: InstallIntegrityServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._scanner = config.scanner
        self._current = config.current_version
        self._manifest: InstallManifest | None = None
        self._report: IntegrityReport | None = None
        self._hash_task: asyncio.Future[None] | None = None
        self._import_error: str | None = None

    def check_sizes(self) -> IntegrityReport:
        """Run the size pass now (stat calls only) and remember its verdict."""
        try:
            raw = self._scanner.read_file(MANIFEST_NAME)
        except OSError as e:
            self._report = unreadable_manifest(f"{MANIFEST_NAME} could not be read: {e}")
            return self._log(self._report)
        if raw is None:
            self._report = unchecked(f"no {MANIFEST_NAME} (a development install)")
            return self._report
        try:
            manifest = parse_manifest(raw)
        except InstallManifestError as e:
            self._report = unreadable_manifest(str(e))
            return self._log(self._report)
        self._manifest = manifest
        sizes = self._scanner.sizes([e.path for e in manifest.entries])
        present_py, present_dirs = self._scanner.python_tree(_PY_ROOT)
        self._report = compare_sizes(manifest, sizes, present_py, present_dirs)
        return self._log(self._report)

    def start_hash_check(self) -> None:
        """Hash every file whose size matched, in an executor; a second call is a no-op."""
        if self._hash_task is not None or self._manifest is None or self._report is None:
            return
        self._hash_task = self._loop.run_in_executor(None, self._hash_io)

    def record_import_failure(self, error: str) -> None:
        """Note that the plugin's own modules failed to import, which only a broken copy explains."""
        self._import_error = error

    async def get_report(self) -> dict[str, Any]:
        """The verdict as ``{success: True, status, expected_version, current_version, ...}``.

        Waits for the hash pass when it is still running. ``status`` is ``ok``,
        ``incomplete``, ``stale_files`` or ``unchecked``; an import failure with
        an otherwise clean folder still reports ``incomplete``.
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
        out: dict[str, Any] = {"success": True, "current_version": self._current, **report.to_dict()}
        if self._import_error is not None:
            out["import_error"] = self._import_error
            if report.status != INCOMPLETE:
                out["status"] = INCOMPLETE
        return out

    def _hash_io(self) -> None:
        manifest, report = self._manifest, self._report
        assert manifest is not None and report is not None
        skip = set(report.missing) | set(report.mismatched)
        digests = {e.path: self._scanner.sha256(e.path) for e in manifest.entries if e.path not in skip}
        self._report = self._log(with_hashes(report, manifest, digests))

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
