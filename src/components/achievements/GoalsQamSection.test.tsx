import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as backend from "../../api/backend";
import { GoalsQamSection, QAM_GOAL_LIMIT } from "./GoalsQamSection";
import type { OverviewGoal } from "../../types";

const goal = (achievement_id: number, unlocked_at: string | null = null): OverviewGoal => ({
  achievement_id,
  title: `Goal ${achievement_id}`,
  description: "",
  points: 5,
  pinned_at: "2026-11-26T10:00:00Z",
  unlocked_at,
  unlocked_hardcore: false,
  ra_game_id: 77,
  game_title: "Sonic",
  app_id: null,
  rom_id: 1,
  achievement_url: "",
});

beforeEach(() => vi.clearAllMocks());

describe("GoalsQamSection", () => {
  it("shows at most three open goals and opens the page", async () => {
    vi.mocked(backend.getAchievementGoals).mockResolvedValue({
      success: true,
      goals: [goal(1), goal(2), goal(3), goal(4), goal(5, "2026-11-01T00:00:00Z")],
      open_count: 4,
      web_api_configured: false,
    });
    const onOpen = vi.fn();
    render(<GoalsQamSection onOpen={onOpen} />);
    expect(await screen.findByText("Goal 1")).toBeInTheDocument();
    expect(screen.getAllByText(/^Goal \d$/)).toHaveLength(QAM_GOAL_LIMIT);
    expect(screen.queryByText("Goal 5")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("All goals and unlock timeline"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("renders nothing without open goals", async () => {
    vi.mocked(backend.getAchievementGoals).mockResolvedValue({
      success: true,
      goals: [goal(5, "2026-11-01T00:00:00Z")],
      open_count: 0,
      web_api_configured: false,
    });
    const { container } = render(<GoalsQamSection onOpen={vi.fn()} />);
    await waitFor(() => expect(backend.getAchievementGoals).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("logs a failed load and stays hidden", async () => {
    vi.mocked(backend.getAchievementGoals).mockRejectedValue(new Error("down"));
    const { container } = render(<GoalsQamSection onOpen={vi.fn()} />);
    await waitFor(() =>
      expect(backend.debugLog).toHaveBeenCalledWith(expect.stringContaining("Failed to load goals for the QAM")),
    );
    expect(container).toBeEmptyDOMElement();
  });
});
