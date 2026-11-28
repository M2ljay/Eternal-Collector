/**
 * Wire shapes of The Collector's callables (`services/console_shelf.py`,
 * `AchievementsService.refresh_progress_snapshot`). Every field of a console page
 * is computed from this device's own records, so the page never waits on the network.
 */

import type { RommErrorCode } from "./api";
import type { SaveSyncDisplay } from "./saves";

export type CollectorAward = "mastered" | "completed" | "beaten";

/** A game's RetroAchievements chip, from the achievement snapshot. */
export interface CollectorAchievements {
  earned: number;
  total: number;
  earned_hardcore: number;
  /** Every unlock so far was earned in hardcore mode. */
  hardcore: boolean;
  award: CollectorAward | null;
  fetched_at: string;
}

export interface ConsoleGame {
  rom_id: number;
  app_id: number;
  name: string;
  last_played: string | null;
  play_seconds: number;
  installed: boolean;
  save_sync: SaveSyncDisplay | null;
  achievements: CollectorAchievements | null;
  /** The game has a RetroAchievements set; with `achievements` null that reads "no progress yet". */
  has_ra_set: boolean;
}

export interface ConsoleGamesPage {
  success: true;
  platform_slug: string;
  name: string;
  total: number;
  offset: number;
  continue_rom_id: number | null;
  save_sync_enabled: boolean;
  /** When the achievement snapshot was last replaced; null before the first refresh. */
  achievements_fetched_at: string | null;
  games: ConsoleGame[];
}

export interface CollectorFailure {
  success: false;
  reason: RommErrorCode | string;
  message: string;
}

export type ConsoleGamesAnswer = ConsoleGamesPage | CollectorFailure;

export type RefreshAchievementsAnswer = { success: true; refreshed_at: string } | CollectorFailure;
