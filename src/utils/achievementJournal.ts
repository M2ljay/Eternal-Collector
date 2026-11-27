/**
 * Achievement journal helpers — the pure rules behind goals, the unlock timeline
 * and the RetroAchievements link-outs, plus the one place that opens a
 * RetroAchievements page in Steam's browser.
 *
 * RomM reports a user's earned achievements by badge id (`earned_achievements[].id`
 * is the badge id), while goals are keyed by RetroAchievements achievement id; the
 * achievement list carries both, so it is the bridge.
 */

import { Navigation } from "@decky/ui";
import type { Achievement, AchievementGoal, AchievementProgress, GoalUnlock, TimelineEntry } from "../types";

/** One achievement's unlock as RomM reported it, keyed by achievement id. */
export interface SeenUnlock {
  unlocked_at: string;
  hardcore: boolean;
}

/** Map achievement id → unlock, from the list and RomM's progress for one game. */
export function unlocksByAchievementId(
  achievements: Achievement[],
  progress: AchievementProgress | null,
): Map<number, SeenUnlock> {
  const byBadge = new Map<string, Achievement>();
  for (const a of achievements) byBadge.set(a.badge_id, a);
  const result = new Map<number, SeenUnlock>();
  for (const earned of progress?.earned_achievements ?? []) {
    const achievement = byBadge.get(earned.id);
    if (!achievement) continue;
    if (earned.date_hardcore) {
      result.set(achievement.ra_id, { unlocked_at: earned.date_hardcore, hardcore: true });
    } else if (earned.date) {
      result.set(achievement.ra_id, { unlocked_at: earned.date, hardcore: false });
    }
  }
  return result;
}

/** Whether a goal counts as done: recorded as unlocked, or seen unlocked in RomM's data. */
export function isGoalDone(goal: AchievementGoal, seen: Map<number, SeenUnlock>): boolean {
  return goal.unlocked_at !== null || seen.has(goal.achievement_id);
}

/**
 * The unlocks worth relaying to the backend: goals RomM shows unlocked that the
 * journal has not recorded yet, or recorded softcore where RomM now has hardcore.
 */
export function unlocksToRecord(goals: AchievementGoal[], seen: Map<number, SeenUnlock>): GoalUnlock[] {
  const out: GoalUnlock[] = [];
  for (const goal of goals) {
    const unlock = seen.get(goal.achievement_id);
    if (!unlock) continue;
    const adds = goal.unlocked_at === null || (unlock.hardcore && !goal.unlocked_hardcore);
    if (adds) out.push({ achievement_id: goal.achievement_id, ...unlock });
  }
  return out;
}

/** Sentinel for "no filter" in the timeline's game and console dropdowns. */
export const ALL = "__all__";

export interface TimelineFilter {
  game: string;
  console: string;
}

/** The entries matching the filter; `game` is a game id as a string, or ALL. */
export function filterTimeline(entries: TimelineEntry[], filter: TimelineFilter): TimelineEntry[] {
  return entries.filter(
    (e) =>
      (filter.game === ALL || String(e.game_id) === filter.game) &&
      (filter.console === ALL || e.console_name === filter.console),
  );
}

/** The distinct games and consoles in the entries, sorted by name, for the filter dropdowns. */
export function timelineFacets(entries: TimelineEntry[]): {
  games: { id: string; title: string }[];
  consoles: string[];
} {
  const games = new Map<string, string>();
  const consoles = new Set<string>();
  for (const e of entries) {
    games.set(String(e.game_id), e.game_title || `Game ${e.game_id}`);
    if (e.console_name) consoles.add(e.console_name);
  }
  return {
    games: [...games.entries()].map(([id, title]) => ({ id, title })).sort((a, b) => a.title.localeCompare(b.title)),
    consoles: [...consoles].sort((a, b) => a.localeCompare(b)),
  };
}

/** Total points of the entries. */
export function sumPoints(entries: TimelineEntry[]): number {
  return entries.reduce((total, e) => total + e.points, 0);
}

/** "2026-11-25T10:00:00Z" → "2026-11-25 10:00" in the device's local time; unparseable stays as given. */
export function formatUnlockDate(iso: string): string {
  const date = new Date(iso.includes("T") || iso.endsWith("Z") ? iso : `${iso.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The public RetroAchievements page of one achievement. */
export function achievementPageUrl(achievementId: number): string {
  return `https://retroachievements.org/achievement/${achievementId}`;
}

const RA_HOSTS = new Set(["retroachievements.org", "www.retroachievements.org", "docs.retroachievements.org"]);

/**
 * Whether a link is one The Collector opens: https on RetroAchievements' own
 * sites, or a page of the RetroAchievements organisation on GitHub (where its
 * guides live). Nothing else is opened, so no third-party guide site is reached.
 */
export function isRetroAchievementsUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port) return false;
  const host = parsed.hostname.toLowerCase();
  if (RA_HOSTS.has(host)) return true;
  return (
    (host === "github.com" || host === "www.github.com") &&
    parsed.pathname.toLowerCase().startsWith("/retroachievements/")
  );
}

/** Open a RetroAchievements page in Steam's browser; anything else is refused. Returns whether it opened. */
export function openRetroAchievementsPage(url: string): boolean {
  if (!isRetroAchievementsUrl(url)) return false;
  Navigation.NavigateToExternalWeb(url);
  return true;
}
