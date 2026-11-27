"""Import-safe composition root: the install check and the self-update channel.

``bootstrap/`` wires the whole plugin, so one missing or stale module anywhere
stops all of it from importing — which is exactly the state a half-copied
install is in (``docs/architecture/plugin-self-update.md``). This root wires
only what is needed to say so and to repair it: ``InstallIntegrityService`` and
``PluginUpdateService``. ``main.py`` imports it before anything else and builds
it before the full bootstrap, so both services work when the rest cannot load.

It lives outside the ``bootstrap`` package on purpose: importing any module of
that package runs its ``__init__``, which imports every adapter and service.
The integrity half imports at module level and is stdlib-only; the update half
is imported inside :func:`build_core` and degrades to ``None`` if it cannot be.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from adapters.install_files import InstallFileAdapter
from adapters.install_repair_files import InstallRepairFileAdapter
from domain.install_manifest import RELEASE_DOWNLOAD_DIR, UPDATE_STAGING_DIR
from services.install_integrity import InstallIntegrityService, InstallIntegrityServiceConfig

if TYPE_CHECKING:
    import asyncio
    import logging

    from services.plugin_update import PluginUpdateService
    from services.protocols import DebugLogger, PluginFolderHandles


@dataclass(frozen=True)
class CoreServices:
    """What the core root builds; ``plugin_update`` and ``folder_handles`` are ``None`` when they failed to import."""

    install_integrity: InstallIntegrityService
    plugin_update: PluginUpdateService | None
    folder_handles: PluginFolderHandles | None
    current_version: str
    update_wiring_error: str | None


def read_plugin_version(plugin_dir: str) -> str:
    """``package.json``'s version, ``""`` when it cannot be read."""
    import json

    try:
        with open(os.path.join(plugin_dir, "package.json"), encoding="utf-8") as f:
            version = json.load(f).get("version", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return version if isinstance(version, str) else ""


def _integrity_service(
    *, loop: asyncio.AbstractEventLoop | None, logger: logging.Logger, plugin_dir: str, runtime_dir: str
) -> InstallIntegrityService:
    return InstallIntegrityService(
        config=InstallIntegrityServiceConfig(
            loop=loop,
            logger=logger,
            scanner=InstallFileAdapter(plugin_dir),
            current_version=read_plugin_version(plugin_dir),
            repair_store=InstallRepairFileAdapter(
                plugin_dir, os.path.join(runtime_dir, UPDATE_STAGING_DIR, RELEASE_DOWNLOAD_DIR)
            ),
        )
    )


def check_install_before_import(
    *, logger: logging.Logger, plugin_dir: str, runtime_dir: str
) -> InstallIntegrityService:
    """The size pass ``main.py`` runs before importing the rest of the plugin, repairing from the kept zip.

    A half-copied install whose verified release zip is still kept heals here,
    and the plugin then imports the restored files on this very start.
    """
    integrity = _integrity_service(loop=None, logger=logger, plugin_dir=plugin_dir, runtime_dir=runtime_dir)
    integrity.check_sizes_and_repair()
    return integrity


def build_core(
    *,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger,
    log_debug: DebugLogger,
    plugin_dir: str,
    runtime_dir: str,
    pre_import_check: InstallIntegrityService | None = None,
) -> CoreServices:
    """Build the install check (running its size pass now) and, when it imports, the update service.

    *pre_import_check* is the pass :func:`check_install_before_import` ran;
    what it restored is carried into this check's report.
    """
    version = read_plugin_version(plugin_dir)
    integrity = _integrity_service(loop=loop, logger=logger, plugin_dir=plugin_dir, runtime_dir=runtime_dir)
    if pre_import_check is not None:
        integrity.note_repaired(pre_import_check.repaired, pre_import_check.repair_source)
    integrity.check_sizes()

    try:
        plugin_update, handles = _build_update(
            loop=loop,
            logger=logger,
            log_debug=log_debug,
            plugin_dir=plugin_dir,
            runtime_dir=runtime_dir,
            version=version,
        )
    except Exception as e:
        logger.error(f"Plugin self-update could not be wired: {e!r}")
        return CoreServices(integrity, None, None, version, repr(e))
    return CoreServices(integrity, plugin_update, handles, version, None)


def _build_update(
    *,
    loop: asyncio.AbstractEventLoop,
    logger: logging.Logger,
    log_debug: DebugLogger,
    plugin_dir: str,
    runtime_dir: str,
    version: str,
) -> tuple[PluginUpdateService, PluginFolderHandles]:
    from adapters.plugin_folder_handles import PluginFolderHandleRegistry
    from adapters.plugin_release import PluginReleaseHttpAdapter
    from adapters.plugin_update_files import PluginUpdateFileAdapter
    from adapters.system_clock import SystemClock
    from services.plugin_update import PluginUpdateService, PluginUpdateServiceConfig

    running_executables = None
    launcher_name = ""
    if sys.platform == "win32":
        from adapters.game_process_windows import WindowsGameProcessAdapter
        from domain.shortcut_data import ROM_LAUNCHER_NAME

        running_executables = WindowsGameProcessAdapter().running_executable_names
        launcher_name = ROM_LAUNCHER_NAME

    handles = PluginFolderHandleRegistry(logger)
    service = PluginUpdateService(
        config=PluginUpdateServiceConfig(
            loop=loop,
            logger=logger,
            log_debug=log_debug,
            clock=SystemClock(),
            release_source=PluginReleaseHttpAdapter(user_agent=f"romm-dock/{version}"),
            files=PluginUpdateFileAdapter(),
            current_version=version,
            plugin_dir=plugin_dir,
            staging_dir=os.path.join(runtime_dir, UPDATE_STAGING_DIR),
            platform_supported=sys.platform == "win32",
            running_executables=running_executables,
            launcher_name=launcher_name,
            folder_handles=handles,
        )
    )
    return service, handles
