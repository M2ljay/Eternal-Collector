/**
 * Publishes the running ROM for other Decky plugins — Assemble turns it into
 * Discord Rich Presence. Contract: `docs/architecture/now-playing-presence.md`.
 *
 * Follows `sessionManager` through its `romm_session_changed` event, so it
 * never changes when or how a session is tracked. For every running RomM game
 * it keeps one record in two places: `window.__eternalNowPlaying` (with an
 * `eternal_now_playing` event after each change) for plugins in this shared
 * Steam page, and the backend's shared file for plugin backends, which are
 * separate processes. Failures are logged and never reach the game.
 */

import { clearNowPlaying, logError, publishNowPlaying, resolveNowPlayingCover } from "../api/backend";
import type { NowPlayingDocument, NowPlayingRecord } from "../types";
import type { RommSessionChangedDetail } from "../types/events";
import { detach } from "./detach";

export const NOW_PLAYING_GLOBAL = "__eternalNowPlaying";
export const NOW_PLAYING_EVENT = "eternal_now_playing";

const records = new Map<number, NowPlayingRecord>();
// The latest session edge per app. An answer for an older edge is dropped, so a
// game that ended while its publish was in flight is never shown again.
const edges = new Map<number, number>();
let edgeSeq = 0;

function project(): void {
  const doc: NowPlayingDocument = { v: 1, source: "collector", records: {} };
  for (const [appId, record] of records) doc.records[String(appId)] = record;
  const target = globalThis as unknown as Record<string, unknown>;
  if (records.size > 0) target[NOW_PLAYING_GLOBAL] = doc;
  else delete target[NOW_PLAYING_GLOBAL];
  globalThis.dispatchEvent(new CustomEvent(NOW_PLAYING_EVENT, { detail: doc }));
}

function setRecord(record: NowPlayingRecord): void {
  records.set(record.app_id, record);
  project();
}

async function publish(appId: number, romId: number, startMs: number): Promise<void> {
  const known = records.get(appId);
  // sessionManager re-announces a live session; its record is already out.
  if (known?.rom_id === romId) return;
  const edge = ++edgeSeq;
  edges.set(appId, edge);
  try {
    const published = await publishNowPlaying(romId, appId, startMs);
    if (edges.get(appId) !== edge || !published.success || !published.record) return;
    setRecord(published.record);
    const withCover = await resolveNowPlayingCover(romId, appId);
    if (edges.get(appId) !== edge || !withCover.success || !withCover.record) return;
    if (withCover.record.cover_url !== published.record.cover_url) setRecord(withCover.record);
  } catch (e) {
    logError(`Now playing: publish failed for appId=${appId}: ${e}`);
  }
}

function clear(appId: number): void {
  edges.set(appId, ++edgeSeq);
  if (records.delete(appId)) project();
  detach(
    Promise.resolve()
      .then(() => clearNowPlaying(appId))
      .catch((e: unknown) => {
        logError(`Now playing: clear failed for appId=${appId}: ${e}`);
      }),
  );
}

function onSessionChanged(e: WindowEventMap["romm_session_changed"]): void {
  const { running, appId, romId, startMs }: RommSessionChangedDetail = e.detail;
  if (running) detach(publish(appId, romId, startMs ?? Date.now()));
  else clear(appId);
}

/**
 * Start following play sessions. Call before `initSessionManager`, so the
 * sessions its reload adoption restores are published too. Returns the stop
 * function, which withdraws every record (the plugin is going away).
 * A stopped app's clear is serialised after its publish by the backend's lock.
 */
export function startNowPlayingPublisher(): () => void {
  globalThis.addEventListener("romm_session_changed", onSessionChanged);
  return () => {
    globalThis.removeEventListener("romm_session_changed", onSessionChanged);
    // A publish still in flight has written, or will write, the shared file.
    for (const appId of new Set([...records.keys(), ...edges.keys()])) clear(appId);
    edges.clear();
  };
}
