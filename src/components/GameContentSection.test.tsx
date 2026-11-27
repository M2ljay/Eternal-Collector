import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { GameContentSection, contentSummary } from "./GameContentSection";
import * as backend from "../api/backend";
import { showModsModal } from "./ModsModal";
import type { GameModsInfo, ModTarget } from "../types";

vi.mock("../api/backend", () => ({ getGameMods: vi.fn(), logError: vi.fn() }));
vi.mock("./ModsModal", () => ({ showModsModal: vi.fn() }));

function target(overrides: Partial<ModTarget>): ModTarget {
  return {
    target_id: "content",
    label: "Updates & DLC (.cia)",
    scope: "install",
    path: "C:\\Azahar\\user\\sdmc",
    exists: true,
    game_folder: null,
    notes: ["Installed by Azahar itself."],
    installed: [],
    installed_truncated: false,
    setting: null,
    accepts: "cia_file",
    kind: "update",
    file_name: null,
    ...overrides,
  };
}

function answer(targets: ModTarget[]): GameModsInfo {
  return { success: true, emulator: null, game_id: null, targets, omitted: [], note: null };
}

const flush = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

beforeEach(() => {
  vi.mocked(backend.getGameMods).mockReset();
  vi.mocked(showModsModal).mockReset();
  vi.mocked(backend.logError).mockReset();
});

describe("GameContentSection", () => {
  it("lists update and DLC targets with what is installed, and opens the narrowed Mods panel", async () => {
    vi.mocked(backend.getGameMods).mockResolvedValue(
      answer([
        target({ installed: [{ name: "Update", is_dir: true, size: 10, files: 1, modified: 1, partial: false }] }),
        target({ target_id: "textures", label: "Texture pack", kind: "files", scope: "game" }),
        target({ target_id: "dlc", label: "DLC", kind: "dlc", scope: "readonly", accepts: "none" }),
      ]),
    );
    const { container, getByText } = render(<GameContentSection romId={7} romName="Mario Kart 7" />);
    await flush();
    expect(container.textContent).toContain("Updates & DLC");
    expect(container.textContent).toContain("Installed: Update");
    expect(container.textContent).toContain("None found.");
    expect(container.textContent).not.toContain("Texture pack");
    fireEvent.click(getByText("Manage"));
    expect(showModsModal).toHaveBeenCalledWith(7, "Mario Kart 7", ["update", "dlc"]);
    expect(getByText("Details")).toBeTruthy();
  });

  it("renders nothing without content targets or when mods are unsupported", async () => {
    vi.mocked(backend.getGameMods).mockResolvedValue({ success: false, reason: "unsupported", message: "x" });
    const { container } = render(<GameContentSection romId={7} romName="x" />);
    await flush();
    expect(container.textContent).toBe("");
  });

  it("logs a failed read and renders nothing", async () => {
    vi.mocked(backend.getGameMods).mockRejectedValue(new Error("socket"));
    const { container } = render(<GameContentSection romId={7} romName="x" />);
    await flush();
    expect(container.textContent).toBe("");
    expect(backend.logError).toHaveBeenCalledWith("GameContentSection: getGameMods failed: Error: socket");
  });

  it("summarises", () => {
    expect(contentSummary(target({}))).toBe("Nothing installed yet.");
  });
});
