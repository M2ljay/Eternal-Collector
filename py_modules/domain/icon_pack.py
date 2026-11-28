"""The ColorGrade icon pack's layout: console families and platforms, as relative file paths.

The pack is personal art the user keeps on their own PC, under
``%APPDATA%\\GamingMode\\icons\\colorgrade`` (shared with Core). It is never copied
into the plugin: the plugin only reads it, and a missing folder or file is an
ordinary answer ("no art"), not an error.

Layout::

    families/<family>/{icon,hero,logo}.png    family in FAMILIES
    platforms/<pack slug>/{icon,hero,logo}.png

Only names from the allow-lists below ever become a path part, so nothing the
frontend sends can name a file outside the pack.
"""

from __future__ import annotations

PACK_ROOT_PARTS: tuple[str, ...] = ("GamingMode", "icons", "colorgrade")

FAMILIES: tuple[str, ...] = ("playstation", "nintendo", "sega", "xbox", "retro")
ART_KINDS: tuple[str, ...] = ("icon", "hero", "logo")


def family_art_parts(family: object, kind: object) -> tuple[str, str, str] | None:
    """The pack-relative path of one family's art, or ``None`` for a name outside the allow-lists."""
    if family not in FAMILIES or kind not in ART_KINDS:
        return None
    return ("families", str(family), f"{kind}.png")


# RomM platform slug -> the pack's folder name, where they differ. The pack's
# names (ColorGrade v1.1, 83 platforms) follow EmulationStation's; RomM's follow
# IGDB's. A RomM slug equal to a pack name needs no entry.
_PACK_SLUG_FOR: dict[str, str] = {
    "ngc": "gc",
    "nintendo-dsi": "ndsi",
    "3ds": "n3ds",
    "new-nintendo-3ds": "n3ds",
    "g-and-w": "gameandwatch",
    "pokemon-mini": "pokemini",
    "genesis-slash-megadrive": "genesis",
    "megadrive": "genesis",
    "sms": "mastersystem",
    "sega32": "sega32x",
    "dc": "dreamcast",
    "sg1000": "sg-1000",
    "sega-pico": "pico",
    "ps": "psx",
    "neogeoaes": "neogeo",
    "neogeomvs": "neogeo",
    "neo-geo-cd": "neogeocd",
    "neo-geo-pocket": "ngp",
    "neo-geo-pocket-color": "ngpc",
    "turbografx-cd": "tg-cd",
    "turbografx16--1": "tg16",
    "pc-engine-supergrafx": "supergrafx",
    "pc-fx": "pcfx",
    "arcade": "mame",
    "jaguar": "atarijaguar",
    "atari-jaguar-cd": "atarijaguarcd",
    "lynx": "atarilynx",
    "atari-st": "atarist",
    "acpc": "amstradcpc",
    "zxs": "zxspectrum",
    "philips-cd-i": "cdimono1",
    "wonderswan-color": "wonderswancolor",
    "win": "windows",
    "pico-8": "pico8",
    "watara-slash-quickshot-supervision": "supervision",
    "vic-20": "vic20",
    "commodore-plus-4": "plus4",
    "pc-8800-series": "pc88",
    "pc-9800-series": "pc98",
}

PACK_PLATFORMS: frozenset[str] = frozenset(
    {
        "3do",
        "amiga",
        "amstradcpc",
        "arduboy",
        "atari2600",
        "atari5200",
        "atari7800",
        "atarijaguar",
        "atarijaguarcd",
        "atarilynx",
        "atarist",
        "atomiswave",
        "c64",
        "cdimono1",
        "cps1",
        "cps2",
        "cps3",
        "dreamcast",
        "fbneo",
        "fds",
        "gameandwatch",
        "gamegear",
        "gb",
        "gba",
        "gbc",
        "gc",
        "genesis",
        "genesismsu",
        "mame",
        "mastersystem",
        "megaduck",
        "msx",
        "n3ds",
        "n64",
        "naomi",
        "nds",
        "ndsi",
        "neogeo",
        "neogeocd",
        "nes",
        "ngage",
        "ngp",
        "ngpc",
        "pc60",
        "pc88",
        "pc98",
        "pcfx",
        "pet",
        "pico",
        "pico8",
        "plus4",
        "pokemini",
        "ps2",
        "ps3",
        "psp",
        "pspminis",
        "psvita",
        "psx",
        "rpgmaker",
        "satellaview",
        "saturn",
        "scummvm",
        "sega32x",
        "segacd",
        "sg-1000",
        "snes",
        "snesmsu1",
        "steam",
        "supergrafx",
        "supervision",
        "switch",
        "tg-cd",
        "tg16",
        "vic20",
        "virtualboy",
        "wii",
        "wiiu",
        "wiiware",
        "windows",
        "wonderswan",
        "wonderswancolor",
        "xbox",
        "zxspectrum",
    }
)


def pack_platform_slug(romm_slug: object) -> str | None:
    """The pack folder for a RomM platform slug, or ``None`` when the pack has none (no PS4, no Xbox 360)."""
    if not isinstance(romm_slug, str):
        return None
    slug = romm_slug.strip().lower()
    pack = _PACK_SLUG_FOR.get(slug, slug)
    return pack if pack in PACK_PLATFORMS else None


def platform_art_parts(romm_slug: object, kind: object) -> tuple[str, str, str] | None:
    """The pack-relative path of one platform's art, or ``None`` when the pack has no folder for it."""
    pack = pack_platform_slug(romm_slug)
    if pack is None or kind not in ART_KINDS:
        return None
    return ("platforms", pack, f"{kind}.png")
