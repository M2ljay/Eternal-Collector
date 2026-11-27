import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { showContextMenu, showModal } from "@decky/ui";
import type { ReactElement } from "react";
import * as backend from "../api/backend";
import { AchievementsTab } from "./AchievementsTab";
import { setRommConnectionState } from "../utils/connectionState";
import type { Achievement, AchievementJournal, AchievementGoal } from "../types";

const achievement = (ra_id: number, badge_id: string, title: string): Achievement => ({
  ra_id,
  badge_id,
  title,
  description: `${title} description`,
  points: 10,
  badge_url: `http://example/${badge_id}.png`,
  badge_url_lock: `http://example/${badge_id}-lock.png`,
  display_order: ra_id,
  type: "",
  num_awarded: 0,
  num_awarded_hardcore: 0,
});

const goal = (achievement_id: number, title: string, overrides: Partial<AchievementGoal> = {}): AchievementGoal => ({
  achievement_id,
  title,
  description: "",
  points: 10,
  pinned_at: "2026-11-26T10:00:00Z",
  unlocked_at: null,
  unlocked_hardcore: false,
  ...overrides,
});

const journal = (goals: AchievementGoal[] = [], notes = ""): AchievementJournal => ({
  success: true,
  ra_game_id: 77,
  game_title: "Sonic",
  notes,
  notes_updated_at: notes ? "2026-11-26T10:00:00Z" : null,
  goals,
  game_url: "https://retroachievements.org/game/77",
  web_api_configured: false,
});

/** Click the first item of the last context menu opened, by its label. */
async function chooseMenuItem(label: string) {
  const menu = vi.mocked(showContextMenu).mock.lastCall?.[0] as ReactElement;
  const { getByText, unmount } = render(menu);
  await act(async () => {
    fireEvent.click(getByText(label));
  });
  unmount();
}

beforeEach(() => {
  vi.clearAllMocks();
  setRommConnectionState("connected");
  vi.mocked(backend.getAchievements).mockResolvedValue({
    success: true,
    total: 2,
    achievements: [achievement(1, "b1", "Ring Master"), achievement(2, "b2", "Speed Demon")],
  });
  vi.mocked(backend.getAchievementProgress).mockResolvedValue({
    success: true,
    earned: 1,
    total: 2,
    earned_achievements: [{ id: "b1", date: "2025-02-14 15:45:38", date_hardcore: null }],
  });
  vi.mocked(backend.getAchievementJournal).mockResolvedValue(journal());
  vi.mocked(backend.recordAchievementGoalUnlocks).mockResolvedValue({ success: true, changed: 0 });
  vi.mocked(backend.getAchievementGameLinks).mockResolvedValue({
    success: true,
    game_url: "https://retroachievements.org/game/77",
    guide_url: "https://github.com/RetroAchievements/guides/wiki/Sonic",
    web_api_configured: true,
  });
});

describe("AchievementsTab goals and notes", () => {
  it("pins an achievement from its row menu and marks it as a goal", async () => {
    vi.mocked(backend.pinAchievementGoal).mockResolvedValue(journal([goal(2, "Speed Demon")]));
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    await screen.findByText("Speed Demon");

    fireEvent.click(screen.getByText("Speed Demon"));
    await chooseMenuItem("Pin as goal");

    expect(backend.pinAchievementGoal).toHaveBeenCalledWith(5, {
      achievement_id: 2,
      title: "Speed Demon",
      description: "Speed Demon description",
      points: 10,
    });
    await screen.findByTestId("goal-chip-2");
    expect(screen.getByText("Goals 0/1")).toBeInTheDocument();
  });

  it("removes a goal from its row menu", async () => {
    vi.mocked(backend.getAchievementJournal).mockResolvedValue(journal([goal(2, "Speed Demon")]));
    vi.mocked(backend.unpinAchievementGoal).mockResolvedValue(journal());
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    await screen.findByTestId("goal-chip-2");

    fireEvent.click(screen.getByText("Speed Demon"));
    await chooseMenuItem("Remove goal");

    expect(backend.unpinAchievementGoal).toHaveBeenCalledWith(5, 2);
    await waitFor(() => expect(screen.queryByTestId("goal-chip-2")).not.toBeInTheDocument());
  });

  it("shows the goals view ticked from RomM's progress and relays the unlock once", async () => {
    vi.mocked(backend.getAchievementJournal).mockResolvedValue(
      journal([goal(1, "Ring Master"), goal(2, "Speed Demon")]),
    );
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    fireEvent.click(await screen.findByText("Goals 1/2"));

    expect(await screen.findByTestId("goals-view")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Unlocked")).toHaveLength(1);
    expect(screen.getAllByLabelText("Not unlocked yet")).toHaveLength(1);
    await waitFor(() =>
      expect(backend.recordAchievementGoalUnlocks).toHaveBeenCalledWith(5, [
        { achievement_id: 1, unlocked_at: "2025-02-14 15:45:38", hardcore: false },
      ]),
    );
    expect(backend.recordAchievementGoalUnlocks).toHaveBeenCalledTimes(1);
  });

  it("keeps goals and notes usable while RomM is offline", async () => {
    setRommConnectionState("offline");
    vi.mocked(backend.getAchievementJournal).mockResolvedValue(journal([goal(2, "Speed Demon")], "spin dash"));
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);

    expect(await screen.findByText("RomM offline — achievements unavailable.")).toBeInTheDocument();
    expect(backend.getAchievements).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Notes •"));
    expect(await screen.findByText("spin dash")).toBeInTheDocument();
  });

  it("notes view shows the links and opens the editor", async () => {
    vi.mocked(backend.getAchievementJournal).mockResolvedValue(journal([], "spin dash"));
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    fireEvent.click(await screen.findByText("Notes •"));

    expect(await screen.findByText("Game guide")).toBeInTheDocument();
    expect(screen.getByText("Game on RetroAchievements")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Edit notes"));
    expect(showModal).toHaveBeenCalledTimes(1);
  });

  it("surfaces a journal load failure instead of hiding it", async () => {
    vi.mocked(backend.getAchievementJournal).mockRejectedValue(new Error("boom"));
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    expect(await screen.findByTestId("journal-error")).toHaveTextContent("Goals and notes could not be loaded.");
    expect(backend.debugLog).toHaveBeenCalledWith(expect.stringContaining("Failed to load achievement journal"));
  });

  it("shows a pin refusal from the backend", async () => {
    vi.mocked(backend.pinAchievementGoal).mockResolvedValue({
      success: false,
      reason: "invalid_achievement",
      message: "a game holds at most 100 goals",
    });
    render(<AchievementsTab romId={5} raId={77} isActive={true} />);
    fireEvent.click(await screen.findByText("Speed Demon"));
    await chooseMenuItem("Pin as goal");
    expect(await screen.findByTestId("journal-error")).toHaveTextContent("a game holds at most 100 goals");
  });
});
