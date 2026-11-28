/**
 * The Collector's achievements bridge — `window.__eternalCollectorAchievements`.
 *
 * Lets another plugin (Core's Home Achievements tab) read The Collector's
 * RetroAchievements data: the newest unlocks and the started games closest to
 * 100%, each naming the ROM and its Steam shortcut appId. Read-only: it wraps two
 * backend reads and, for the second, the achievement-snapshot refresh the console
 * page already makes. No wrapper throws, every failure is `{ ok: false, reason }`
 * with a fixed reason code and no message, so nothing from an error (and never the
 * RetroAchievements Web API key, which no answer carries) can leave through it.
 * Contract: `docs/architecture/achievement-journal.md#achievements-bridge`.
 */

import { getClosestRaCompletions, getRecentRaUnlocks, refreshConsoleAchievements } from "../api/backend";
import type { ClosestRaCompletionsAnswer, RaCompletionWire, RecentRaUnlockWire } from "../types/achievements";

export const COLLECTOR_ACHIEVEMENTS_GLOBAL = "__eternalCollectorAchievements";
/** Dispatched on `window` each time the bridge is installed. */
export const COLLECTOR_ACHIEVEMENTS_READY_EVENT = "eternal_collector_achievements_ready";
export const COLLECTOR_ACHIEVEMENTS_VERSION = 1;

export const MIN_LIMIT = 1;
export const MAX_LIMIT = 50;
/** The snapshot is re-read from RomM when it is older than this, as the console page does. */
export const SNAPSHOT_MAX_AGE_MS = 3_600_000;

export interface RecentUnlock {
  romId: number;
  /** The Steam shortcut appId; null when the game's ROM has no shortcut. */
  appId: number | null;
  game: string;
  platform: string;
  title: string;
  description: string;
  /** A public https URL on media.retroachievements.org, or null. */
  badgeUrl: string | null;
  /** ISO-8601, UTC. */
  unlockedAt: string;
  hardcore: boolean;
}

export interface CompletionProgress {
  romId: number;
  appId: number | null;
  game: string;
  platform: string;
  earned: number;
  total: number;
  /** 0-100, one decimal; never 0 or 100 in an answer. */
  percent: number;
}

export type BridgeFailure = { ok: false; reason: string };
export type RecentUnlocksAnswer = { ok: true; items: RecentUnlock[] } | BridgeFailure;
export type ClosestToCompleteAnswer = { ok: true; items: CompletionProgress[] } | BridgeFailure;

export interface CollectorAchievementsBridge {
  readonly version: number;
  /** The newest unlocks in games of the library, newest first. Needs the RetroAchievements Web API key. */
  getRecentUnlocks(limit: number): Promise<RecentUnlocksAnswer>;
  /** Started, unfinished games, highest completion first (0% and 100% left out). From RomM's progress data. */
  getClosestToComplete(limit: number): Promise<ClosestToCompleteAnswer>;
}

export interface CollectorAchievementsBridgeDeps {
  /** Milliseconds since the epoch; injectable for tests. */
  readonly now?: () => number;
}

const MEDIA_HOST = "media.retroachievements.org";
const REASON = /^[a-z_]{1,40}$/;

function fail(reason: string): BridgeFailure {
  return { ok: false, reason };
}

/** A limit clamped to 1-50, or null when *value* is not a finite number. */
export function clampLimit(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, Math.floor(value)));
}

/**
 * *url* when it is a plain https image URL on RetroAchievements' media host (no
 * user info, port, query or fragment), else null. The backend checks the same
 * (`domain/ra_web.public_badge_url`); checking again here keeps the bridge's
 * promise independent of it.
 */
export function publicBadgeUrl(url: unknown): string | null {
  if (typeof url !== "string" || !url || url.includes("?") || url.includes("#")) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase() !== MEDIA_HOST) return null;
  if (parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash) return null;
  return url;
}

/** A backend failure reason as a bridge reason: the bridge's own names, else the code if it is a plain one. */
function bridgeReason(reason: unknown): string {
  if (reason === "no_web_api_key" || reason === "no_snapshot") return "not_configured";
  if (reason === "invalid_argument") return "bad_request";
  return typeof reason === "string" && REASON.test(reason) ? reason : "backend_error";
}

function appIdOf(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function toUnlock(w: RecentRaUnlockWire): RecentUnlock {
  return {
    romId: w.rom_id,
    appId: appIdOf(w.app_id),
    game: w.game,
    platform: w.platform,
    title: w.title,
    description: w.description,
    badgeUrl: publicBadgeUrl(w.badge_url),
    unlockedAt: w.unlocked_at,
    hardcore: w.hardcore === true,
  };
}

function toProgress(w: RaCompletionWire): CompletionProgress {
  return {
    romId: w.rom_id,
    appId: appIdOf(w.app_id),
    game: w.game,
    platform: w.platform,
    earned: w.earned,
    total: w.total,
    percent: w.percent,
  };
}

async function guarded<T>(run: () => Promise<T | BridgeFailure>): Promise<T | BridgeFailure> {
  try {
    return await run();
  } catch {
    return fail("bridge_error");
  }
}

export function createCollectorAchievementsBridge(
  deps: CollectorAchievementsBridgeDeps = {},
): CollectorAchievementsBridge {
  const now = deps.now ?? Date.now;
  let lastRefreshAttempt: number | null = null;
  let refreshing: Promise<void> | null = null;

  const isStale = (answer: ClosestRaCompletionsAnswer): boolean => {
    if (!answer.success) return answer.reason === "no_snapshot";
    const at = Date.parse(answer.fetched_at);
    return Number.isNaN(at) || now() - at > SNAPSHOT_MAX_AGE_MS;
  };

  /** One RomM re-read at a time, and at most one attempt an hour whatever its outcome. */
  const refreshSnapshot = (): Promise<void> => {
    if (refreshing) return refreshing;
    if (lastRefreshAttempt !== null && now() - lastRefreshAttempt < SNAPSHOT_MAX_AGE_MS) return Promise.resolve();
    lastRefreshAttempt = now();
    refreshing = refreshConsoleAchievements()
      .then(() => undefined)
      .catch(() => undefined)
      .finally(() => {
        refreshing = null;
      });
    return refreshing;
  };

  const bridge: CollectorAchievementsBridge = {
    version: COLLECTOR_ACHIEVEMENTS_VERSION,

    getRecentUnlocks: (limit) =>
      guarded(async (): Promise<RecentUnlocksAnswer> => {
        const size = clampLimit(limit);
        if (size === null) return fail("bad_request");
        const answer = await getRecentRaUnlocks(size);
        if (!answer.success) return fail(bridgeReason(answer.reason));
        return { ok: true, items: answer.items.slice(0, size).map(toUnlock) };
      }),

    getClosestToComplete: (limit) =>
      guarded(async (): Promise<ClosestToCompleteAnswer> => {
        const size = clampLimit(limit);
        if (size === null) return fail("bad_request");
        let answer = await getClosestRaCompletions(size);
        if (isStale(answer)) {
          await refreshSnapshot();
          answer = await getClosestRaCompletions(size);
        }
        if (!answer.success) return fail(bridgeReason(answer.reason));
        return { ok: true, items: answer.items.slice(0, size).map(toProgress) };
      }),
  };
  return Object.freeze(bridge);
}

/**
 * Publish the bridge on `window` and announce it. Returns the uninstall
 * function, which withdraws the global only if it is still this one.
 */
export function installCollectorAchievementsBridge(deps: CollectorAchievementsBridgeDeps = {}): () => void {
  const bridge = createCollectorAchievementsBridge(deps);
  const target = globalThis as unknown as Record<string, unknown>;
  target[COLLECTOR_ACHIEVEMENTS_GLOBAL] = bridge;
  globalThis.dispatchEvent(
    new CustomEvent(COLLECTOR_ACHIEVEMENTS_READY_EVENT, { detail: { version: COLLECTOR_ACHIEVEMENTS_VERSION } }),
  );
  return () => {
    if (target[COLLECTOR_ACHIEVEMENTS_GLOBAL] === bridge) delete target[COLLECTOR_ACHIEVEMENTS_GLOBAL];
  };
}
