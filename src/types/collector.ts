/**
 * Wire shapes of The Collector's callables (`services/console_shelf.py`,
 * `AchievementsService.refresh_progress_snapshot`). Every field is computed from
 * this device's own records, so the Home row never waits on the network.
 */

import type { RommErrorCode } from "./api";
import type { SaveSyncDisplay } from "./saves";

/** One console tile on the Home row, already in "most played" order. */
export interface ShelfConsole {
  platform_slug: string;
  name: string;
  game_count: number;
  /** ISO-8601, the newest last-played instant of any of its games; null when none was played. */
  last_played: string | null;
  play_seconds: number;
  /** The shortcut whose Steam capsule art stands for the console: its "Continue" game, else its first by name. */
  cover_app_id: number;
}

export interface ConsoleShelfAnswer {
  success: true;
  /** The "Show The Collector on Home" setting. */
  enabled: boolean;
  consoles: ShelfConsole[];
}

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
