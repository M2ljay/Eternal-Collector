import { describe, it, expect } from "vitest";
import { biosColorForLevel } from "./biosColor";
import { core } from "../theme/coreTokens";

describe("biosColorForLevel", () => {
  it("maps 'ok' to green", () => {
    expect(biosColorForLevel("ok")).toBe(core.success);
  });

  it("maps 'partial' to amber", () => {
    expect(biosColorForLevel("partial")).toBe(core.warning);
  });

  it("maps 'missing' to crimson", () => {
    expect(biosColorForLevel("missing")).toBe(core.crimson);
  });

  it("maps 'unmanaged' (no registry coverage) to neutral", () => {
    expect(biosColorForLevel("unmanaged")).toBe(core.neutral);
  });

  it("maps null (no level data) to neutral", () => {
    expect(biosColorForLevel(null)).toBe(core.neutral);
  });
});
