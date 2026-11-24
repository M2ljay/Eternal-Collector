import { describe, it, expect, vi, afterEach } from "vitest";
import { retroDeckBanner } from "./retrodeckHealth";

const PATHS = { config_path: "/cfg/retrodeck.json", resolved_home: "/sd/retrodeck" };

describe("retroDeckBanner", () => {
  it("returns null for 'ok' (healthy — stays quiet)", () => {
    expect(retroDeckBanner("ok", PATHS)).toBeNull();
  });

  it("returns null for 'absent' (fresh-install fallback — stays quiet)", () => {
    expect(retroDeckBanner("absent", PATHS)).toBeNull();
  });

  it("returns the unreadable banner with the probed config path", () => {
    const banner = retroDeckBanner("unreadable", PATHS);
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("RetroDECK configuration unreadable");
    expect(banner!.message).toContain("syncs and downloads may target the wrong location");
    expect(banner!.message).toContain("/cfg/retrodeck.json");
  });

  it("returns the root-missing banner with the resolved home path", () => {
    const banner = retroDeckBanner("root_missing", PATHS);
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("RetroDECK library not found");
    expect(banner!.message).toContain("make sure the card is inserted");
    expect(banner!.message).toContain("/sd/retrodeck");
  });
});

describe("retroDeckBanner — launcher name on Windows", () => {
  const WINDOWS_UA =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Valve Steam Client";

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each(["unreadable", "root_missing"] as const)("names EmuDeck, never RetroDECK, in the %s banner", (status) => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    const banner = retroDeckBanner(status, PATHS);
    expect(banner).not.toBeNull();
    expect(banner!.title.startsWith("EmuDeck ")).toBe(true);
    expect(banner!.message).toContain("EmuDeck");
    expect(`${banner!.title} ${banner!.message}`).not.toContain("RetroDECK");
  });

  it("stays quiet on Windows for 'ok' and 'absent'", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    expect(retroDeckBanner("ok", PATHS)).toBeNull();
    expect(retroDeckBanner("absent", PATHS)).toBeNull();
  });
});
