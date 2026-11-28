import { describe, it, expect, beforeEach, vi } from "vitest";
import * as backend from "../api/backend";
import {
  COLLECTOR_ACHIEVEMENTS_GLOBAL,
  COLLECTOR_ACHIEVEMENTS_READY_EVENT,
  SNAPSHOT_MAX_AGE_MS,
  clampLimit,
  createCollectorAchievementsBridge,
  installCollectorAchievementsBridge,
  publicBadgeUrl,
} from "./collectorAchievementsBridge";
import type { RaCompletionWire, RecentRaUnlockWire } from "../types/achievements";

const KEY = "AbCdEf0123456789AbCdEf0123456789";
const NOW = Date.parse("2026-11-27T12:00:00Z");
const FRESH = "2026-11-27T11:30:00Z";
const STALE = "2026-11-27T09:00:00Z";

function unlock(overrides: Partial<RecentRaUnlockWire> = {}): RecentRaUnlockWire {
  return {
    rom_id: 42,
    app_id: 3_000_000_001,
    game: "Sonic",
    platform: "Sega Genesis",
    title: "Ring Master",
    description: "Collect 100 rings",
    badge_url: "https://media.retroachievements.org/Badge/250336.png",
    unlocked_at: "2026-11-25T10:00:00Z",
    hardcore: true,
    ...overrides,
  };
}

function completion(overrides: Partial<RaCompletionWire> = {}): RaCompletionWire {
  return {
    rom_id: 42,
    app_id: 3_000_000_001,
    game: "Sonic",
    platform: "genesis",
    earned: 9,
    total: 10,
    percent: 90,
    ...overrides,
  };
}

const recent = () => vi.mocked(backend.getRecentRaUnlocks);
const closest = () => vi.mocked(backend.getClosestRaCompletions);
const refresh = () => vi.mocked(backend.refreshConsoleAchievements);

function bridge() {
  return createCollectorAchievementsBridge({ now: () => NOW });
}

beforeEach(() => {
  recent().mockReset();
  closest().mockReset();
  refresh().mockReset();
  refresh().mockResolvedValue({ success: true, refreshed_at: FRESH });
});

describe("clampLimit", () => {
  it.each([
    [1, 1],
    [10, 10],
    [50, 50],
    [0, 1],
    [-7, 1],
    [51, 50],
    [1e9, 50],
    [7.9, 7],
  ])("clamps %s to %s", (input, expected) => {
    expect(clampLimit(input)).toBe(expected);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, "5", null, undefined, {}, true])("refuses %s", (input) => {
    expect(clampLimit(input)).toBeNull();
  });
});

describe("publicBadgeUrl", () => {
  it("passes a plain media URL", () => {
    const url = "https://media.retroachievements.org/Badge/1.png";
    expect(publicBadgeUrl(url)).toBe(url);
  });

  it.each([
    "http://media.retroachievements.org/Badge/1.png",
    "https://retroachievements.org/Badge/1.png",
    "https://media.retroachievements.org.evil.example/Badge/1.png",
    `https://media.retroachievements.org/Badge/1.png?y=${KEY}`,
    "https://media.retroachievements.org/Badge/1.png#x",
    "https://u:p@media.retroachievements.org/Badge/1.png",
    "https://media.retroachievements.org:8443/Badge/1.png",
    "/Badge/1.png",
    "",
    null,
  ])("refuses %s", (url) => {
    expect(publicBadgeUrl(url)).toBeNull();
  });
});

describe("getRecentUnlocks", () => {
  it("answers the documented shape, camelCased", async () => {
    recent().mockResolvedValue({ success: true, items: [unlock(), unlock({ app_id: null, hardcore: false })] });
    const answer = await bridge().getRecentUnlocks(5);
    expect(answer).toEqual({
      ok: true,
      items: [
        {
          romId: 42,
          appId: 3_000_000_001,
          game: "Sonic",
          platform: "Sega Genesis",
          title: "Ring Master",
          description: "Collect 100 rings",
          badgeUrl: "https://media.retroachievements.org/Badge/250336.png",
          unlockedAt: "2026-11-25T10:00:00Z",
          hardcore: true,
        },
        expect.objectContaining({ appId: null, hardcore: false }),
      ],
    });
    expect(recent()).toHaveBeenCalledWith(5);
  });

  it("clamps the limit before calling the backend and never answers more", async () => {
    recent().mockResolvedValue({ success: true, items: [unlock(), unlock(), unlock()] });
    const b = bridge();
    await b.getRecentUnlocks(0);
    expect(recent()).toHaveBeenLastCalledWith(1);
    const answer = await b.getRecentUnlocks(-3);
    expect(answer.ok && answer.items).toHaveLength(1);
    await b.getRecentUnlocks(500);
    expect(recent()).toHaveBeenLastCalledWith(50);
  });

  it.each([Number.NaN, "5", undefined, null])(
    "answers bad_request for %s without calling the backend",
    async (limit) => {
      expect(await bridge().getRecentUnlocks(limit as unknown as number)).toEqual({ ok: false, reason: "bad_request" });
      expect(recent()).not.toHaveBeenCalled();
    },
  );

  it("answers not_configured without a Web API key", async () => {
    recent().mockResolvedValue({ success: false, reason: "no_web_api_key", message: "Add a key" });
    expect(await bridge().getRecentUnlocks(5)).toEqual({ ok: false, reason: "not_configured" });
  });

  it("drops a badge URL that is not a public media URL", async () => {
    recent().mockResolvedValue({
      success: true,
      items: [unlock({ badge_url: `https://media.retroachievements.org/Badge/1.png?y=${KEY}` })],
    });
    const answer = await bridge().getRecentUnlocks(5);
    expect(answer.ok && answer.items[0]?.badgeUrl).toBeNull();
    expect(JSON.stringify(answer)).not.toContain(KEY);
  });

  it("turns a backend failure into ok:false with the reason code only", async () => {
    recent().mockResolvedValue({ success: false, reason: "auth_failed", message: `refused ${KEY}` });
    const answer = await bridge().getRecentUnlocks(5);
    expect(answer).toEqual({ ok: false, reason: "auth_failed" });
    expect(JSON.stringify(answer)).not.toContain(KEY);
  });

  it("never passes an odd reason string through", async () => {
    recent().mockResolvedValue({ success: false, reason: `boom ${KEY}`, message: "" });
    expect(await bridge().getRecentUnlocks(5)).toEqual({ ok: false, reason: "backend_error" });
  });

  it("turns a rejected callable into bridge_error without its message", async () => {
    recent().mockRejectedValue(new Error(`socket closed ${KEY}`));
    const answer = await bridge().getRecentUnlocks(5);
    expect(answer).toEqual({ ok: false, reason: "bridge_error" });
    expect(JSON.stringify(answer)).not.toContain(KEY);
  });
});

describe("getClosestToComplete", () => {
  it("answers the documented shape from a fresh snapshot without refreshing", async () => {
    closest().mockResolvedValue({ success: true, fetched_at: FRESH, items: [completion()] });
    expect(await bridge().getClosestToComplete(10)).toEqual({
      ok: true,
      items: [
        { romId: 42, appId: 3_000_000_001, game: "Sonic", platform: "genesis", earned: 9, total: 10, percent: 90 },
      ],
    });
    expect(refresh()).not.toHaveBeenCalled();
    expect(closest()).toHaveBeenCalledWith(10);
  });

  it("refreshes a stale snapshot once, then re-reads", async () => {
    closest()
      .mockResolvedValueOnce({ success: true, fetched_at: STALE, items: [] })
      .mockResolvedValueOnce({ success: true, fetched_at: FRESH, items: [completion()] });
    const answer = await bridge().getClosestToComplete(3);
    expect(refresh()).toHaveBeenCalledTimes(1);
    expect(answer.ok && answer.items).toHaveLength(1);
  });

  it("tries a refresh at most once an hour, even when it fails", async () => {
    let clock = NOW;
    const b = createCollectorAchievementsBridge({ now: () => clock });
    refresh().mockRejectedValue(new Error("offline"));
    closest().mockResolvedValue({ success: true, fetched_at: STALE, items: [completion()] });
    expect((await b.getClosestToComplete(3)).ok).toBe(true);
    expect((await b.getClosestToComplete(3)).ok).toBe(true);
    expect(refresh()).toHaveBeenCalledTimes(1);
    clock += SNAPSHOT_MAX_AGE_MS + 1;
    await b.getClosestToComplete(3);
    expect(refresh()).toHaveBeenCalledTimes(2);
  });

  it("answers not_configured when there is still no snapshot after the refresh", async () => {
    closest().mockResolvedValue({ success: false, reason: "no_snapshot", message: "not read yet" });
    refresh().mockResolvedValue({ success: false, reason: "server_unreachable", message: "down" });
    expect(await bridge().getClosestToComplete(5)).toEqual({ ok: false, reason: "not_configured" });
    expect(refresh()).toHaveBeenCalledTimes(1);
  });

  it("clamps, and refuses bad input", async () => {
    closest().mockResolvedValue({ success: true, fetched_at: FRESH, items: [] });
    await bridge().getClosestToComplete(99);
    expect(closest()).toHaveBeenLastCalledWith(50);
    expect(await bridge().getClosestToComplete("3" as unknown as number)).toEqual({ ok: false, reason: "bad_request" });
  });

  it("turns a backend failure or a rejection into ok:false", async () => {
    closest().mockResolvedValue({ success: false, reason: "invalid_argument", message: "x" });
    expect(await bridge().getClosestToComplete(5)).toEqual({ ok: false, reason: "bad_request" });
    closest().mockRejectedValue(new Error(KEY));
    const answer = await bridge().getClosestToComplete(5);
    expect(answer).toEqual({ ok: false, reason: "bridge_error" });
    expect(JSON.stringify(answer)).not.toContain(KEY);
  });
});

describe("installCollectorAchievementsBridge", () => {
  it("publishes a frozen bridge, announces it, and withdraws only itself", () => {
    const g = globalThis as unknown as Record<string, unknown>;
    const ready = vi.fn();
    globalThis.addEventListener(COLLECTOR_ACHIEVEMENTS_READY_EVENT, ready);
    const uninstall = installCollectorAchievementsBridge();
    const published = g[COLLECTOR_ACHIEVEMENTS_GLOBAL] as { version: number };
    expect(published.version).toBe(1);
    expect(Object.isFrozen(published)).toBe(true);
    expect(ready).toHaveBeenCalledTimes(1);

    const other = { version: 2 };
    g[COLLECTOR_ACHIEVEMENTS_GLOBAL] = other;
    uninstall();
    expect(g[COLLECTOR_ACHIEVEMENTS_GLOBAL]).toBe(other);
    delete g[COLLECTOR_ACHIEVEMENTS_GLOBAL];

    const again = installCollectorAchievementsBridge();
    again();
    expect(g[COLLECTOR_ACHIEVEMENTS_GLOBAL]).toBeUndefined();
    globalThis.removeEventListener(COLLECTOR_ACHIEVEMENTS_READY_EVENT, ready);
  });

  it("never throws from a wrapper, whatever the backend does", async () => {
    recent().mockImplementation(() => {
      throw new Error("sync throw");
    });
    closest().mockImplementation(() => {
      throw new Error("sync throw");
    });
    const b = bridge();
    await expect(b.getRecentUnlocks(5)).resolves.toEqual({ ok: false, reason: "bridge_error" });
    await expect(b.getClosestToComplete(5)).resolves.toEqual({ ok: false, reason: "bridge_error" });
  });
});
