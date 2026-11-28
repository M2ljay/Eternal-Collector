/**
 * Module-level store behind The Collector's Home row.
 *
 * Steam re-renders Home constantly, so the row never calls the backend while it
 * renders: it reads this store through {@link useConsoleShelf}, and the store is
 * filled by one `get_console_shelf` read at plugin start and re-read when what it
 * shows can have changed — a sync run ending, a session's playtime landing, a
 * save-status answer.
 *
 * The row shows one tile per console family with games in the library. Each
 * family's hero and logo come from the user's icon pack through `get_family_art`,
 * read once per family when the family first appears and kept as data URLs, so
 * the row never waits on them: a tile draws its plain fallback until its art
 * lands, and keeps it when the pack has none.
 *
 * Every write installs a new state object, so {@link getConsoleShelfState} is a
 * valid `useSyncExternalStore` snapshot. Each read takes a sequence number when
 * it is issued and an answer older than the last one applied is dropped, so a
 * slow read can never overwrite a newer one.
 */

import { useSyncExternalStore } from "react";
import { addEventListener, removeEventListener } from "@decky/api";
import { getConsoleShelf, getFamilyArt, logWarn } from "../api/backend";
import { consoleFamily, FAMILY_ORDER, type ConsoleFamily } from "../theme/coreTokens";
import type { ShelfConsole, SyncProgress } from "../types";

/** A family's art: a data URL, `null` when the icon pack has none, `undefined` while it is being read. */
export interface FamilyArt {
  hero?: string | null;
  logo?: string | null;
}

export interface ConsoleShelfState {
  status: "idle" | "ready" | "error";
  /** The "Show The Collector on Home" setting; on until the backend says otherwise. */
  enabled: boolean;
  consoles: ShelfConsole[];
  /** The families with at least one console in `consoles`, in shelf order. */
  families: ConsoleFamily[];
  art: Partial<Record<ConsoleFamily, FamilyArt>>;
}

const INITIAL: ConsoleShelfState = { status: "idle", enabled: true, consoles: [], families: [], art: {} };
const REFRESH_DEBOUNCE_MS = 1500;

let state: ConsoleShelfState = INITIAL;
let listeners: Array<() => void> = [];
let issued = 0;
let applied = 0;
let artRequested = new Set<ConsoleFamily>();

function publish(next: ConsoleShelfState): void {
  state = next;
  listeners.forEach((fn) => fn());
}

export function getConsoleShelfState(): ConsoleShelfState {
  return state;
}

export function onConsoleShelfChange(fn: () => void): () => void {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
}

/** The families present among `consoles`, in shelf order. */
export function shelfFamilies(consoles: readonly ShelfConsole[]): ConsoleFamily[] {
  const present = new Set(consoles.map((c) => consoleFamily(c.platform_slug)));
  return FAMILY_ORDER.filter((f) => present.has(f));
}

async function readArt(family: ConsoleFamily, kind: "hero" | "logo"): Promise<string | null> {
  try {
    const answer = await getFamilyArt(family, kind);
    return answer.success && answer.base64 ? `data:image/png;base64,${answer.base64}` : null;
  } catch (e) {
    logWarn(`The Collector: ${family} ${kind} read failed: ${e instanceof Error ? e.message : String(e)}`);
    return null;
  }
}

function setArt(family: ConsoleFamily, part: FamilyArt): void {
  publish({ ...state, art: { ...state.art, [family]: { ...state.art[family], ...part } } });
}

/**
 * Read the art of every family not read yet, one file at a time: a hero is a few
 * megabytes, and one callable answer at a time keeps Decky's bridge clear.
 */
async function loadFamilyArt(families: readonly ConsoleFamily[]): Promise<void> {
  const fresh = families.filter((f) => !artRequested.has(f));
  fresh.forEach((f) => artRequested.add(f));
  for (const family of fresh) {
    setArt(family, { logo: await readArt(family, "logo") });
    setArt(family, { hero: await readArt(family, "hero") });
  }
}

export function useConsoleShelf(): ConsoleShelfState {
  return useSyncExternalStore(onConsoleShelfChange, getConsoleShelfState);
}

/** Reflect a settings change at once, ahead of the next read. */
export function setHomeShelfEnabled(enabled: boolean): void {
  if (state.enabled !== enabled) publish({ ...state, enabled });
}

/** Read the shelf from the backend; a failure keeps what is shown and is logged. */
export async function refreshConsoleShelf(): Promise<void> {
  const ticket = ++issued;
  try {
    const answer = await getConsoleShelf();
    if (ticket < applied) return;
    applied = ticket;
    const families = shelfFamilies(answer.consoles);
    publish({ ...state, status: "ready", enabled: answer.enabled, consoles: answer.consoles, families });
    void loadFamilyArt(families);
  } catch (e) {
    if (ticket < applied) return;
    applied = ticket;
    logWarn(`The Collector: console shelf read failed: ${e instanceof Error ? e.message : String(e)}`);
    publish({ ...state, status: state.status === "ready" ? "ready" : "error" });
  }
}

/**
 * Load the shelf now and keep it current until the returned stop function runs.
 * Bursts of change signals (a sync applying many games) collapse into one read.
 */
export function startConsoleShelfStore(): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const schedule = () => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void refreshConsoleShelf();
    }, REFRESH_DEBOUNCE_MS);
  };
  const onSyncProgress = (progress: SyncProgress) => {
    if (progress.running === false) schedule();
  };
  const onSaveStatus = () => schedule();
  const onPlaytime = () => schedule();

  addEventListener<[SyncProgress]>("sync_progress", onSyncProgress);
  addEventListener("save_status_updated", onSaveStatus);
  globalThis.addEventListener("romm_playtime_changed", onPlaytime);
  void refreshConsoleShelf();

  return () => {
    if (timer !== null) clearTimeout(timer);
    removeEventListener("sync_progress", onSyncProgress);
    removeEventListener("save_status_updated", onSaveStatus);
    globalThis.removeEventListener("romm_playtime_changed", onPlaytime);
  };
}

/** Test-only: drop every subscriber and return to the initial state. */
export function resetConsoleShelfStore(): void {
  state = INITIAL;
  listeners = [];
  issued = 0;
  applied = 0;
  artRequested = new Set();
}
