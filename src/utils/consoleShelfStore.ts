/**
 * Module-level store behind The Collector's Home row.
 *
 * Steam re-renders Home constantly, so the row never calls the backend while it
 * renders: it reads this store through {@link useConsoleShelf}, and the store is
 * filled by one `get_console_shelf` read at plugin start and re-read when what it
 * shows can have changed — a sync run ending, a session's playtime landing, a
 * save-status answer.
 *
 * Every write installs a new state object, so {@link getConsoleShelfState} is a
 * valid `useSyncExternalStore` snapshot. Each read takes a sequence number when
 * it is issued and an answer older than the last one applied is dropped, so a
 * slow read can never overwrite a newer one.
 */

import { useSyncExternalStore } from "react";
import { addEventListener, removeEventListener } from "@decky/api";
import { getConsoleShelf, logWarn } from "../api/backend";
import type { ShelfConsole, SyncProgress } from "../types";

export interface ConsoleShelfState {
  status: "idle" | "ready" | "error";
  /** The "Show The Collector on Home" setting; on until the backend says otherwise. */
  enabled: boolean;
  consoles: ShelfConsole[];
}

const INITIAL: ConsoleShelfState = { status: "idle", enabled: true, consoles: [] };
const REFRESH_DEBOUNCE_MS = 1500;

let state: ConsoleShelfState = INITIAL;
let listeners: Array<() => void> = [];
let issued = 0;
let applied = 0;

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
    publish({ status: "ready", enabled: answer.enabled, consoles: answer.consoles });
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
}
