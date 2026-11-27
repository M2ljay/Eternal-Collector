"""The Mods panel's bounded context: where a game's mods, cheats, patches and updates go, and changing them.

``GameModsService`` is the façade the plugin calls; its sub-modules resolve the
targets (``targets``), switch built-in entries (``toggles``) and install game
content through an emulator (``content``), and may import each other.
"""

from services.game_mods.service import GameModsService, GameModsServiceConfig

__all__ = ["GameModsService", "GameModsServiceConfig"]
