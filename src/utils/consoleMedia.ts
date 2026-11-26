/**
 * Which physical media a console's games came on, keyed by RomM platform slug.
 *
 * The Collector draws every console as a stack of its media in CSS — generic
 * shapes, no logos — and lays a console page out in the same style. An unknown
 * slug gets the generic keep case, so a platform added to RomM later still has
 * a sensible look without a code change.
 */

export type MediaKind =
  | "dvd-case" // PS2 / Xbox: tall keep cases, shown spine-out
  | "gc-box" // GameCube: smaller, squarer keep cases
  | "jewel-case" // CD consoles: square jewel cases
  | "snes-cart" // SNES / Super Famicom: wide grey cartridges
  | "n64-cart" // Nintendo 64: dark cartridges with a rounded top
  | "nes-cart" // NES / Famicom / Mega Drive era: upright cartridges
  | "small-cart" // handhelds: small cartridges
  | "umd" // PSP: UMD discs in their small case
  | "keep-case"; // anything else

const MEDIA_BY_SLUG: Readonly<Record<string, MediaKind>> = {
  ps2: "dvd-case",
  xbox: "dvd-case",
  ps3: "dvd-case",
  wii: "dvd-case",
  ngc: "gc-box",
  gamecube: "gc-box",
  psx: "jewel-case",
  ps: "jewel-case",
  saturn: "jewel-case",
  segacd: "jewel-case",
  dc: "jewel-case",
  dreamcast: "jewel-case",
  "pc-fx": "jewel-case",
  "turbografx-cd": "jewel-case",
  "3do": "jewel-case",
  snes: "snes-cart",
  sfam: "snes-cart",
  n64: "n64-cart",
  nes: "nes-cart",
  famicom: "nes-cart",
  genesis: "nes-cart",
  "genesis-slash-megadrive": "nes-cart",
  megadrive: "nes-cart",
  sms: "nes-cart",
  atari2600: "nes-cart",
  gb: "small-cart",
  gbc: "small-cart",
  gba: "small-cart",
  nds: "small-cart",
  "3ds": "small-cart",
  n3ds: "small-cart",
  gamegear: "small-cart",
  "game-gear": "small-cart",
  lynx: "small-cart",
  ngp: "small-cart",
  ngpc: "small-cart",
  wonderswan: "small-cart",
  "wonderswan-color": "small-cart",
  psp: "umd",
};

export function mediaKindFor(platformSlug: string): MediaKind {
  return MEDIA_BY_SLUG[platformSlug.toLowerCase()] ?? "keep-case";
}

/** How many pieces of media a Home tile stacks for a console with `gameCount` games. */
export function stackSize(kind: MediaKind, gameCount: number): number {
  const most = kind === "dvd-case" || kind === "keep-case" ? 6 : 4;
  return Math.max(1, Math.min(most, gameCount));
}

/** Path of the console page route for one console. */
export const CONSOLE_PAGE_ROUTE = "/the-collector/console/:slug";

export function consolePagePath(platformSlug: string): string {
  return `/the-collector/console/${encodeURIComponent(platformSlug)}`;
}
