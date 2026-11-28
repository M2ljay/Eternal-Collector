"""SteamCollectionOwnershipService — the record of which Steam collections the plugin owns.

Steam's collections live in the frontend (``collectionStore``), so the frontend makes,
renames and deletes them; this service only keeps the record it acts on. The record
is the ownership proof: the frontend touches a collection only when a record names
its Steam id, so a collection the user made is never renamed, refilled or deleted,
whatever it is called. The service validates what the untrusted wire sends and
answers in the canonical failure shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from domain.owned_steam_collection import ADOPTION_DONE_KEY, OwnedSteamCollection
from domain.platform_names import decode_romm_platform_names, platform_renames

if TYPE_CHECKING:
    from services.protocols import DebugLogger, UnitOfWorkFactory

NAME_STYLE_SETTING: Final = "collection_name_style"
INSTALLED_COLLECTION_SETTING: Final = "installed_roms_collection"
FAMILY_COLLECTIONS_SETTING: Final = "family_collections"
NAME_STYLES: Final[tuple[str, ...]] = ("classic", "clean")
DEFAULT_NAME_STYLE: Final = "classic"
_PLATFORM_NAMES_KEY: Final = "platform_names"


def name_style_of(settings: dict[str, Any]) -> str:
    """The configured collection-name style, ``classic`` for a missing or unknown value."""
    style = settings.get(NAME_STYLE_SETTING, DEFAULT_NAME_STYLE)
    return style if style in NAME_STYLES else DEFAULT_NAME_STYLE


def _invalid(message: str) -> dict[str, Any]:
    return {"success": False, "reason": "invalid_record", "message": message}


@dataclass(frozen=True)
class SteamCollectionOwnershipServiceConfig:
    """Frozen wiring bundle handed to ``SteamCollectionOwnershipService.__init__``.

    Holds the SQLite Unit-of-Work factory (``owned_steam_collections`` and the
    ``kv_config`` adoption marker and platform-name cache, plus reads of ``roms`` and
    ``rom_installs`` for the installed and console-family collections), the live
    settings dict (the name
    style and the two collection toggles), and the debug logger.
    """

    uow_factory: UnitOfWorkFactory
    settings: dict[str, Any]
    log_debug: DebugLogger


class SteamCollectionOwnershipService:
    """Owns the record of the plugin's own Steam collections on this device."""

    def __init__(self, *, config: SteamCollectionOwnershipServiceConfig) -> None:
        self._uow_factory = config.uow_factory
        self._settings = config.settings
        self._log_debug = config.log_debug

    def get_owned_steam_collections(self) -> dict[str, Any]:
        """Every owned collection, the name style, whether the one-time adoption is done, and the platform renames.

        ``platform_renames`` maps a platform's RomM name to the name the plugin shows
        for it (``domain.platform_names.PLATFORM_NAME_OVERRIDES``), for the platforms
        in the last sync's name cache: a platform collection recorded under the RomM
        name moves its record to the shown name.
        """
        with self._uow_factory() as uow:
            records = [record.to_wire() for record in uow.owned_steam_collections.iter_all()]
            adoption_done = uow.kv_config.get(ADOPTION_DONE_KEY) == "1"
            renames = platform_renames(decode_romm_platform_names(uow.kv_config.get(_PLATFORM_NAMES_KEY)))
        return {
            "success": True,
            "name_style": name_style_of(self._settings),
            "adoption_done": adoption_done,
            "collections": records,
            "platform_renames": renames,
        }

    def get_installed_rom_app_ids(self) -> dict[str, Any]:
        """The Steam app ids of the shortcuts whose ROM content is installed on this device.

        A ROM counts when it has an install record (downloaded or adopted) and is
        bound to a shortcut; an installed sibling the shortcut is not bound to does
        not, because a version switch away from it leaves the shortcut launching an
        uninstalled version. ``enabled`` is the "Keep an Installed ROMs collection"
        setting, on unless switched off.
        """
        with self._uow_factory() as uow:
            installed = {install.rom_id for install in uow.rom_installs.iter_all()}
            app_ids = sorted(
                rom.shortcut_app_id
                for rom in uow.roms.iter_all()
                if rom.rom_id in installed and rom.shortcut_app_id is not None
            )
        return {
            "success": True,
            "enabled": bool(self._settings.get(INSTALLED_COLLECTION_SETTING, True)),
            "app_ids": app_ids,
        }

    def get_family_collection_games(self) -> dict[str, Any]:
        """Every ROM shortcut with its platform, for the console-family collections.

        One entry per ROM bound to a shortcut (``{app_id, platform_slug}``); the
        frontend groups them into PlayStation, Nintendo, Sega, Xbox and Retro with the
        same mapping as Core's Library tabs. ``enabled`` is the "Keep console family
        collections" setting, on unless switched off.
        """
        with self._uow_factory() as uow:
            games = sorted(
                (
                    {"app_id": rom.shortcut_app_id, "platform_slug": rom.platform_slug}
                    for rom in uow.roms.iter_all()
                    if rom.shortcut_app_id is not None
                ),
                key=lambda g: g["app_id"],
            )
        return {
            "success": True,
            "enabled": bool(self._settings.get(FAMILY_COLLECTIONS_SETTING, True)),
            "games": games,
        }

    def record_owned_steam_collection(
        self,
        collection_id: object,
        family: object,
        source_name: object,
        display_name: object,
        yielded_to: object,
    ) -> dict[str, Any]:
        """Record that *collection_id* is the plugin's collection for one source.

        Replaces any earlier record for the same family and source. Rejects a
        non-string or empty field, an unknown family, and a *yielded_to* that is
        neither a string nor ``None``.
        """
        fields = (collection_id, family, source_name, display_name)
        if not all(isinstance(value, str) for value in fields):
            return _invalid("collection_id, family, source_name and display_name must be strings")
        if yielded_to is not None and not isinstance(yielded_to, str):
            return _invalid("yielded_to must be a string or null")
        try:
            record = OwnedSteamCollection.claim(
                collection_id=str(collection_id),
                family=str(family),
                source_name=str(source_name),
                display_name=str(display_name),
                yielded_to=yielded_to,
            )
        except ValueError as exc:
            return _invalid(str(exc))
        with self._uow_factory() as uow:
            uow.owned_steam_collections.save(record)
        self._log_debug(
            f"Recorded owned Steam collection {record.collection_id} ({record.family}: {record.source_name})"
        )
        return {"success": True}

    def forget_owned_steam_collection(self, collection_id: object) -> dict[str, Any]:
        """Drop the record for *collection_id*; a no-op when there is none."""
        if not isinstance(collection_id, str) or not collection_id:
            return _invalid("collection_id must be a non-empty string")
        with self._uow_factory() as uow:
            uow.owned_steam_collections.delete(collection_id)
        self._log_debug(f"Forgot owned Steam collection {collection_id}")
        return {"success": True}

    def finish_steam_collection_adoption(self) -> dict[str, Any]:
        """Mark the one-time adoption of pre-record collections as done."""
        with self._uow_factory() as uow:
            uow.kv_config.set(ADOPTION_DONE_KEY, "1")
        return {"success": True}
