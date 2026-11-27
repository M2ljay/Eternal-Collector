/**
 * Wire shapes of the "now playing" record The Collector publishes while a ROM
 * runs (`services/now_playing.py`, contract in
 * `docs/architecture/now-playing-presence.md`).
 */

/** One running ROM. Nothing in it points at the RomM server. */
export interface NowPlayingRecord {
  /** The Steam shortcut's app id. */
  app_id: number;
  rom_id: number;
  name: string;
  /** Console display name, e.g. "Nintendo 64". */
  platform: string;
  /** Unix time in milliseconds. */
  started_at: number;
  /** A public metadata-provider cover URL, or null. */
  cover_url: string | null;
}

/** What other plugins read on `window.__eternalNowPlaying` (version 1). */
export interface NowPlayingDocument {
  v: 1;
  source: "collector";
  records: Record<string, NowPlayingRecord>;
}

export type NowPlayingAnswer =
  { success: true; record: NowPlayingRecord | null } | { success: false; reason: string; message: string };
