import { describe, it, expect } from "vitest";
import { consolePagePath, mediaKindFor } from "./consoleMedia";

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

describe("consolePagePath", () => {
  it("encodes the slug", () => {
    expect(consolePagePath("ps2")).toBe("/the-collector/console/ps2");
    expect(consolePagePath("a b/c")).toBe("/the-collector/console/a%20b%2Fc");
  });
});
