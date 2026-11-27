import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { Navigation, showContextMenu } from "@decky/ui";
import type { ReactElement } from "react";
import * as backend from "../api/backend";
import { AchievementsPage, NO_KEY_LINE } from "./AchievementsPage";
import type { OverviewGoal, TimelineEntry } from "../types";

// Local @decky/ui mock: Field forwards onClick (the rows open their menu on A),
// and DropdownItem renders its options as buttons so a choice is clickable.
vi.mock("@decky/ui", async () => {
  type AnyProps = Record<string, unknown> & { children?: unknown };
  const { createElement: ce } = await import("react");
  const passthrough = (tag: string) => (p: AnyProps) => ce(tag, {}, p.children as never);
  return {
    PanelSection: (p: AnyProps & { title?: unknown }) =>
      ce("section", {}, typeof p.title === "string" ? ce("h3", {}, p.title) : null, p.children as never),
    PanelSectionRow: passthrough("div"),
    ButtonItem: ({ children, onClick, disabled }: AnyProps) => ce("button", { onClick, disabled }, children as never),
    DialogButton: ({ children, onClick }: AnyProps) => ce("button", { onClick }, children as never),
    Field: ({ label, onClick }: AnyProps) => ce("div", { onClick }, label as never),
    DropdownItem: ({
      label,
      rgOptions,
      onChange,
    }: AnyProps & { rgOptions: { data: unknown; label: string }[]; onChange: (o: unknown) => void }) =>
      ce(
        "div",
        { "data-testid": `dropdown-${String(label)}` },
        rgOptions.map((o) =>
          ce("button", { key: String(o.data), onClick: () => onChange(o) }, `${String(label)}: ${o.label}`),
        ),
      ),
    Menu: passthrough("div"),
    MenuItem: ({ children, onClick }: AnyProps) => ce("button", { onClick }, children as never),
    showContextMenu: vi.fn(),
    Navigation: { Navigate: vi.fn(), CloseSideMenus: vi.fn(), NavigateToExternalWeb: vi.fn() },
  };
});

const goal = (achievement_id: number, overrides: Partial<OverviewGoal> = {}): OverviewGoal => ({
  achievement_id,
  title: `Goal ${achievement_id}`,
  description: "",
  points: 10,
  pinned_at: "2026-11-26T10:00:00Z",
  unlocked_at: null,
  unlocked_hardcore: false,
  ra_game_id: 77,
  game_title: "Sonic",
  app_id: 4001,
  rom_id: 1,
  achievement_url: `https://retroachievements.org/achievement/${achievement_id}`,
  ...overrides,
});

const entry = (achievement_id: number, game_id: number, console_name: string, game_title: string): TimelineEntry => ({
  unlocked_at: "2026-11-25T10:00:00Z",
  achievement_id,
  title: `Unlock ${achievement_id}`,
  description: "",
  points: 5,
  hardcore: achievement_id === 1,
  game_id,
  game_title,
  console_name,
  badge_url: "",
});

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
  vi.mocked(backend.getAchievementGoals).mockResolvedValue({
    success: true,
    goals: [goal(1), goal(2, { unlocked_at: "2026-11-20T00:00:00Z", unlocked_hardcore: true })],
    open_count: 1,
    web_api_configured: false,
  });
});

describe("AchievementsPage", () => {
  it("shows goals and the one-line explanation without a Web API key", async () => {
    render(<AchievementsPage onBack={vi.fn()} />);
    expect(await screen.findByText("Goal 1")).toBeInTheDocument();
    expect(screen.getByText("Goals (1 open)")).toBeInTheDocument();
    expect(screen.getByTestId("no-key-line")).toHaveTextContent(NO_KEY_LINE);
    expect(backend.getUnlockTimeline).not.toHaveBeenCalled();
    expect(screen.queryByText("Check goals on RetroAchievements")).not.toBeInTheDocument();
  });

  it("loads the timeline with a key and filters it by game and console", async () => {
    vi.mocked(backend.getAchievementGoals).mockResolvedValue({
      success: true,
      goals: [goal(1)],
      open_count: 1,
      web_api_configured: true,
    });
    vi.mocked(backend.getUnlockTimeline).mockResolvedValue({
      success: true,
      days: 30,
      fetched_at: "2026-11-26T12:00:00Z",
      entries: [
        entry(1, 77, "Genesis/Mega Drive", "Sonic"),
        entry(2, 88, "SNES/Super Famicom", "Zelda"),
        entry(3, 77, "Genesis/Mega Drive", "Sonic"),
      ],
    });
    render(<AchievementsPage onBack={vi.fn()} />);

    expect(await screen.findByText("Unlock 2")).toBeInTheDocument();
    expect(backend.getUnlockTimeline).toHaveBeenCalledWith(30, false);
    expect(screen.getByTestId("timeline-summary")).toHaveTextContent("3 unlocks · 15 points");

    fireEvent.click(screen.getByText("Game: Zelda"));
    expect(screen.queryByText("Unlock 1")).not.toBeInTheDocument();
    expect(screen.getByText("Unlock 2")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Game: All games"));
    fireEvent.click(screen.getByText("Console: Genesis/Mega Drive"));
    expect(screen.queryByText("Unlock 2")).not.toBeInTheDocument();
    expect(screen.getByTestId("timeline-summary")).toHaveTextContent("2 unlocks · 10 points");

    fireEvent.click(screen.getByText("Period: Last year"));
    await waitFor(() => expect(backend.getUnlockTimeline).toHaveBeenCalledWith(365, false));

    fireEvent.click(screen.getByText("Refresh timeline"));
    await waitFor(() => expect(backend.getUnlockTimeline).toHaveBeenCalledWith(365, true));
  });

  it("reports a refused key on the timeline", async () => {
    vi.mocked(backend.getAchievementGoals).mockResolvedValue({
      success: true,
      goals: [],
      open_count: 0,
      web_api_configured: true,
    });
    vi.mocked(backend.getUnlockTimeline).mockResolvedValue({
      success: false,
      reason: "auth_failed",
      message: "RetroAchievements refused the Web API key.",
    });
    render(<AchievementsPage onBack={vi.fn()} />);
    expect(await screen.findByText("RetroAchievements refused the Web API key.")).toBeInTheDocument();
  });

  it("checks goals and reports how many were ticked off", async () => {
    vi.mocked(backend.getAchievementGoals).mockResolvedValue({
      success: true,
      goals: [goal(1)],
      open_count: 1,
      web_api_configured: true,
    });
    vi.mocked(backend.getUnlockTimeline).mockResolvedValue({
      success: true,
      days: 30,
      fetched_at: "x",
      entries: [],
    });
    vi.mocked(backend.refreshAchievementGoals).mockResolvedValue({
      success: true,
      goals: [goal(1, { unlocked_at: "2026-11-26T11:00:00Z" })],
      open_count: 0,
      web_api_configured: true,
      changed: 1,
      refreshed: 1,
      failed: 0,
    });
    render(<AchievementsPage onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("Check goals on RetroAchievements"));
    expect(await screen.findByTestId("goal-status")).toHaveTextContent("1 goal unlocked");
  });

  it("a goal's menu opens its game and removes it", async () => {
    vi.mocked(backend.unpinAchievementGoal).mockResolvedValue({
      success: true,
      ra_game_id: 77,
      game_title: "Sonic",
      notes: "",
      notes_updated_at: null,
      goals: [],
    });
    render(<AchievementsPage onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("Goal 1"));
    await chooseMenuItem("Open game");
    expect(Navigation.Navigate).toHaveBeenCalledWith("/library/app/4001");

    fireEvent.click(screen.getByText("Goal 1"));
    await chooseMenuItem("Remove goal");
    expect(backend.unpinAchievementGoal).toHaveBeenCalledWith(1, 1);
  });

  it("logs and shows a goals load failure", async () => {
    vi.mocked(backend.getAchievementGoals).mockRejectedValue(new Error("down"));
    render(<AchievementsPage onBack={vi.fn()} />);
    expect(await screen.findByTestId("goal-status")).toHaveTextContent("Goals could not be loaded.");
    expect(backend.debugLog).toHaveBeenCalledWith(expect.stringContaining("Failed to load goals"));
  });
});
