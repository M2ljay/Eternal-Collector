/**
 * Achievements types — RetroAchievements integration: per-achievement metadata,
 * per-user earned records, and the summary/list/progress envelope shapes
 * returned by the backend.
 */

import type { RommErrorCode } from "./api";

export interface Achievement {
  ra_id: number;
  badge_id: string;
  title: string;
  description: string;
  points: number;
  badge_url: string;
  badge_url_lock: string;
  display_order: number;
  type: string;
  num_awarded: number;
  num_awarded_hardcore: number;
}

export interface EarnedAchievement {
  id: string;
  date: string;
  date_hardcore: string | null;
}

export interface AchievementSummary {
  earned: number;
  total: number;
  earned_hardcore: number;
  cached_at?: number;
}

export interface AchievementList {
  success: boolean;
  achievements: Achievement[];
  total: number;
  no_ra_id?: boolean;
  stale?: boolean;
  // Present on a failure ({success: false}); "server_unreachable" is the only
  // reason the offline feed acts on (#1345).
  reason?: RommErrorCode;
  message?: string;
}

export interface AchievementProgress {
  success: boolean;
  earned: number;
  earned_hardcore?: number;
  total: number;
  earned_achievements: EarnedAchievement[];
  no_ra_id?: boolean;
  stale?: boolean;
  // Present on a failure ({success: false}); "server_unreachable" is the only
  // reason the offline feed acts on. "no_ra_username" is a config gap, not a
  // connectivity verdict, so the feed leaves the store untouched for it (#1345).
  reason?: RommErrorCode | "no_ra_username";
  message?: string;
}

/** A failure from the achievement journal callables (canonical failure shape). */
export interface JournalFailure {
  success: false;
  reason: string;
  message: string;
}

/** One achievement the user pinned as a goal, with what it looked like when pinned. */
export interface AchievementGoal {
  achievement_id: number;
  title: string;
  description: string;
  points: number;
  pinned_at: string;
  /** ISO-8601 UTC; null until an unlock has been seen. */
  unlocked_at: string | null;
  unlocked_hardcore: boolean;
}

/** The user's goals and notes for one RetroAchievements game (shared by every version of it). */
export interface AchievementJournal {
  success: true;
  ra_game_id: number;
  game_title: string;
  notes: string;
  notes_updated_at: string | null;
  goals: AchievementGoal[];
  game_url?: string;
  web_api_configured?: boolean;
}

export type AchievementJournalAnswer = AchievementJournal | JournalFailure;

/** What pinning sends: taken from the achievement list the tab already shows. */
export interface PinnedAchievement {
  achievement_id: number;
  title: string;
  description: string;
  points: number;
}

/** An unlock seen in RomM's progress data, relayed so the goal ticks off everywhere. */
export interface GoalUnlock {
  achievement_id: number;
  unlocked_at: string;
  hardcore: boolean;
}

/** A goal in the cross-game list, with its game and (when it has a shortcut) its Steam app id. */
export interface OverviewGoal extends AchievementGoal {
  ra_game_id: number;
  game_title: string;
  app_id: number | null;
  /** A ROM of the game, for unpinning from the QAM; null once no ROM points at the game. */
  rom_id: number | null;
  achievement_url: string;
}

export type GoalsOverviewAnswer =
  | {
      success: true;
      goals: OverviewGoal[];
      open_count: number;
      web_api_configured: boolean;
      refreshed?: number;
      failed?: number;
      changed?: number;
    }
  | JournalFailure;

/** One unlock in the timeline (from RetroAchievements' Web API). */
export interface TimelineEntry {
  unlocked_at: string;
  achievement_id: number;
  title: string;
  description: string;
  points: number;
  hardcore: boolean;
  game_id: number;
  game_title: string;
  console_name: string;
  badge_url: string;
}

/** The windows the unlock timeline offers, in days. */
export type TimelineRange = 30 | 90 | 365;

export type UnlockTimelineAnswer =
  { success: true; days: TimelineRange; entries: TimelineEntry[]; fetched_at: string } | JournalFailure;

export type GameLinksAnswer =
  { success: true; game_url: string; guide_url: string | null; web_api_configured: boolean } | JournalFailure;
