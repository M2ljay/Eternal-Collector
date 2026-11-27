/**
 * The Core palette: the one source of colour for every surface this plugin draws.
 *
 * Crimson is the single accent — the selected or focused item, active toggles and
 * progress — and also the colour of a problem (error, conflict, failure). Status
 * colours are muted so they sit with black and gunmetal: green for done, amber
 * for pending or partial, steel for unknown. Gold is not part of the palette.
 *
 * Contrast: `crimson` measures 4.2:1 on black and 3.4:1 on gunmetal, below the
 * 4.5:1 that body text needs, so crimson reaches text only as `crimsonText`
 * (6.2:1 on black, 5.0:1 on gunmetal). `crimson` itself is for bars, dots,
 * borders, underlines and fills. Text on a green or amber fill is `black`.
 */
export const core = {
  black: "#000000",
  gunmetal: "#1A1D21",
  gunmetalRaised: "#2A2F36",
  steel: "#C9D1D9",
  hint: "#9AA4AE",
  white: "#FFFFFF",
  text: "#E6EAEE",
  crimson: "#D7263D",
  crimsonText: "#EA5A68",
  success: "#6FA37F",
  warning: "#C98B4A",
  neutral: "#C9D1D9",
} as const;

export type CoreColor = (typeof core)[keyof typeof core];

/** `rgba()` of a palette colour, for tinted fills and translucent glass. */
export function tint(color: CoreColor, alpha: number): string {
  const r = Number.parseInt(color.slice(1, 3), 16);
  const g = Number.parseInt(color.slice(3, 5), 16);
  const b = Number.parseInt(color.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Console-family tones, as Core UI paints the Library's tabs and tiles (Core's
 * `CORE_FAMILY_TONES`). A platform chip is filled with its family's tone and
 * carries black text; a platform outside the four families is "retro".
 */
export const familyTones = {
  playstation: "#6E8CB8",
  nintendo: "#B07A84",
  sega: "#5E9E9A",
  xbox: "#7FA36B",
  retro: "#8F7CB0",
} as const;

export type ConsoleFamily = keyof typeof familyTones;

const FAMILY_SLUGS: Record<Exclude<ConsoleFamily, "retro">, readonly string[]> = {
  playstation: ["psx", "ps", "ps2", "ps3", "ps4", "ps5", "psp", "psvita"],
  nintendo: [
    "nes",
    "famicom",
    "fds",
    "snes",
    "sfam",
    "n64",
    "gb",
    "gbc",
    "gba",
    "nds",
    "nintendo-dsi",
    "3ds",
    "n3ds",
    "ngc",
    "wii",
    "wiiu",
    "switch",
    "virtualboy",
    "pokemon-mini",
    "satellaview",
    "sufami-turbo",
    "64dd",
  ],
  sega: [
    "genesis",
    "genesis-slash-megadrive",
    "megadrive",
    "sms",
    "gamegear",
    "sega32",
    "segacd",
    "saturn",
    "dc",
    "sg1000",
    "sega-pico",
    "naomi",
  ],
  xbox: ["xbox", "xbox360", "xboxone"],
};

/** The console family a RomM platform slug belongs to. */
export function consoleFamily(platformSlug: string): ConsoleFamily {
  const slug = platformSlug.toLowerCase();
  for (const [family, slugs] of Object.entries(FAMILY_SLUGS) as [ConsoleFamily, readonly string[]][]) {
    if (slugs.includes(slug)) return family;
  }
  return "retro";
}
