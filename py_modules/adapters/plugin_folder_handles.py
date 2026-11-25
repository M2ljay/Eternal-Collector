"""The registry of handles the backend holds inside its plugin folder. Implements ``PluginFolderHandles``.

Windows refuses to delete or overwrite a file another handle keeps open (a
loaded DLL is mapped, not just opened), and Decky Loader v3.3.1's installer
aborts mid-extract on the first such file, leaving a half-copied folder
(``docs/architecture/plugin-self-update.md``). Every holder registers here so
the self-update can close them all before the hand-off.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable


class PluginFolderHandleRegistry:
    """Real ``PluginFolderHandles``: named release callbacks, called in registration order."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._lock = threading.Lock()
        self._holders: dict[str, Callable[[], None]] = {}

    def register(self, name: str, release: Callable[[], None]) -> None:
        with self._lock:
            self._holders[name] = release

    def release_all(self) -> list[str]:
        with self._lock:
            holders = list(self._holders.items())
        failed: list[str] = []
        for name, release in holders:
            try:
                release()
            except Exception as e:
                self._logger.warning(f"Could not release {name} before the plugin update: {e}")
                failed.append(name)
        return failed
