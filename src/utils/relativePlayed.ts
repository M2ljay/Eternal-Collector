/**
 * "Last played" wording for The Collector, relative to the viewer's local clock.
 *
 * The day turns over at 05:00 rather than midnight: a session that ran past
 * midnight still reads "Played tonight" until morning.
 */

import { pluralize } from "./pluralize";

const DAY_TURNOVER_HOURS = 5;
const EVENING_FROM_HOURS = 17;
const MS_PER_HOUR = 3_600_000;
const MS_PER_DAY = 24 * MS_PER_HOUR;

function playDay(instant: Date): number {
  const shifted = new Date(instant.getTime() - DAY_TURNOVER_HOURS * MS_PER_HOUR);
  return Date.UTC(shifted.getFullYear(), shifted.getMonth(), shifted.getDate()) / MS_PER_DAY;
}

export function relativePlayed(lastPlayed: string | null | undefined, now: Date = new Date()): string {
  if (!lastPlayed) return "Not played yet";
  const played = new Date(lastPlayed);
  if (Number.isNaN(played.getTime())) return "Not played yet";

  const days = playDay(now) - playDay(played);
  if (days <= 0) {
    const hour = played.getHours();
    const evening = hour >= EVENING_FROM_HOURS || hour < DAY_TURNOVER_HOURS;
    return evening ? "Played tonight" : "Played today";
  }
  if (days === 1) return "Played yesterday";
  if (days < 7) return `Played ${pluralize(days, "day")} ago`;
  if (days < 14) return "Played last week";
  if (days < 60) return `Played ${pluralize(Math.floor(days / 7), "week")} ago`;
  if (days < 365) return `Played ${pluralize(Math.floor(days / 30), "month")} ago`;
  return `Played ${pluralize(Math.floor(days / 365), "year")} ago`;
}
