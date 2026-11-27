/**
 * Pure formatters and selectors for the SettingsPage UI. Anything that takes
 * inputs and returns outputs without touching component state or React
 * belongs here; rendering helpers live alongside their sections.
 */

import { formatRelativeTime as formatRelative } from "../../utils/formatters";

/** Format a relative time string (e.g. "5m ago", "2h ago") from an ISO string */
export function formatRelativeTime(isoStr: string | null): string {
  return formatRelative(isoStr, "never", "unknown");
}

/** Format a one-line summary of the RetroArch save-sort flags. */
export function sortLabel(settings: { sort_by_content: boolean; sort_by_core: boolean }): string {
  return `Sort by content: ${settings.sort_by_content ? "ON" : "OFF"}, Sort by core: ${settings.sort_by_core ? "ON" : "OFF"}`;
}
