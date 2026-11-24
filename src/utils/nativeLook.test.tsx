import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { joinCls, nativeLook, pressOnce, rc } from "./nativeLook";

// Steam's class maps resolve through a webpack probe at runtime; pin them to
// known names so the mapping is observable. Mutable so a test can drop one.
const classes = vi.hoisted(() => ({
  playSection: {
    GameStat: "steam-gamestat",
    PlayBarLabel: "steam-playbarlabel",
    PlayBarDetailLabel: "steam-playbardetaillabel",
  } as Record<string, string | undefined>,
}));

vi.mock("./deckyUiInternals", () => ({
  playSectionClasses: classes.playSection,
  appActionButtonClasses: {},
  findSP: () => undefined,
}));

const WINDOWS_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Valve Steam Client";
const DECK_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Valve Steam Client";

function stubUserAgent(ua: string): void {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  classes.playSection.GameStat = "steam-gamestat";
});

describe("nativeLook", () => {
  it("is on for a Windows Steam client", () => {
    stubUserAgent(WINDOWS_UA);
    expect(nativeLook()).toBe(true);
  });

  it("is off for the Steam Deck's Linux client", () => {
    stubUserAgent(DECK_UA);
    expect(nativeLook()).toBe(false);
  });
});

describe("joinCls", () => {
  it("joins the truthy parts with single spaces", () => {
    expect(joinCls("a", false, "b", null, undefined, "", "c")).toBe("a b c");
  });

  it("is empty when every part is falsy", () => {
    expect(joinCls(false, null, undefined, "")).toBe("");
  });
});

describe("rc", () => {
  it("returns the RomM classes unchanged off Windows", () => {
    stubUserAgent(DECK_UA);
    expect(rc("romm-info-item romm-extra")).toBe("romm-info-item romm-extra");
  });

  it.each([
    ["romm-info-item", "steam-gamestat"],
    ["romm-info-header", "steam-playbarlabel"],
    ["romm-info-value", "steam-playbardetaillabel"],
  ])("replaces %s with Steam's class and keeps the rest on Windows", (romm, steam) => {
    stubUserAgent(WINDOWS_UA);
    expect(rc(`${romm} romm-extra other`)).toBe(`${steam} romm-extra other`);
  });

  it("leaves a class with no Steam equivalent untouched on Windows", () => {
    stubUserAgent(WINDOWS_UA);
    expect(rc("romm-something-else romm-extra")).toBe("romm-something-else romm-extra");
  });

  it("falls back to the RomM classes when Steam's class map lacks the entry", () => {
    stubUserAgent(WINDOWS_UA);
    classes.playSection.GameStat = undefined;
    expect(rc("romm-info-item romm-extra")).toBe("romm-info-item romm-extra");
  });
});

describe("pressOnce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });

  it("runs the first press, drops a repeat inside 500ms, and runs again after", () => {
    const fn = vi.fn((x: number) => x * 2);
    const press = pressOnce(fn, {});

    expect(press(1)).toBe(2);
    vi.advanceTimersByTime(499);
    expect(press(2)).toBeUndefined();
    expect(fn).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1);
    expect(press(3)).toBe(6);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(fn).toHaveBeenLastCalledWith(3);
  });

  it("debounces two wrappers that share a key as one press (onClick + onActivate)", () => {
    const fn = vi.fn();
    const key = {};
    const viaClick = pressOnce(fn, key);
    const viaActivate = pressOnce(fn, key);

    viaClick();
    viaActivate();

    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("keeps presses under different keys independent", () => {
    const fn = vi.fn();
    pressOnce(fn, {})();
    pressOnce(fn, {})();
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("keys on the function itself when no key is given", () => {
    const fn = vi.fn();
    pressOnce(fn, null)();
    pressOnce(fn, undefined)();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("is a no-op returning undefined with neither a function nor a key", () => {
    const press = pressOnce(undefined, null);
    expect(press()).toBeUndefined();
    expect(press()).toBeUndefined();
  });
});
