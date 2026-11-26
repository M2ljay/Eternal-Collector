"""OwnedSteamCollection — the record that a Steam collection was made by the plugin on this device.

Steam collections carry no owner, and a collection name proves nothing: the user can
make a collection called "PlayStation 2" just as the plugin can. This record is the
only ownership proof the plugin accepts. A collection without a record is the
user's, and the plugin never renames, refills or deletes it.

Identity is Steam's collection id. Each source — one platform or one synced RomM
collection, told apart by ``family`` and matched case-insensitively by
``source_key`` — has at most one owned collection, so recording a source against a
new collection id replaces the old record. ``display_name`` is the name the plugin
last gave the collection. ``yielded_to`` is set when the name the source wanted was
already taken by a collection of the user's: the name of that collection, kept so
the settings page can say why this one carries a suffix.

A thin record built whole and upserted, never mutated in place, so :meth:`claim` is
its one constructor and there are no mutators.
"""

from __future__ import annotations

from typing import Final, Literal

from domain._aggregate import cosmic_aggregate

CollectionFamily = Literal["platform", "romm"]
COLLECTION_FAMILIES: Final[tuple[str, ...]] = ("platform", "romm")

# kv_config key set once a completed sync has brought this device's pre-record
# collections under the record. Absent means the one-time adoption is still due.
ADOPTION_DONE_KEY: Final = "steam_collections_adopted"


@cosmic_aggregate
class OwnedSteamCollection:
    """One Steam collection the plugin made, keyed by Steam's collection id."""

    collection_id: str
    family: str
    source_name: str
    display_name: str
    yielded_to: str | None

    @property
    def source_key(self) -> str:
        """The case-insensitive identity of the source; Steam folds collection names by case."""
        return self.source_name.casefold()

    @classmethod
    def claim(
        cls,
        *,
        collection_id: str,
        family: str,
        source_name: str,
        display_name: str,
        yielded_to: str | None = None,
    ) -> OwnedSteamCollection:
        """Record that the collection *collection_id* is the plugin's collection for one source.

        Raises ``ValueError`` on an empty id, source or name, or an unknown family.
        An empty *yielded_to* is stored as ``None``.
        """
        if not collection_id:
            raise ValueError("an owned Steam collection needs its collection id")
        if family not in COLLECTION_FAMILIES:
            raise ValueError(f"family must be one of {COLLECTION_FAMILIES}, got {family!r}")
        if not source_name:
            raise ValueError("an owned Steam collection needs the source it was made for")
        if not display_name:
            raise ValueError("an owned Steam collection needs its display name")
        return cls(
            collection_id=collection_id,
            family=family,
            source_name=source_name,
            display_name=display_name,
            yielded_to=yielded_to or None,
        )

    def to_wire(self) -> dict[str, str | None]:
        """The JSON shape the frontend reads."""
        return {
            "collection_id": self.collection_id,
            "family": self.family,
            "source_name": self.source_name,
            "display_name": self.display_name,
            "yielded_to": self.yielded_to,
        }
