import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { navigate, params } from "../../test-utils/collectorUiMock";
import { ConsolePage, snapshotIsStale, ACHIEVEMENTS_MAX_AGE_MS } from "./ConsolePage";
import { achievementChips, saveChip } from "./GameCase";
import { getConsoleGames, logWarn, refreshConsoleAchievements } from "../../api/backend";
import type { ConsoleGame, ConsoleGamesPage } from "../../types";

vi.mock("@decky/ui", async () => (await import("../../test-utils/collectorUiMock")).collectorUiMock());
vi.mock("../../api/backend", () => ({
  getConsoleGames: vi.fn(),
  refreshConsoleAchievements: vi.fn(),
  logWarn: vi.fn(),
}));

function game(rom_id: number, over: Partial<ConsoleGame> = {}): ConsoleGame {
  return {
    rom_id,
    app_id: 5000 + rom_id,
    name: `Game ${rom_id}`,
    last_played: null,
    play_seconds: 0,
    installed: true,
    save_sync: null,
    achievements: null,
    has_ra_set: false,
    ...over,
  };
}

function page(games: ConsoleGame[], over: Partial<ConsoleGamesPage> = {}): ConsoleGamesPage {
  return {
    success: true,
    platform_slug: "ps2",
    name: "PlayStation 2",
    total: games.length,
    offset: 0,
    continue_rom_id: null,
    save_sync_enabled: true,
    achievements_fetched_at: new Date().toISOString(),
    games,
    ...over,
  };
}

async function settle() {
  await act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  });
}

beforeEach(() => {
  params.value = { slug: "ps2" };
  navigate.mockReset();
  vi.mocked(getConsoleGames).mockReset();
  vi.mocked(refreshConsoleAchievements).mockReset();
  vi.mocked(logWarn).mockReset();
});

describe("ConsolePage", () => {
  it("shows Continue first, then the rest, in the console's media style, with chips", async () => {
    const okami = game(2, {
      name: "Okami",
      last_played: new Date().toISOString(),
      save_sync: { status: "synced", label: null, last_sync_check_at: "2026-11-25T00:00:00Z" },
      achievements: { earned: 12, total: 40, earned_hardcore: 12, hardcore: true, award: null, fetched_at: "t" },
      has_ra_set: true,
    });
    const ape = game(3, { name: "Ape Escape", installed: false, has_ra_set: true });
    vi.mocked(getConsoleGames).mockResolvedValue(page([okami, ape], { continue_rom_id: 2 }));

    render(<ConsolePage />);
    await settle();

    expect(getConsoleGames).toHaveBeenCalledWith("ps2", 0, 100);
    expect(screen.getByRole("heading", { name: "PlayStation 2" })).toBeInTheDocument();
    expect(screen.getByText("2 games")).toBeInTheDocument();
    const cases = document.querySelectorAll(".tc-case");
    expect([...cases].map((c) => c.getAttribute("data-rom-id"))).toEqual(["2", "3"]);
    expect(cases[0]).toHaveClass("tc-case--continue", "tc-case--dvd-case");
    expect(cases[0]).toHaveAttribute("data-preferred-focus", "true");
    expect(cases[1]).not.toHaveAttribute("data-preferred-focus");
    expect(cases[0]).toHaveTextContent("Saves synced");
    expect(cases[0]).toHaveTextContent("12 / 40");
    expect(cases[0]).toHaveTextContent("Hardcore");
    expect(cases[1]).toHaveTextContent("No progress yet");
    expect(cases[1]).toHaveTextContent("Not played yet · Not downloaded");
    expect(screen.getByText("Continue")).toBeInTheDocument();
  });

  it("A on a game opens its game page", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue(page([game(1, { name: "Ico" })]));
    render(<ConsolePage />);
    await settle();
    fireEvent.click(screen.getByLabelText("Ico"));
    expect(navigate).toHaveBeenCalledWith("/library/app/5001");
  });

  it("without a Continue game the first case takes the initial focus and rows hold six cases", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue(page(Array.from({ length: 8 }, (_, i) => game(i + 1))));
    render(<ConsolePage />);
    await settle();
    expect(screen.queryByText("Continue")).toBeNull();
    const rows = document.querySelectorAll(".tc-grid .tc-grid__row");
    expect([...rows].map((r) => r.querySelectorAll(".tc-case").length)).toEqual([6, 2]);
    expect(document.querySelector(".tc-case")).toHaveAttribute("data-preferred-focus", "true");
  });

  it("falls back to the title when Steam has no cover", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue(page([game(1, { name: "Ico" })]));
    render(<ConsolePage />);
    await settle();
    const img = () => document.querySelector("img.tc-case__art");
    expect(img()).toHaveAttribute("src", "/customimages/5001p.png");
    fireEvent.error(img()!);
    expect(img()).toHaveAttribute("src", "/customimages/5001p.jpg");
    fireEvent.error(img()!);
    expect(img()).toBeNull();
    expect(document.querySelector(".tc-case__fallback")).toHaveTextContent("Ico");
  });

  it("pages with Show more", async () => {
    vi.mocked(getConsoleGames)
      .mockResolvedValueOnce(page([game(1)], { total: 2 }))
      .mockResolvedValueOnce(page([game(2)], { total: 2, offset: 1 }));
    render(<ConsolePage />);
    await settle();
    fireEvent.click(screen.getByText("Show more (1 left)"));
    await settle();
    expect(getConsoleGames).toHaveBeenLastCalledWith("ps2", 1, 100);
    expect(document.querySelectorAll(".tc-case")).toHaveLength(2);
    expect(screen.queryByText(/Show more/)).toBeNull();
  });

  it("says so when the console has no games", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue(page([]));
    render(<ConsolePage />);
    await settle();
    expect(screen.getByRole("status")).toHaveTextContent("No games from this console are in Steam.");
  });

  it("shows the backend's failure message", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue({
      success: false,
      reason: "invalid_platform",
      message: "A console is required",
    });
    render(<ConsolePage />);
    await settle();
    expect(screen.getByRole("status")).toHaveTextContent("A console is required");
  });

  it("a rejected read shows an error and logs it", async () => {
    vi.mocked(getConsoleGames).mockRejectedValue(new Error("bridge down"));
    render(<ConsolePage />);
    await settle();
    expect(screen.getByRole("status")).toHaveTextContent("Could not load this console.");
    expect(logWarn).toHaveBeenCalledWith("The Collector: console page read failed for ps2: bridge down");
  });

  it("refreshes a stale achievement snapshot once and re-reads the page", async () => {
    const stale = page([game(1, { has_ra_set: true })], { achievements_fetched_at: null });
    const fresh = page([
      game(1, {
        has_ra_set: true,
        achievements: { earned: 1, total: 9, earned_hardcore: 0, hardcore: false, award: null, fetched_at: "t" },
      }),
    ]);
    vi.mocked(getConsoleGames).mockResolvedValueOnce(stale).mockResolvedValueOnce(fresh);
    vi.mocked(refreshConsoleAchievements).mockResolvedValue({ success: true, refreshed_at: "t" });
    render(<ConsolePage />);
    await settle();
    await waitFor(() => expect(document.querySelector(".tc-case")).toHaveTextContent("1 / 9"));
    expect(refreshConsoleAchievements).toHaveBeenCalledTimes(1);
    expect(getConsoleGames).toHaveBeenCalledTimes(2);
  });

  it("does not refresh when no game has a set, and logs a rejected refresh", async () => {
    vi.mocked(getConsoleGames).mockResolvedValue(page([game(1)], { achievements_fetched_at: null }));
    render(<ConsolePage />);
    await settle();
    expect(refreshConsoleAchievements).not.toHaveBeenCalled();

    params.value = { slug: "snes" };
    vi.mocked(getConsoleGames).mockResolvedValue(
      page([game(2, { has_ra_set: true })], { achievements_fetched_at: null }),
    );
    vi.mocked(refreshConsoleAchievements).mockRejectedValue(new Error("offline"));
    render(<ConsolePage />);
    await settle();
    expect(refreshConsoleAchievements).toHaveBeenCalledTimes(1);
    expect(logWarn).toHaveBeenCalledWith("The Collector: achievement refresh failed: offline");
  });

  it("drops an answer that arrives after the page was left", async () => {
    let release: (v: ConsoleGamesPage) => void = () => {};
    vi.mocked(getConsoleGames).mockImplementation(() => new Promise((resolve) => (release = resolve)));
    const { unmount } = render(<ConsolePage />);
    unmount();
    await act(async () => {
      release(page([game(1)]));
      await Promise.resolve();
    });
    expect(document.querySelector(".tc-case")).toBeNull();
  });
});

describe("snapshotIsStale", () => {
  it("is stale when missing, unparseable or older than the limit", () => {
    const now = Date.parse("2026-11-26T12:00:00Z");
    expect(snapshotIsStale(null, now)).toBe(true);
    expect(snapshotIsStale("junk", now)).toBe(true);
    expect(snapshotIsStale(new Date(now - ACHIEVEMENTS_MAX_AGE_MS - 1).toISOString(), now)).toBe(true);
    expect(snapshotIsStale(new Date(now - 60_000).toISOString(), now)).toBe(false);
  });
});

describe("chips", () => {
  it("save chip reflects the cached display and is absent with save sync off", () => {
    expect(saveChip(game(1), false)).toBeNull();
    expect(saveChip(game(1), true)).toEqual({ text: "No saves yet", tone: "plain" });
    expect(
      saveChip(game(1, { save_sync: { status: "pending", label: "Local changes", last_sync_check_at: null } }), true),
    ).toEqual({
      text: "Local changes",
      tone: "pending",
    });
    expect(
      saveChip(game(1, { save_sync: { status: "conflict", label: null, last_sync_check_at: null } }), true),
    ).toEqual({
      text: "Save conflict",
      tone: "conflict",
    });
    expect(
      saveChip(game(1, { save_sync: { status: "none", label: "No local saves", last_sync_check_at: null } }), true),
    ).toEqual({
      text: "No local saves",
      tone: "plain",
    });
  });

  it("achievement chips show progress, hardcore and the award", () => {
    expect(achievementChips(game(1))).toEqual([]);
    expect(
      achievementChips(
        game(1, {
          achievements: {
            earned: 40,
            total: 40,
            earned_hardcore: 40,
            hardcore: true,
            award: "mastered",
            fetched_at: "t",
          },
        }),
      ).map((c) => c.text),
    ).toEqual(["40 / 40", "Hardcore", "Mastered"]);
  });
});
