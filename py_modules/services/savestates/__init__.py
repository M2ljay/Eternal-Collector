"""Savestate backup subsystem.

The package's public API is ``SavestateService``: the upload-only backup of
RetroArch savestates to RomM after a game exits, over the SQLite
``rom_savestate_sync_states`` aggregate, plus the settings behind it (ADR-0031).
"""

from services.savestates.service import SavestateService, SavestateServiceConfig

__all__ = ["SavestateService", "SavestateServiceConfig"]
