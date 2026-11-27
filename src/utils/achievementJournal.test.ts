import { describe, it, expect, vi, beforeEach } from "vitest";
import { Navigation } from "@decky/ui";
import {
  ALL,
  filterTimeline,
  formatUnlockDate,
  isGoalDone,
  isRetroAchievementsUrl,
  openRetroAchievementsPage,
  sumPoints,
  timelineFacets,
  unlocksByAchievementId,
  unlocksToRecord,
} from "./achievementJournal";
import type { Achievement, AchievementGoal, AchievementProgress, TimelineEntry } from "../types";

const achievement = (ra_id: number, badge_id: string): Achievement => ({
  ra_id,
  badge_id,
  title: `A${ra_id}`,
  description: "",
  points: 5,
  badge_url: "",
  badge_url_lock: "",
  display_order: ra_id,
  type: "",
  num_awarded: 0,
  num_awarded_hardcore: 0,
});

const goal = (achievement_id: number, overrides: Partial<AchievementGoal> = {}): AchievementGoal => ({
  achievement_id,
  title: `G${achievement_id}`,
  description: "",
  points: 5,
  pinned_at: "2026-11-26T10:00:00Z",
  unlocked_at: null,
  unlocked_hardcore: false,
  ...overrides,
});

const progress: AchievementProgress = {
  success: true,
  earned: 2,
  total: 3,
  earned_achievements: [
    { id: "b1", date: "2025-02-14 15:45:38", date_hardcore: null },
    { id: "b2", date: "2025-02-15 10:00:00", date_hardcore: "2025-02-15 10:00:00" },
    { id: "unknown", date: "2025-02-15 10:00:00", date_hardcore: null },
  ],
};

describe("unlocksByAchievementId", () => {
  it("bridges RomM's badge ids to achievement ids, hardcore winning", () => {
    const seen = unlocksByAchievementId([achievement(1, "b1"), achievement(2, "b2"), achievement(3, "b3")], progress);
    expect([...seen.entries()]).toEqual([
      [1, { unlocked_at: "2025-02-14 15:45:38", hardcore: false }],
      [2, { unlocked_at: "2025-02-15 10:00:00", hardcore: true }],
    ]);
  });

  it("is empty without progress", () => {
    expect(unlocksByAchievementId([achievement(1, "b1")], null).size).toBe(0);
  });
});

describe("goal ticks", () => {
  const seen = unlocksByAchievementId([achievement(1, "b1"), achievement(2, "b2")], progress);

  it("a goal is done when recorded or seen", () => {
    expect(isGoalDone(goal(1), seen)).toBe(true);
    expect(isGoalDone(goal(9), seen)).toBe(false);
    expect(isGoalDone(goal(9, { unlocked_at: "2025-01-01T00:00:00Z" }), seen)).toBe(true);
  });

  it("relays only what the journal lacks, including a hardcore upgrade", () => {
    const goals = [goal(1), goal(2, { unlocked_at: "2025-02-15T10:00:00Z", unlocked_hardcore: false }), goal(9)];
    expect(unlocksToRecord(goals, seen)).toEqual([
      { achievement_id: 1, unlocked_at: "2025-02-14 15:45:38", hardcore: false },
      { achievement_id: 2, unlocked_at: "2025-02-15 10:00:00", hardcore: true },
    ]);
    expect(unlocksToRecord([goal(2, { unlocked_at: "y", unlocked_hardcore: true })], seen)).toEqual([]);
  });
});

const entry = (achievement_id: number, game_id: number, console_name: string, points = 5): TimelineEntry => ({
  unlocked_at: "2026-11-25T10:00:00Z",
  achievement_id,
  title: `A${achievement_id}`,
  description: "",
  points,
  hardcore: false,
  game_id,
  game_title: game_id === 1 ? "Sonic" : "",
  console_name,
  badge_url: "",
});

describe("timeline", () => {
  const entries = [
    entry(1, 1, "Genesis/Mega Drive", 10),
    entry(2, 2, "SNES/Super Famicom", 25),
    entry(3, 1, "Genesis/Mega Drive"),
  ];

  it("filters by game and console", () => {
    expect(filterTimeline(entries, { game: ALL, console: ALL })).toHaveLength(3);
    expect(filterTimeline(entries, { game: "1", console: ALL }).map((e) => e.achievement_id)).toEqual([1, 3]);
    expect(filterTimeline(entries, { game: ALL, console: "SNES/Super Famicom" }).map((e) => e.achievement_id)).toEqual([
      2,
    ]);
    expect(filterTimeline(entries, { game: "1", console: "SNES/Super Famicom" })).toEqual([]);
  });

  it("lists distinct games and consoles, sorted, naming untitled games", () => {
    expect(timelineFacets(entries)).toEqual({
      games: [
        { id: "2", title: "Game 2" },
        { id: "1", title: "Sonic" },
      ],
      consoles: ["Genesis/Mega Drive", "SNES/Super Famicom"],
    });
  });

  it("sums points", () => {
    expect(sumPoints(entries)).toBe(40);
  });

  it("formats dates locally and keeps unparseable text", () => {
    expect(formatUnlockDate("2026-11-25T10:00:00Z")).toMatch(/^2026-11-2\d \d{2}:\d{2}$/);
    expect(formatUnlockDate("2025-02-14 15:45:38")).toMatch(/^2025-02-1\d \d{2}:\d{2}$/);
    expect(formatUnlockDate("whenever")).toBe("whenever");
  });
});

describe("link-outs", () => {
  beforeEach(() => vi.mocked(Navigation.NavigateToExternalWeb).mockClear());

  it.each([
    "https://retroachievements.org/achievement/1",
    "https://docs.retroachievements.org/x",
    "https://github.com/RetroAchievements/guides/wiki/Sonic",
  ])("opens %s in Steam's browser", (url) => {
    expect(isRetroAchievementsUrl(url)).toBe(true);
    expect(openRetroAchievementsPage(url)).toBe(true);
    expect(Navigation.NavigateToExternalWeb).toHaveBeenCalledWith(url);
  });

  it.each([
    "http://retroachievements.org/x",
    "https://gamefaqs.gamespot.com/guide",
    "https://github.com/other/guides",
    "https://retroachievements.org.evil.example/",
    "https://u:p@retroachievements.org/",
    "https://retroachievements.org:444/",
    "not a url",
  ])("refuses %s", (url) => {
    expect(openRetroAchievementsPage(url)).toBe(false);
    expect(Navigation.NavigateToExternalWeb).not.toHaveBeenCalled();
  });
});
