import { describe, expect, it } from "vitest";
import { core, tint } from "./coreTokens";

function linear(hex: string, offset: number): number {
  const c = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  return 0.2126 * linear(hex, 1) + 0.7152 * linear(hex, 3) + 0.0722 * linear(hex, 5);
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

describe("core palette", () => {
  it.each([
    ["white", core.white],
    ["text", core.text],
    ["steel", core.steel],
    ["hint", core.hint],
    ["crimsonText", core.crimsonText],
    ["success", core.success],
    ["warning", core.warning],
  ])("%s text reads at 4.5:1 or better on black and on gunmetal", (_name, color) => {
    expect(contrast(color, core.black)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(color, core.gunmetal)).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps crimson itself off body text: it falls short of 4.5:1 on gunmetal", () => {
    expect(contrast(core.crimson, core.gunmetal)).toBeLessThan(4.5);
  });

  it("white on a crimson fill reads at 4.5:1 or better", () => {
    expect(contrast(core.white, core.crimson)).toBeGreaterThanOrEqual(4.5);
  });

  it("black on a green or amber fill reads at 4.5:1 or better", () => {
    expect(contrast(core.black, core.success)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(core.black, core.warning)).toBeGreaterThanOrEqual(4.5);
  });

  it("tint renders a palette colour as rgba with the given alpha", () => {
    expect(tint(core.crimson, 0.15)).toBe("rgba(215, 38, 61, 0.15)");
  });

  it("holds no gold", () => {
    const values = Object.values(core).map((v) => v.toLowerCase());
    for (const gold of ["#d4a72c", "#d9a337", "#ffc83c", "#ffd700"]) expect(values).not.toContain(gold);
  });
});
