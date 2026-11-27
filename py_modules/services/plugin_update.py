"""PluginUpdateService — this fork's self-update channel.

Owns the answer to "is a newer fork build published?" and the preparation of an
install: the build is downloaded into the plugin's runtime folder and must match
its ``update.json`` size and SHA-256 before the frontend may hand it to Decky
Loader's own installer, and the installed plugin folder is snapshotted first so
the previous build can be reinstalled the same way.

Offered only on a Windows fork build (a ``-win.N`` version on ``win32``); every
other build answers ``supported: False`` and is left to the Decky store.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.install_manifest import RELEASE_DOWNLOAD_DIR, release_zip_name
from domain.plugin_release import (
    CHECK_INTERVAL_SECONDS,
    MANIFEST_URL,
    MAX_MANIFEST_BYTES,
    ManifestError,
    ReleaseManifest,
    is_fork_build,
    is_newer,
    parse_manifest,
)
from lib.errors import PluginReleaseFetchError
from lib.list_result import ErrorCode

if TYPE_CHECKING:
    import asyncio
    import logging

    from services.protocols import (
        Clock,
        DebugLogger,
        PluginFolderHandles,
        PluginReleaseSource,
        PluginUpdateFileStore,
        RunningExecutablesFn,
    )

_STATE_FILE = "state.json"
_PREVIOUS_DIR = "previous"
_PREVIOUS_RECORD = "previous.json"
_UNSUPPORTED = "Self-update is only offered on the Windows fork build."
_GAME_RUNNING = (
    "A game started from The Collector is still running. Close it first: Windows keeps the game "
    "launcher locked while it runs, and Decky cannot replace a locked file."
)
# Decky Loader's PluginInstallType (backend/decky_loader/browser.py, v3.3.1); its prompt words itself from it.
INSTALL_TYPE_REINSTALL = 1
INSTALL_TYPE_UPDATE = 2


@dataclass(frozen=True)
class PluginUpdateServiceConfig:
    """Frozen wiring bundle handed to ``PluginUpdateService.__init__``.

    Carries the runtime infrastructure (loop, logger, debug logger, clock), the
    release-channel transport and the staging-folder store (``None`` where they
    are not wired), the running build's version, the installed plugin folder,
    the staging folder under the runtime dir, whether this platform takes
    its updates from the fork at all, the process-table read and launcher exe
    name that tell whether a game the plugin launched is running (``None``
    where they cannot be read), and the registry of handles to close before
    the hand-off.
    """

    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    log_debug: DebugLogger
    clock: Clock
    release_source: PluginReleaseSource | None
    files: PluginUpdateFileStore | None
    current_version: str
    plugin_dir: str
    staging_dir: str
    platform_supported: bool
    running_executables: RunningExecutablesFn | None = None
    launcher_name: str = ""
    folder_handles: PluginFolderHandles | None = None


class PluginUpdateService:
    """Checks the fork's release channel and stages verified builds for Decky's installer."""

    def __init__(self, *, config: PluginUpdateServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._log_debug = config.log_debug
        self._clock = config.clock
        self._source = config.release_source
        self._files = config.files
        self._current = config.current_version
        self._plugin_dir = config.plugin_dir
        self._staging_dir = config.staging_dir
        self._running_executables = config.running_executables
        self._launcher_name = config.launcher_name.lower()
        self._handles = config.folder_handles
        self._supported = (
            config.platform_supported
            and config.release_source is not None
            and config.files is not None
            and is_fork_build(config.current_version)
        )
        self._manifest: ReleaseManifest | None = None
        self._checked_at: float | None = None
        self._state_loaded = False

    def is_supported(self) -> bool:
        return self._supported

    # ── check ──────────────────────────────────────────────────────

    async def check_for_update(self, force: bool = False) -> dict[str, Any]:
        """Report whether a newer fork build is published.

        Reads the channel at most once per ``CHECK_INTERVAL_SECONDS`` (the last
        answer survives a plugin restart); ``force`` reads it now. Returns
        ``{success: True, supported, current, update_available, version, notes,
        size, checked_at}`` or the standard failure shape.
        """
        if not self._supported:
            return {"success": True, "supported": False, "current": self._current, "update_available": False}
        await self._load_state()
        now = self._clock.time()
        fresh = self._checked_at is not None and 0 <= now - self._checked_at < CHECK_INTERVAL_SECONDS
        if force or not fresh or self._manifest is None:
            failure = await self._refresh(now)
            if failure is not None:
                return failure
        return self._answer()

    def _answer(self) -> dict[str, Any]:
        manifest = self._manifest
        available = manifest is not None and is_newer(self._current, manifest.version)
        out: dict[str, Any] = {
            "success": True,
            "supported": True,
            "current": self._current,
            "update_available": available,
            "checked_at": self._checked_at,
        }
        if manifest is not None:
            out.update(version=manifest.version, notes=manifest.notes, size=manifest.size)
        return out

    async def _refresh(self, now: float) -> dict[str, Any] | None:
        try:
            manifest = await self._fetch_manifest(now)
        except PluginReleaseFetchError as e:
            self._logger.warning(f"Plugin update check failed: {e}")
            return self._failure(ErrorCode.SERVER_UNREACHABLE, str(e))
        except ManifestError as e:
            self._logger.warning(f"Plugin update check: {e}")
            return self._failure("manifest_invalid", str(e))
        self._manifest = manifest
        self._checked_at = now
        await self._run(self._save_state_io)
        self._log_debug(f"Plugin update check: published {manifest.version}, running {self._current}")
        return None

    async def _fetch_manifest(self, now: float) -> ReleaseManifest:
        assert self._source is not None
        source = self._source
        url = f"{MANIFEST_URL}?t={int(now)}"
        body = await self._run(lambda: source.fetch_manifest(url, MAX_MANIFEST_BYTES))
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ManifestError(f"update.json is not valid JSON: {e}") from e
        return parse_manifest(payload)

    # ── prepare ────────────────────────────────────────────────────

    async def prepare_update(self) -> dict[str, Any]:
        """Download the newest build, verify it, and snapshot the installed one.

        Always re-reads ``update.json`` first, so what is installed is what is
        published now. Returns ``{success: True, version, artifact, sha256,
        size, install_type}`` where ``artifact`` is a ``file://`` path Decky's
        installer reads, or the standard failure shape — nothing is handed on
        unless the downloaded file's size and SHA-256 both match the manifest,
        no game the plugin launched is running, and the installed build was
        snapshotted. The plugin's own handles inside its folder are closed last.
        """
        return await self._prepare(reinstall=False)

    async def prepare_reinstall(self) -> dict[str, Any]:
        """Download and verify the published build to repair a half-copied install.

        Like :meth:`prepare_update`, but the published build may be the running
        version (``install_type`` REINSTALL) as well as a newer one (UPDATE),
        and the installed folder is not snapshotted: a broken copy must not
        replace the rollback build kept from the last good update. An older
        published build is refused with ``channel_older``.
        """
        return await self._prepare(reinstall=True)

    async def _prepare(self, *, reinstall: bool) -> dict[str, Any]:
        if not self._supported:
            return self._failure(ErrorCode.UNSUPPORTED, _UNSUPPORTED)
        if await self._run(self._game_running_io):
            return self._failure("game_running", _GAME_RUNNING)
        await self._load_state()
        now = self._clock.time()
        failure = await self._refresh(now)
        if failure is not None:
            return failure
        manifest = self._manifest
        assert manifest is not None
        newer = is_newer(self._current, manifest.version)
        if reinstall:
            if not newer and manifest.version != self._current:
                return self._failure(
                    "channel_older",
                    f"The update channel only has {manifest.version}, older than the installed {self._current}. "
                    f"Install {release_zip_name(self._current)} again from Decky's Developer menu "
                    "(Install plugin from ZIP).",
                )
        elif not newer:
            return self._failure("up_to_date", f"{self._current} is already the newest build.")

        download_dir = os.path.join(self._staging_dir, RELEASE_DOWNLOAD_DIR)
        dest = os.path.join(download_dir, release_zip_name(manifest.version))
        try:
            size, sha256 = await self._run(lambda: self._download_io(download_dir, dest, manifest, now))
        except PluginReleaseFetchError as e:
            self._logger.warning(f"Plugin update download failed: {e}")
            return self._failure(ErrorCode.SERVER_UNREACHABLE, str(e))
        except OSError as e:
            self._logger.warning(f"Plugin update download failed: {e}")
            return self._failure("download_failed", f"Could not save the update: {e}")

        if size != manifest.size:
            await self._run(lambda: self._discard_io(dest))
            return self._failure(
                "size_mismatch",
                f"The download is {size} bytes, update.json says {manifest.size}. Nothing was installed; "
                "if the build was just published, try again in a few minutes.",
            )
        if sha256 != manifest.sha256:
            await self._run(lambda: self._discard_io(dest))
            return self._failure(
                "hash_mismatch",
                "The download's SHA-256 does not match update.json. Nothing was installed; "
                "if the build was just published, try again in a few minutes.",
            )

        if not reinstall:
            try:
                await self._run(self._snapshot_installed_io)
            except OSError as e:
                self._logger.warning(f"Plugin update: snapshot of the installed build failed: {e}")
                return self._failure("backup_failed", f"Could not back up the installed build, so it was kept: {e}")

        if await self._run(self._game_running_io):
            await self._run(lambda: self._discard_io(dest))
            return self._failure("game_running", _GAME_RUNNING)
        self._release_handles()

        verb = "reinstall" if reinstall else "update"
        self._logger.info(f"Plugin {verb} {manifest.version} downloaded and verified ({size} bytes)")
        return {
            "success": True,
            "version": manifest.version,
            "artifact": _file_artifact(dest),
            "sha256": sha256,
            "size": size,
            "install_type": INSTALL_TYPE_UPDATE if newer else INSTALL_TYPE_REINSTALL,
        }

    async def prepare_for_install(self) -> dict[str, Any]:
        """The last step before the frontend hands any build to Decky Loader's installer.

        Every hand-off goes through here (update, reinstall, rollback): refuses
        with ``game_running`` while a game the plugin launched runs, then
        releases every handle the backend holds inside its own folder. Returns
        ``{success: True, still_held}`` — ``still_held`` names holders whose
        release failed (logged; the install is still allowed, as a refusal
        would leave the user nothing to do) — or the standard failure shape.
        """
        if await self._run(self._game_running_io):
            return self._failure("game_running", _GAME_RUNNING)
        return {"success": True, "still_held": self._release_handles()}

    def _game_running_io(self) -> bool:
        if self._running_executables is None or not self._launcher_name:
            return False
        names = self._running_executables()
        if names is None:
            self._logger.warning("Plugin update: the process table could not be read; not checking for a running game")
            return False
        return self._launcher_name in names

    def _release_handles(self) -> list[str]:
        if self._handles is None:
            return []
        failed = self._handles.release_all()
        if failed:
            self._logger.warning(f"Plugin update: still holding {failed} inside the plugin folder")
        return failed

    def _download_io(self, download_dir: str, dest: str, manifest: ReleaseManifest, now: float) -> tuple[int, str]:
        assert self._source is not None and self._files is not None
        self._files.ensure_dir(download_dir)
        return self._source.download(f"{manifest.url}?t={int(now)}", dest, manifest.size)

    def _discard_io(self, path: str) -> None:
        assert self._files is not None
        self._files.remove(path)

    def _snapshot_installed_io(self) -> None:
        assert self._files is not None
        previous_dir = os.path.join(self._staging_dir, _PREVIOUS_DIR)
        self._files.ensure_dir(previous_dir)
        dest = os.path.join(previous_dir, "romm-dock-previous.zip")
        size, sha256 = self._files.archive_folder(self._plugin_dir, os.path.basename(self._plugin_dir), dest)
        self._files.write_json(
            os.path.join(previous_dir, _PREVIOUS_RECORD),
            {"version": self._current, "sha256": sha256, "size": size, "path": dest},
        )

    # ── rollback ───────────────────────────────────────────────────

    async def get_rollback(self) -> dict[str, Any]:
        """Report the build kept from before the last update, if it can be reinstalled.

        Returns ``{success: True, available: False}`` when there is none (or it
        is the running build, or its file no longer matches its record), else
        ``{success: True, available: True, version, artifact, sha256}``.
        """
        if not self._supported:
            return {"success": True, "available": False}
        record = await self._run(self._read_previous_io)
        if record is None:
            return {"success": True, "available": False}
        return {"success": True, "available": True, **record}

    def _read_previous_io(self) -> dict[str, Any] | None:
        assert self._files is not None
        previous_dir = os.path.join(self._staging_dir, _PREVIOUS_DIR)
        record = self._files.read_json(os.path.join(previous_dir, _PREVIOUS_RECORD))
        if record is None:
            return None
        version, sha256, path = record.get("version"), record.get("sha256"), record.get("path")
        if not (isinstance(version, str) and isinstance(sha256, str) and isinstance(path, str)):
            return None
        if version == self._current or os.path.dirname(path) != previous_dir:
            return None
        actual = self._files.digest(path)
        if actual is None or actual[1] != sha256:
            return None
        return {"version": version, "artifact": _file_artifact(path), "sha256": sha256}

    # ── state ──────────────────────────────────────────────────────

    async def _load_state(self) -> None:
        if self._state_loaded:
            return
        self._state_loaded = True
        state = await self._run(self._read_state_io)
        if state is None:
            return
        checked_at = state.get("checked_at")
        try:
            manifest = parse_manifest(state.get("manifest"))
        except ManifestError:
            return
        if isinstance(checked_at, (int, float)) and not isinstance(checked_at, bool):
            self._manifest = manifest
            self._checked_at = float(checked_at)

    def _read_state_io(self) -> dict[str, object] | None:
        assert self._files is not None
        return self._files.read_json(os.path.join(self._staging_dir, _STATE_FILE))

    def _save_state_io(self) -> None:
        assert self._files is not None and self._manifest is not None
        m = self._manifest
        try:
            self._files.ensure_dir(self._staging_dir)
            self._files.write_json(
                os.path.join(self._staging_dir, _STATE_FILE),
                {
                    "checked_at": self._checked_at,
                    "manifest": {
                        "version": m.version,
                        "sha256": m.sha256,
                        "size": m.size,
                        "notes": m.notes,
                        "url": m.url,
                    },
                },
            )
        except OSError as e:
            self._logger.warning(f"Plugin update: could not record the last check: {e}")

    # ── helpers ────────────────────────────────────────────────────

    async def _run(self, fn):
        return await self._loop.run_in_executor(None, fn)

    def _failure(self, reason: ErrorCode | str, message: str) -> dict[str, Any]:
        return {"success": False, "reason": reason, "message": message, "current": self._current}


def _file_artifact(path: str) -> str:
    # Decky's PluginBrowser._install opens ``artifact[7:]`` for a ``file://``
    # artifact (backend/decky_loader/browser.py), so the raw path follows the
    # scheme unchanged — ``file://C:\...`` on Windows, ``file:///home/...`` elsewhere.
    return "file://" + path
