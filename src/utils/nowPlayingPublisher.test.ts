import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as backend from "../api/backend";
import type { NowPlayingDocument, NowPlayingRecord } from "../types";
import { NOW_PLAYING_EVENT, NOW_PLAYING_GLOBAL, startNowPlayingPublisher } from "./nowPlayingPublisher";

vi.mock("../api/backend", () => ({
  publishNowPlaying: vi.fn(),
  resolveNowPlayingCover: vi.fn(),
  clearNowPlaying: vi.fn().mockResolvedValue({ success: true }),
  logError: vi.fn(),
}));

const APP = 3_000_000_123;
const IGDB = "https://images.igdb.com/igdb/image/upload/t_cover_big/co3nnx.jpg";

function record(over: Partial<NowPlayingRecord> = {}): NowPlayingRecord {
  return {
    app_id: APP,
    rom_id: 7,
    name: "The Legend of Zelda: Ocarina of Time",
    platform: "Nintendo 64",
    started_at: 5_000,
    cover_url: null,
    ...over,
  };
}

function session(running: boolean, appId = APP, romId = 7, startMs: number | null = 5_000): void {
  const detail = startMs === null ? { running, appId, romId } : { running, appId, romId, startMs };
  globalThis.dispatchEvent(new CustomEvent("romm_session_changed", { detail }));
}

const shared = () => (globalThis as unknown as Record<string, NowPlayingDocument | undefined>)[NOW_PLAYING_GLOBAL];
const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

describe("nowPlayingPublisher", () => {
  let stop: () => void;
  let events: NowPlayingDocument[];
  const onEvent = (e: Event) => events.push((e as CustomEvent<NowPlayingDocument>).detail);

  beforeEach(() => {
    vi.mocked(backend.publishNowPlaying).mockReset();
    vi.mocked(backend.resolveNowPlayingCover).mockReset();
    vi.mocked(backend.clearNowPlaying).mockClear();
    vi.mocked(backend.publishNowPlaying).mockResolvedValue({ success: true, record: record() });
    vi.mocked(backend.resolveNowPlayingCover).mockResolvedValue({ success: true, record: record({ cover_url: IGDB }) });
    events = [];
    globalThis.addEventListener(NOW_PLAYING_EVENT, onEvent);
    stop = startNowPlayingPublisher();
  });

  afterEach(() => {
    stop();
    globalThis.removeEventListener(NOW_PLAYING_EVENT, onEvent);
  });

  it("publishes a started ROM, then adds its cover", async () => {
    session(true);
    await flush();
    expect(backend.publishNowPlaying).toHaveBeenCalledWith(7, APP, 5_000);
    expect(backend.resolveNowPlayingCover).toHaveBeenCalledWith(7, APP);
    expect(shared()).toEqual({ v: 1, source: "collector", records: { [APP]: record({ cover_url: IGDB }) } });
    expect(events.map((d) => d.records[APP]?.cover_url)).toEqual([null, IGDB]);
  });

  it("withdraws the record when the game ends", async () => {
    session(true);
    await flush();
    session(false);
    await flush();
    expect(shared()).toBeUndefined();
    expect(events[events.length - 1]).toEqual({ v: 1, source: "collector", records: {} });
    expect(backend.clearNowPlaying).toHaveBeenCalledWith(APP);
  });

  it("never re-publishes a game that ended while its publish was in flight", async () => {
    let answer: (v: { success: true; record: NowPlayingRecord }) => void = () => undefined;
    vi.mocked(backend.publishNowPlaying).mockReturnValue(new Promise((resolve) => (answer = resolve)));
    session(true);
    session(false);
    answer({ success: true, record: record() });
    await flush();
    expect(shared()).toBeUndefined();
    expect(backend.resolveNowPlayingCover).not.toHaveBeenCalled();
  });

  it("ignores the re-announcement of a live session", async () => {
    session(true);
    await flush();
    session(true);
    await flush();
    expect(backend.publishNowPlaying).toHaveBeenCalledTimes(1);
  });

  it("keeps concurrent games apart", async () => {
    vi.mocked(backend.publishNowPlaying).mockImplementation(async (romId, appId, startMs) => ({
      success: true,
      record: record({ rom_id: romId, app_id: appId, started_at: startMs }),
    }));
    vi.mocked(backend.resolveNowPlayingCover).mockResolvedValue({ success: true, record: null });
    session(true, APP, 7);
    session(true, 42, 9, 6_000);
    await flush();
    session(false, APP, 7);
    await flush();
    expect(Object.keys(shared()?.records ?? {})).toEqual(["42"]);
  });

  it("degrades to no record when the backend fails, without throwing", async () => {
    vi.mocked(backend.publishNowPlaying).mockRejectedValue(new Error("backend down"));
    session(true);
    await flush();
    expect(shared()).toBeUndefined();
    expect(backend.logError).toHaveBeenCalled();
    vi.mocked(backend.publishNowPlaying).mockResolvedValue({ success: false, reason: "not_found", message: "x" });
    session(true, 77, 8);
    await flush();
    expect(shared()).toBeUndefined();
  });

  it("falls back to now when the event carries no start", async () => {
    vi.spyOn(Date, "now").mockReturnValue(9_999);
    session(true, APP, 7, null);
    await flush();
    expect(backend.publishNowPlaying).toHaveBeenCalledWith(7, APP, 9_999);
    vi.mocked(Date.now).mockRestore();
  });

  it("stop withdraws every record and stops listening", async () => {
    session(true);
    await flush();
    stop();
    expect(shared()).toBeUndefined();
    await flush();
    expect(backend.clearNowPlaying).toHaveBeenCalledWith(APP);
    session(true);
    await flush();
    expect(backend.publishNowPlaying).toHaveBeenCalledTimes(1);
    stop = () => undefined;
  });
});
