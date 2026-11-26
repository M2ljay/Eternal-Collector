import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { emitDeckyEvent, deckyEventListenerCount } from "../test-utils/decky-api-mock";
import { getConsoleShelf, logWarn } from "../api/backend";
import {
  getConsoleShelfState,
  refreshConsoleShelf,
  resetConsoleShelfStore,
  setHomeShelfEnabled,
  startConsoleShelfStore,
  useConsoleShelf,
} from "./consoleShelfStore";
import type { ConsoleShelfAnswer, ShelfConsole } from "../types";

vi.mock("../api/backend", () => ({
  getConsoleShelf: vi.fn(),
  logWarn: vi.fn(),
}));

const ps2: ShelfConsole = {
  platform_slug: "ps2",
  name: "PlayStation 2",
  game_count: 14,
  last_played: "2026-11-26T20:00:00Z",
  play_seconds: 3600,
};

function answer(consoles: ShelfConsole[], enabled = true): ConsoleShelfAnswer {
  return { success: true, enabled, consoles };
}

beforeEach(() => {
  resetConsoleShelfStore();
  vi.mocked(getConsoleShelf).mockReset();
  vi.mocked(logWarn).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("consoleShelfStore", () => {
  it("starts idle and becomes ready with the backend's answer", async () => {
    expect(getConsoleShelfState()).toEqual({ status: "idle", enabled: true, consoles: [] });
    vi.mocked(getConsoleShelf).mockResolvedValue(answer([ps2], false));
    await refreshConsoleShelf();
    expect(getConsoleShelfState()).toEqual({ status: "ready", enabled: false, consoles: [ps2] });
  });

  it("drops an answer older than one already applied", async () => {
    let releaseSlow: (v: ConsoleShelfAnswer) => void = () => {};
    vi.mocked(getConsoleShelf)
      .mockImplementationOnce(() => new Promise((resolve) => (releaseSlow = resolve)))
      .mockResolvedValueOnce(answer([ps2]));
    const slow = refreshConsoleShelf();
    await refreshConsoleShelf();
    releaseSlow(answer([]));
    await slow;
    expect(getConsoleShelfState().consoles).toEqual([ps2]);
  });

  it("a failed first read leaves an error state and logs it", async () => {
    vi.mocked(getConsoleShelf).mockRejectedValue(new Error("bridge down"));
    await refreshConsoleShelf();
    expect(getConsoleShelfState().status).toBe("error");
    expect(logWarn).toHaveBeenCalledWith("The Collector: console shelf read failed: bridge down");
  });

  it("a failed later read keeps what is shown", async () => {
    vi.mocked(getConsoleShelf)
      .mockResolvedValueOnce(answer([ps2]))
      .mockRejectedValueOnce("nope");
    await refreshConsoleShelf();
    await refreshConsoleShelf();
    expect(getConsoleShelfState()).toEqual({ status: "ready", enabled: true, consoles: [ps2] });
    expect(logWarn).toHaveBeenCalledWith("The Collector: console shelf read failed: nope");
  });

  it("setHomeShelfEnabled publishes to subscribers", () => {
    const { result } = renderHook(() => useConsoleShelf());
    act(() => setHomeShelfEnabled(false));
    expect(result.current.enabled).toBe(false);
  });

  it("start reads once, re-reads after sync end / save status / playtime signals, and stop removes every listener", async () => {
    vi.useFakeTimers();
    vi.mocked(getConsoleShelf).mockResolvedValue(answer([ps2]));
    const stop = startConsoleShelfStore();
    expect(getConsoleShelf).toHaveBeenCalledTimes(1);
    expect(deckyEventListenerCount("sync_progress")).toBe(1);
    expect(deckyEventListenerCount("save_status_updated")).toBe(1);

    emitDeckyEvent("sync_progress", { running: true, stage: "applying", current: 1, total: 2, message: "" });
    await vi.advanceTimersByTimeAsync(2000);
    expect(getConsoleShelf).toHaveBeenCalledTimes(1);

    emitDeckyEvent("sync_progress", { running: false, stage: "done", current: 2, total: 2, message: "" });
    emitDeckyEvent("save_status_updated", { rom_id: 1 });
    globalThis.dispatchEvent(new CustomEvent("romm_playtime_changed", { detail: { appId: 1 } }));
    await vi.advanceTimersByTimeAsync(2000);
    expect(getConsoleShelf).toHaveBeenCalledTimes(2);

    stop();
    expect(deckyEventListenerCount("sync_progress")).toBe(0);
    expect(deckyEventListenerCount("save_status_updated")).toBe(0);
    globalThis.dispatchEvent(new CustomEvent("romm_playtime_changed", { detail: { appId: 1 } }));
    await vi.advanceTimersByTimeAsync(2000);
    expect(getConsoleShelf).toHaveBeenCalledTimes(2);
  });

  it("stop cancels a pending re-read", async () => {
    vi.useFakeTimers();
    vi.mocked(getConsoleShelf).mockResolvedValue(answer([ps2]));
    const stop = startConsoleShelfStore();
    emitDeckyEvent("save_status_updated", { rom_id: 1 });
    stop();
    await vi.advanceTimersByTimeAsync(2000);
    expect(getConsoleShelf).toHaveBeenCalledTimes(1);
  });
});
