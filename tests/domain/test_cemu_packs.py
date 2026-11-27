"""Tests for domain.cemu_packs — rules.txt definitions and settings.xml GraphicPack entries."""

from __future__ import annotations

import pytest

from domain.cemu_packs import cemu_packs, cemu_set_pack, pack_entries, pack_info

_RULES = '[Definition]\ntitleIds = 00050000101C9300,00050000101c9400\nname = "Resolution"\nversion = 7\n'
_SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8"?>\r\n'
    "<content>\r\n"
    "    <GraphicPack>\r\n"
    '        <Entry filename="graphicPacks\\BotW_Res\\rules.txt">\r\n'
    "            <Preset>\r\n"
    "                <category>Resolution</category>\r\n"
    "                <preset>1440p</preset>\r\n"
    "            </Preset>\r\n"
    "        </Entry>\r\n"
    '        <Entry filename="graphicPacks\\BotW_FPS\\rules.txt" disabled="true"/>\r\n'
    "    </GraphicPack>\r\n"
    "</content>\r\n"
)


def test_pack_info():
    info = pack_info(_RULES)
    assert info is not None
    assert info.title_ids == {"00050000101C9300", "00050000101C9400"}
    assert info.name == "Resolution"
    assert info.default_enabled is False
    assert pack_info("[Definition]\nname = x\n") is None
    assert pack_info("[Definition]\ntitleIds = 00050000101C9400\ndefault = true\n").default_enabled is True


def test_entries_and_state():
    assert pack_entries(_SETTINGS) == {
        "graphicpacks\\botw_res\\rules.txt": False,
        "graphicpacks\\botw_fps\\rules.txt": True,
    }
    info = pack_info(_RULES)
    packs = [
        ("graphicPacks\\BotW_Res\\rules.txt", info),
        ("graphicPacks\\BotW_FPS\\rules.txt", info),
        ("graphicPacks\\BotW_New\\rules.txt", info),
    ]
    listing = cemu_packs(packs, _SETTINGS, "00050000101C9400", settings_file="settings.xml")
    assert [(e.entry_id, e.enabled) for e in listing.entries] == [
        ("graphicPacks\\BotW_FPS\\rules.txt", False),
        ("graphicPacks\\BotW_New\\rules.txt", False),
        ("graphicPacks\\BotW_Res\\rules.txt", True),
    ]
    assert cemu_packs(packs, _SETTINGS, "0005000000000000", settings_file="s").entries == ()


def test_enable_a_disabled_entry_and_disable_one_with_presets():
    on = cemu_set_pack(_SETTINGS, "graphicPacks\\BotW_FPS\\rules.txt", True, False)
    assert on is not None and '<Entry filename="graphicPacks\\BotW_FPS\\rules.txt"/>\r\n' in on
    off = cemu_set_pack(_SETTINGS, "graphicPacks/botw_res/rules.txt", False, False)
    assert off is not None and '<Entry filename="graphicPacks\\BotW_Res\\rules.txt" disabled="true">\r\n' in off
    assert "<preset>1440p</preset>" in off


def test_a_new_entry_goes_before_the_closing_tag():
    out = cemu_set_pack(_SETTINGS, "graphicPacks/New Pack & Co/rules.txt", True, False)
    assert out is not None
    assert '        <Entry filename="graphicPacks\\New Pack &amp; Co\\rules.txt"/>\r\n    </GraphicPack>' in out


def test_default_on_pack_is_disabled_with_an_entry():
    out = cemu_set_pack(_SETTINGS, "graphicPacks\\Default\\rules.txt", False, True)
    assert out is not None and 'filename="graphicPacks\\Default\\rules.txt" disabled="true"/>' in out
    assert cemu_set_pack(_SETTINGS, "graphicPacks\\Default\\rules.txt", True, True) == _SETTINGS


def test_self_closing_graphic_pack_element_is_opened():
    text = "<content>\n    <GraphicPack/>\n</content>\n"
    out = cemu_set_pack(text, "graphicPacks\\A\\rules.txt", True, False)
    assert out == (
        '<content>\n    <GraphicPack>\n        <Entry filename="graphicPacks\\A\\rules.txt"/>\n'
        "    </GraphicPack>\n</content>\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "<content><GraphicPack>\n<Entry><filename>x</filename></Entry>\n</GraphicPack></content>\n",
        "<content>\n<GraphicPack>\n</GraphicPack>\n<GraphicPack>\n</GraphicPack>\n</content>\n",
        '<content>\n<GraphicPack>\n<Entry filename="a" foo="b"/>\n</GraphicPack>\n</content>\n',
    ],
)
def test_layouts_not_edited_here_are_read_only(text):
    assert pack_entries(text) is None
    assert cemu_set_pack(text, "graphicPacks\\A\\rules.txt", True, False) is None
    info = pack_info(_RULES)
    listing = cemu_packs([("graphicPacks\\A\\rules.txt", info)], text, "00050000101C9400", settings_file="s")
    assert listing.editable is False
