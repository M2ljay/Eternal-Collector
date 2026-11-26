import { describe, it, expect } from "vitest";
import { consolePagePath, mediaKindFor, stackSize } from "./consoleMedia";

describe("mediaKindFor", () => {
  it.each([
    ["ps2", "dvd-case"],
    ["ngc", "gc-box"],
    ["psx", "jewel-case"],
    ["snes", "snes-cart"],
    ["n64", "n64-cart"],
    ["gba", "small-cart"],
    ["psp", "umd"],
    ["PS2", "dvd-case"],
    ["some-new-platform", "keep-case"],
  ])("%s draws as %s", (slug, kind) => {
    expect(mediaKindFor(slug)).toBe(kind);
  });
});

describe("stackSize", () => {
  it("follows the game count up to the media's limit, never below one", () => {
    expect(stackSize("dvd-case", 14)).toBe(6);
    expect(stackSize("jewel-case", 14)).toBe(4);
    expect(stackSize("snes-cart", 2)).toBe(2);
    expect(stackSize("n64-cart", 0)).toBe(1);
  });
});

describe("consolePagePath", () => {
  it("encodes the slug", () => {
    expect(consolePagePath("ps2")).toBe("/the-collector/console/ps2");
    expect(consolePagePath("a b/c")).toBe("/the-collector/console/a%20b%2Fc");
  });
});
