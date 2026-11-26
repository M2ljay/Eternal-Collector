import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { navigate } from "../../test-utils/collectorUiMock";
import { ConsoleShelfRow, SHELF_TITLE } from "./ConsoleShelfRow";
import { getConsoleShelf } from "../../api/backend";
import { refreshConsoleShelf, resetConsoleShelfStore, setHomeShelfEnabled } from "../../utils/consoleShelfStore";
import type { ShelfConsole } from "../../types";

vi.mock("@decky/ui", async () => (await import("../../test-utils/collectorUiMock")).collectorUiMock());
vi.mock("../../api/backend", () => ({ getConsoleShelf: vi.fn(), logWarn: vi.fn() }));

const consoles: ShelfConsole[] = [
  {
    platform_slug: "ps2",
    name: "PlayStation 2",
    game_count: 14,
    last_played: new Date().toISOString(),
    play_seconds: 1,
  },
  { platform_slug: "ngc", name: "GameCube", game_count: 1, last_played: null, play_seconds: 0 },
  { platform_slug: "psx", name: "PlayStation", game_count: 3, last_played: null, play_seconds: 0 },
];

async function load(list: ShelfConsole[], enabled = true) {
  vi.mocked(getConsoleShelf).mockResolvedValue({ success: true, enabled, consoles: list });
  await act(async () => {
    await refreshConsoleShelf();
  });
}

beforeEach(() => {
  resetConsoleShelfStore();
  navigate.mockReset();
});

describe("ConsoleShelfRow", () => {
  it("renders nothing before the shelf has loaded", () => {
    const { container } = render(<ConsoleShelfRow />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one tile per console in the backend's order, with name, count and last played", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    expect(screen.getByText(SHELF_TITLE)).toBeInTheDocument();
    const tiles = document.querySelectorAll(".tc-tile");
    expect([...tiles].map((t) => t.getAttribute("data-platform"))).toEqual(["ps2", "ngc", "psx"]);
    expect(tiles[0]).toHaveTextContent("PlayStation 2");
    expect(tiles[0]).toHaveTextContent(/14 games · Played (tonight|today)/);
    expect(tiles[1]).toHaveTextContent("1 game · Not played yet");
    expect(tiles[0]!.querySelector("[data-media-kind]")?.getAttribute("data-media-kind")).toBe("dvd-case");
    expect(tiles[0]!.querySelectorAll(".tc-media__item")).toHaveLength(6);
    expect(tiles[1]!.querySelector("[data-media-kind]")?.getAttribute("data-media-kind")).toBe("gc-box");
    expect(document.querySelector(".tc-shelf__row")?.getAttribute("data-flow")).toBe("row");
  });

  it("A on a tile opens that console's page", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    fireEvent.click(screen.getByLabelText("GameCube, 1 game"));
    expect(navigate).toHaveBeenCalledWith("/the-collector/console/ngc");
  });

  it("renders nothing when switched off or when there are no consoles", async () => {
    const { container } = render(<ConsoleShelfRow />);
    await load(consoles, false);
    expect(container).toBeEmptyDOMElement();
    act(() => setHomeShelfEnabled(true));
    expect(container).not.toBeEmptyDOMElement();
    await load([]);
    expect(container).toBeEmptyDOMElement();
  });
});
