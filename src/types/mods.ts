/**
 * The Mods panel's wire shapes (`get_game_mods` and its siblings). Every path is
 * resolved by the backend on each call; the frontend only ever sends back a
 * target id, a Downloads entry name, or an entry name the backend listed.
 */

export interface ModEntry {
  name: string;
  is_dir: boolean;
  size: number | null;
  files: number | null;
  /** Seconds since the epoch. */
  modified: number;
  /** True when a folder's totals stopped at the walk limit. */
  partial: boolean;
}

export type ModSettingState = "on" | "off" | "unknown";

export interface ModSetting {
  label: string;
  file: string;
  section: string;
  key: string;
  state: ModSettingState;
  can_enable: boolean;
}

export type ModScope = "game" | "shared" | "patch";

export interface ModTarget {
  target_id: string;
  label: string;
  scope: ModScope;
  path: string;
  exists: boolean;
  game_folder: string | null;
  notes: string[];
  installed: ModEntry[];
  installed_truncated: boolean;
  setting: ModSetting | null;
  accepts: "patch" | "archive_or_folder";
}

export interface ModEmulator {
  id: string | null;
  label: string;
  exe: string;
}

export interface ModFailure {
  success: false;
  reason: string;
  message: string;
}

export interface GameModsInfo {
  success: true;
  emulator: ModEmulator | null;
  game_id: string | null;
  targets: ModTarget[];
  omitted: { label: string; reason: string }[];
  note: string | null;
}

export type GameModsAnswer = GameModsInfo | ModFailure;

export type ModSourceKind = "zip" | "folder" | "patch" | "unsupported_archive";

export interface ModSource extends ModEntry {
  kind: ModSourceKind;
  supported: boolean;
}

export type ModSourcesAnswer = { success: true; folder: string; entries: ModSource[]; truncated: boolean } | ModFailure;

export interface ModInstallPreview {
  success: true;
  destination: string;
  source: string;
  writes: { path: string; size: number; replaces: boolean }[];
  write_count: number;
  total_bytes: number;
  replace_count: number;
  stripped_folder: string | null;
  backup_root: string | null;
  fingerprint: string;
}

export type ModPreviewAnswer = ModInstallPreview | ModFailure;

export type ModInstallAnswer =
  | { success: true; destination: string; written: number; backed_up: number; backup_folder: string | null }
  | (ModFailure & { written?: number; backup_folder?: string | null });

export type ModRemoveAnswer = { success: true; removed: string; backup_folder: string } | ModFailure;

export type ModSettingAnswer = { success: true; file: string; backup_path: string } | ModFailure;

export type ModOpenAnswer = { success: true; folder: string } | ModFailure;
