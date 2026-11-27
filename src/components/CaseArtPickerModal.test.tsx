import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act, fireEvent } from "@testing-library/react";
import { createElement } from "react";
import { toaster } from "@decky/api";
import * as backend from "../api/backend";
import * as caseArt from "../utils/caseArt";
import { CaseArtPickerModalContent } from "./CaseArtPickerModal";

vi.mock("../utils/caseArt", () => ({ applyCaseArt: vi.fn() }));

const GRIDS: backend.CaseArtGrid[] = [
  { id: 102, thumb: "https://cdn/t/102.png", width: 600, height: 900, author: "Castcoder", score: 3, curated: true },
  { id: 105, thumb: "https://cdn/t/105.jpg", width: 342, height: 482, author: "Legacy", score: 40, curated: false },
];

const flushAsync = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

function renderPicker(closeModal = vi.fn()) {
  return render(
    createElement(CaseArtPickerModalContent, { romId: 41, appId: 5000, romName: "Wind Waker", closeModal }),
  );
}

describe("CaseArtPickerModal", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(backend.debugLog).mockResolvedValue(undefined);
    vi.mocked(backend.listCaseArt).mockResolvedValue({ success: true, grids: GRIDS, selected_grid_id: 105 });
  });

  it("lists every grid as a focusable 2:3 thumbnail, best first, marking the one in use", async () => {
    const { container } = renderPicker();
    await flushAsync();
    const frames = [...container.querySelectorAll("[data-grid-id]")];
    expect(frames.map((t) => t.getAttribute("data-grid-id"))).toEqual(["102", "105"]);
    const tiles = frames.map((f) => f.closest("button"));
    expect(tiles).not.toContain(null);
    expect(tiles[0]?.textContent).toContain("Castcoder · case template");
    expect(tiles[1]?.textContent).toContain("in use");
    expect(tiles[0]!.querySelector("img")?.getAttribute("src")).toBe("https://cdn/t/102.png");
    expect(vi.mocked(backend.listCaseArt)).toHaveBeenCalledWith(41);
  });

  it("A on a grid applies it as a manual pick and closes", async () => {
    vi.mocked(caseArt.applyCaseArt).mockResolvedValue("applied");
    const closeModal = vi.fn();
    const { container } = renderPicker(closeModal);
    await flushAsync();
    await act(async () => {
      fireEvent.click(container.querySelector('[data-grid-id="102"]')!.closest("button")!);
    });
    await flushAsync();
    expect(vi.mocked(caseArt.applyCaseArt)).toHaveBeenCalledWith(41, 5000, { gridId: 102 });
    expect(vi.mocked(toaster.toast)).toHaveBeenCalledWith(expect.objectContaining({ body: "Cover changed" }));
    expect(closeModal).toHaveBeenCalledTimes(1);
  });

  it("a failed apply stays open and says so", async () => {
    vi.mocked(caseArt.applyCaseArt).mockResolvedValue("failed");
    const closeModal = vi.fn();
    const { container } = renderPicker(closeModal);
    await flushAsync();
    await act(async () => {
      fireEvent.click(container.querySelector('[data-grid-id="105"]')!.closest("button")!);
    });
    await flushAsync();
    expect(vi.mocked(toaster.toast)).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Could not apply that artwork" }),
    );
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("explains a missing SteamGridDB game", async () => {
    vi.mocked(backend.listCaseArt).mockResolvedValue({ success: false, reason: "no_sgdb_game", message: "x" });
    const { container } = renderPicker();
    await flushAsync();
    expect(container.textContent).toContain("Run Refresh Artwork first");
  });

  it("a rejected list shows the unreachable message and logs it", async () => {
    vi.mocked(backend.listCaseArt).mockRejectedValue(new Error("socket"));
    const { container } = renderPicker();
    await flushAsync();
    expect(container.textContent).toContain("Could not reach SteamGridDB.");
    expect(vi.mocked(backend.debugLog)).toHaveBeenCalledWith(expect.stringContaining("listCaseArt rejected"));
  });

  it("says when SteamGridDB has no portrait artwork", async () => {
    vi.mocked(backend.listCaseArt).mockResolvedValue({ success: true, grids: [], selected_grid_id: null });
    const { container } = renderPicker();
    await flushAsync();
    expect(container.textContent).toContain("no portrait artwork");
  });
});
