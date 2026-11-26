"""Contract tests for the Steam-collection ownership callables over the real nesting.

Driven frontend-shaped per ``src/api/backend.ts``: ``get_owned_steam_collections``
and ``finish_steam_collection_adoption`` take no argument;
``record_owned_steam_collection`` takes ``(collection_id, family, source_name,
display_name, yielded_to)`` with ``yielded_to`` a string or ``None``;
``forget_owned_steam_collection`` takes one id; ``set_collection_name_style`` takes
``"classic"`` or ``"clean"``. Failures use the canonical shape.
"""

from __future__ import annotations


async def test_empty_record_shape(harness):
    assert await harness.plugin.get_owned_steam_collections() == {
        "success": True,
        "name_style": "classic",
        "adoption_done": False,
        "collections": [],
    }


async def test_record_forget_and_adoption_round_trip_over_real_sqlite(harness):
    plugin = harness.plugin
    assert await plugin.record_owned_steam_collection("uc-1", "platform", "Nintendo 64", "Nintendo 64", None) == {
        "success": True
    }
    assert await plugin.record_owned_steam_collection("uc-2", "romm", "VR", "VR (RomM)", "VR") == {"success": True}
    assert await plugin.finish_steam_collection_adoption() == {"success": True}

    answer = await plugin.get_owned_steam_collections()

    assert answer["adoption_done"] is True
    assert answer["collections"] == [
        {
            "collection_id": "uc-1",
            "family": "platform",
            "source_name": "Nintendo 64",
            "display_name": "Nintendo 64",
            "yielded_to": None,
        },
        {
            "collection_id": "uc-2",
            "family": "romm",
            "source_name": "VR",
            "display_name": "VR (RomM)",
            "yielded_to": "VR",
        },
    ]

    assert await plugin.forget_owned_steam_collection("uc-2") == {"success": True}
    remaining = (await plugin.get_owned_steam_collections())["collections"]
    assert [r["collection_id"] for r in remaining] == ["uc-1"]


async def test_a_source_recorded_against_a_new_collection_replaces_the_old(harness):
    plugin = harness.plugin
    await plugin.record_owned_steam_collection("uc-old", "platform", "Nintendo 64", "RomM: Nintendo 64 (htpc)", None)
    await plugin.record_owned_steam_collection("uc-new", "platform", "nintendo 64", "Nintendo 64", None)

    remaining = (await plugin.get_owned_steam_collections())["collections"]
    assert [r["collection_id"] for r in remaining] == ["uc-new"]


async def test_bad_record_uses_the_canonical_failure_shape(harness):
    result = await harness.plugin.record_owned_steam_collection("uc-1", "shelf", "N64", "N64", None)

    assert set(result) == {"success", "reason", "message"}
    assert result["success"] is False
    assert result["reason"] == "invalid_record"
    assert (await harness.plugin.get_owned_steam_collections())["collections"] == []


async def test_bad_forget_uses_the_canonical_failure_shape(harness):
    result = await harness.plugin.forget_owned_steam_collection("")

    assert set(result) == {"success", "reason", "message"}
    assert result["success"] is False


async def test_name_style_persists_and_is_reported(harness):
    assert await harness.plugin.set_collection_name_style("clean") == {"success": True}
    assert harness.plugin.settings["collection_name_style"] == "clean"
    assert (await harness.plugin.get_settings())["collection_name_style"] == "clean"
    assert (await harness.plugin.get_owned_steam_collections())["name_style"] == "clean"


async def test_name_style_rejects_unknown_values(harness):
    result = await harness.plugin.set_collection_name_style("fancy")

    assert set(result) == {"success", "reason", "message"}
    assert result["reason"] == "invalid_style"
    assert harness.plugin.settings["collection_name_style"] == "classic"
