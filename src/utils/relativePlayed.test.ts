import { describe, it, expect } from "vitest";
import { relativePlayed } from "./relativePlayed";

// Local times, so the wording is checked against the viewer's own clock.
const at = (y: number, m: number, d: number, h: number, min = 0) => new Date(y, m - 1, d, h, min);
const NOW = at(2026, 11, 26, 21, 0);

describe("relativePlayed", () => {
  it.each([null, undefined, "", "not a date"])("%s reads not played yet", (value) => {
    expect(relativePlayed(value, NOW)).toBe("Not played yet");
  });

  it("evening play on the same day reads tonight", () => {
    expect(relativePlayed(at(2026, 11, 26, 19).toISOString(), NOW)).toBe("Played tonight");
  });

  it("daytime play on the same day reads today", () => {
    expect(relativePlayed(at(2026, 11, 26, 11).toISOString(), NOW)).toBe("Played today");
  });

  it("a session past midnight still reads tonight before 05:00", () => {
    expect(relativePlayed(at(2026, 11, 27, 2).toISOString(), at(2026, 11, 27, 3))).toBe("Played tonight");
    expect(relativePlayed(at(2026, 11, 26, 23).toISOString(), at(2026, 11, 27, 3))).toBe("Played tonight");
  });

  it.each([
    [at(2026, 11, 25, 20), "Played yesterday"],
    [at(2026, 11, 23, 12), "Played 3 days ago"],
    [at(2026, 11, 17, 12), "Played last week"],
    [at(2026, 11, 5, 12), "Played 3 weeks ago"],
    [at(2026, 8, 20, 12), "Played 3 months ago"],
    [at(2025, 11, 1, 12), "Played 1 year ago"],
    [at(2023, 1, 1, 12), "Played 3 years ago"],
  ])("%s → %s", (played, text) => {
    expect(relativePlayed(played.toISOString(), NOW)).toBe(text);
  });
});
