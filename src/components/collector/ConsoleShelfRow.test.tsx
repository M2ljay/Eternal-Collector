import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
    cover_app_id: 9001,
  },
  { platform_slug: "ngc", name: "GameCube", game_count: 1, last_played: null, play_seconds: 0, cover_app_id: 9002 },
  { platform_slug: "psx", name: "PlayStation", game_count: 3, last_played: null, play_seconds: 0, cover_app_id: 9003 },
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/**
 * A stand-in for the DOM Steam renders on Home: the Recent games row (title, a
 * landscape hero, then portrait capsules) with The Collector inserted right after
 * it, then another Steam row. Every box is given by `data-rect="left,top,width,height"`.
 */
function SteamHome({ withTitle = true }: { withTitle?: boolean }) {
  return (
    <div className="steam-home">
      <div className="steam-recents" data-rect="0,100,1920,400">
        {withTitle && (
          <div data-rect="48,112,300,28" style={{ fontSize: "26px", fontWeight: "700", textTransform: "uppercase" }}>
            Recent games
          </div>
        )}
        <div className="steam-carousel">
          <img alt="" data-rect="48,160,560,300" />
          <img alt="" data-rect="624,160,200,300" />
          <img alt="" data-rect="840,160,200,300" />
          <img alt="" data-rect="1056,160,200,300" />
        </div>
      </div>
      <ConsoleShelfRow />
      <div className="steam-next" data-rect="0,900,1920,300">
        <div data-rect="48,910,200,24" style={{ fontSize: "22px", letterSpacing: "1px" }}>
          What&apos;s new
        </div>
      </div>
    </div>
  );
}

function stubBoxes() {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const [left, top, width, height] = (this.getAttribute("data-rect") ?? "0,0,0,0").split(",").map(Number) as [
      number,
      number,
      number,
      number,
    ];
    return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top } as DOMRect;
  });
}

function shelfStyle(): CSSStyleDeclaration {
  return (document.querySelector(".tc-shelf") as HTMLElement).style;
}

describe("ConsoleShelfRow", () => {
  it("renders nothing before the shelf has loaded", () => {
    const { container } = render(<ConsoleShelfRow />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one tile per console in the backend's order, with the name only and no count or last played", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    expect(screen.getByText(SHELF_TITLE)).toBeInTheDocument();
    const tiles = document.querySelectorAll(".tc-tile");
    expect([...tiles].map((t) => t.getAttribute("data-platform"))).toEqual(["ps2", "ngc", "psx"]);
    expect(tiles[0]).toHaveTextContent("PlayStation 2");
    for (const tile of tiles) {
      expect(tile.textContent).not.toMatch(/\bgames?\b|played|ago|tonight|today|yesterday|week|month|year/i);
      expect(tile.querySelector(".tc-tile__meta")).toBeNull();
    }
    expect(document.querySelector(".tc-shelf")?.textContent).not.toMatch(/\d+ games?/);
    expect(tiles[0]!.querySelector("[data-media-kind]")?.getAttribute("data-media-kind")).toBe("dvd-case");
    expect(tiles[0]!.querySelectorAll(".tc-media__item")).toHaveLength(6);
    expect(tiles[1]!.querySelector("[data-media-kind]")?.getAttribute("data-media-kind")).toBe("gc-box");
    expect(document.querySelector(".tc-shelf__row")?.getAttribute("data-flow")).toBe("row");
  });

  it("A on a tile opens that console's page", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    fireEvent.click(screen.getByLabelText("GameCube"));
    expect(navigate).toHaveBeenCalledWith("/the-collector/console/ngc");
  });

  it("shows the console's name only while its capsule has focus", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    const css = document.querySelector("style")?.textContent ?? "";
    expect(css).toMatch(/\.tc-tile__label\{[^}]*opacity:0/);
    expect(css).toContain(".tc-tile.tc-focus .tc-tile__label");
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

describe("ConsoleShelfRow on Steam's Home", () => {
  it("shows Steam's own capsule art for each console's cover game", async () => {
    vi.stubGlobal("appStore", {
      GetAppOverviewByAppID: (id: number) => ({ appid: id, rt_custom_image_mtime: 42 }),
      GetCustomVerticalCapsuleURLs: (o: { appid: number }) => [`/customimages/${o.appid}p.png?v=42`],
      GetVerticalCapsuleURLForApp: () => "",
    });
    render(<ConsoleShelfRow />);
    await load(consoles);
    const art = [...document.querySelectorAll("img.tc-tile__art")].map((i) => i.getAttribute("src"));
    expect(art).toEqual([
      "/customimages/9001p.png?v=42",
      "/customimages/9002p.png?v=42",
      "/customimages/9003p.png?v=42",
    ]);
  });

  it("keeps the console's media stack under the art and drops an image that fails to load", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    const tile = document.querySelector('[data-platform="ngc"]')!;
    const img = () => tile.querySelector("img.tc-tile__art");
    expect(img()).toHaveAttribute("src", "/customimages/9002p.png");
    fireEvent.error(img()!);
    expect(img()).toHaveAttribute("src", "/customimages/9002p.jpg");
    fireEvent.error(img()!);
    expect(img()).toBeNull();
    expect(tile.querySelector("[data-media-kind]")?.getAttribute("data-media-kind")).toBe("gc-box");
    expect(tile.querySelector(".tc-tile__name")).toHaveTextContent("GameCube");
  });

  it("takes inset, capsule height, gap, spacing and title type from Steam's Recent games row", async () => {
    stubBoxes();
    render(<SteamHome />);
    await load(consoles);
    const shelf = document.querySelector(".tc-shelf")!;
    expect(shelf.previousElementSibling).toHaveClass("steam-recents");
    expect(shelf).toHaveAttribute("data-geometry", "steam");
    const style = shelfStyle();
    expect(style.getPropertyValue("--tc-inset")).toBe("48px");
    expect(style.getPropertyValue("--tc-capsule-h")).toBe("300px");
    expect(style.getPropertyValue("--tc-gap")).toBe("16px");
    expect(style.getPropertyValue("--tc-pad-top")).toBe("12px");
    expect(style.getPropertyValue("--tc-title-gap")).toBe("20px");
    expect(style.getPropertyValue("--tc-pad-bottom")).toBe("40px");
    expect(style.getPropertyValue("--tc-title-size")).toBe("26px");
    expect(style.getPropertyValue("--tc-title-weight")).toBe("700");
    expect(style.getPropertyValue("--tc-title-tt")).toBe("uppercase");
  });

  it("borrows the title type from a later Steam row when Recent games has no title", async () => {
    stubBoxes();
    render(<SteamHome withTitle={false} />);
    await load(consoles);
    const style = shelfStyle();
    expect(style.getPropertyValue("--tc-pad-top")).toBe("60px");
    expect(style.getPropertyValue("--tc-inset")).toBe("48px");
    expect(style.getPropertyValue("--tc-title-size")).toBe("22px");
    expect(style.getPropertyValue("--tc-title-ls")).toBe("1px");
  });

  it("falls back to its own 2:3 geometry when there is no Steam row to measure", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    expect(document.querySelector(".tc-shelf")).toHaveAttribute("data-geometry", "fallback");
    expect(shelfStyle().getPropertyValue("--tc-capsule-h")).toBe("240px");
    expect(document.querySelector("style")?.textContent).toContain("aspect-ratio:2/3");
  });

  it("never writes to Steam's elements", async () => {
    stubBoxes();
    render(<SteamHome />);
    const recents = document.querySelector(".steam-recents")!;
    const before = recents.outerHTML;
    await load(consoles);
    expect(recents.outerHTML).toBe(before);
  });
});
