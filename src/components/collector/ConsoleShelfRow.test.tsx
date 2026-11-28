import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { navigate } from "../../test-utils/collectorUiMock";
import { ConsoleShelfRow, SHELF_TITLE } from "./ConsoleShelfRow";
import { getConsoleShelf, getFamilyArt } from "../../api/backend";
import { refreshConsoleShelf, resetConsoleShelfStore, setHomeShelfEnabled } from "../../utils/consoleShelfStore";
import type { ShelfConsole } from "../../types";

vi.mock("@decky/ui", async () => (await import("../../test-utils/collectorUiMock")).collectorUiMock());
vi.mock("../../api/backend", () => ({ getConsoleShelf: vi.fn(), getFamilyArt: vi.fn(), logWarn: vi.fn() }));

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
  { platform_slug: "arcade", name: "Arcade", game_count: 2, last_played: null, play_seconds: 0, cover_app_id: 9004 },
];

/** Generated stand-ins for the pack's files: a family's logo only where `withLogo` says so. */
function packArt(withLogo: readonly string[]) {
  vi.mocked(getFamilyArt).mockImplementation((family, kind) =>
    Promise.resolve({
      success: true,
      family,
      kind,
      base64: withLogo.includes(family) ? btoa(`${family}-${kind}`) : null,
    }),
  );
}

async function load(list: ShelfConsole[], enabled = true) {
  vi.mocked(getConsoleShelf).mockResolvedValue({ success: true, enabled, consoles: list });
  await act(async () => {
    await refreshConsoleShelf();
    for (let i = 0; i < 20; i++) await Promise.resolve();
  });
}

beforeEach(() => {
  resetConsoleShelfStore();
  navigate.mockReset();
  packArt([]);
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
function SteamHome({ withTitle = true, artHero = false }: { withTitle?: boolean; artHero?: boolean }) {
  return (
    <div className="steam-home">
      <div className="steam-recents" data-rect="0,100,1920,400">
        {withTitle && (
          <div data-rect="48,112,300,28" style={{ fontSize: "26px", fontWeight: "700", textTransform: "uppercase" }}>
            Recent games
          </div>
        )}
        <div className="steam-carousel">
          {artHero ? <img alt="" data-rect="0,0,1920,700" /> : null}
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

  it("renders one wide tile per family present, in shelf order, and no game art, counts or last played", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    expect(screen.getByText(SHELF_TITLE)).toBeInTheDocument();
    expect(document.querySelector(".tc-shelf__title svg")).not.toBeNull();
    const tiles = document.querySelectorAll(".tc-family");
    expect([...tiles].map((t) => t.getAttribute("data-family"))).toEqual(["playstation", "nintendo", "retro"]);
    expect(document.querySelector(".tc-shelf")?.textContent).not.toMatch(/\d+ games?|played|ago|yesterday/i);
    expect(document.querySelector(".tc-tile, .tc-media, .tc-tile__art")).toBeNull();
    expect(document.querySelector(".tc-shelf__row")?.getAttribute("data-flow")).toBe("row");
    expect(document.querySelector("style")?.textContent).toContain("aspect-ratio:16/9");
  });

  it("shows the pack's hero, dimmed, and the logo centred over it, with the family tone along the bottom", async () => {
    packArt(["nintendo"]);
    render(<ConsoleShelfRow />);
    await load(consoles);
    const tile = document.querySelector('[data-family="nintendo"]')!;
    expect(tile.querySelector("img.tc-family__hero")).toHaveAttribute(
      "src",
      `data:image/png;base64,${btoa("nintendo-hero")}`,
    );
    expect(tile.querySelector("img.tc-family__logo")).toHaveAttribute("alt", "Nintendo");
    expect(tile.querySelector(".tc-family__name")).toBeNull();
    expect((tile.querySelector(".tc-family__tone") as HTMLElement).style.background.toLowerCase()).toBe("#b07a84");
    const css = document.querySelector("style")?.textContent ?? "";
    expect(css).toMatch(/\.tc-family__hero\{[^}]*filter:brightness\(\.5\)/);
    expect(css).toMatch(/\.tc-family__logo\{[^}]*max-width:80%;max-height:36%/);
  });

  it("without the pack's art, draws a gunmetal tile with the family name and the tone strip", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    const tile = document.querySelector('[data-family="retro"]')!;
    expect(tile.querySelector("img")).toBeNull();
    expect(tile.querySelector(".tc-family__name")).toHaveTextContent("Retro");
    expect(tile.querySelector(".tc-family__tone")).not.toBeNull();
  });

  it("focus is a crimson ring with a lift the row has room for, inside the 10px card", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    const css = document.querySelector("style")?.textContent ?? "";
    expect(css).toMatch(
      /\.tc-family\.tc-focus \.tc-family__card[^{]*\{\s*transform:translateY\(-4px\);box-shadow:0 0 0 3px #D7263D\}/,
    );
    expect(css).toMatch(/\.tc-family__card\{[^}]*border-radius:var\(--core-radius-float,10px\)/);
    expect(css).toMatch(/\.tc-shelf__row\{[^}]*padding:16px max\(var\(--tc-inset\),8px\)/);
    expect(css).toMatch(/\.tc-shelf__row\{[^}]*scroll-padding-inline:max\(var\(--tc-inset\),8px\)/);
  });

  it("A opens the Library collection named after the family when there is one", async () => {
    vi.stubGlobal("collectionStore", {
      userCollections: [
        { id: "uc-1", displayName: "PS2" },
        { id: "uc-7", displayName: "playstation" },
      ],
    });
    render(<ConsoleShelfRow />);
    await load(consoles);
    fireEvent.click(screen.getByLabelText("PlayStation"));
    expect(navigate).toHaveBeenCalledWith("/library/collection/uc-7");
  });

  it("A opens the console page of the family's most played console when there is no such collection", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    fireEvent.click(screen.getByLabelText("PlayStation"));
    expect(navigate).toHaveBeenCalledWith("/the-collector/console/ps2");
    fireEvent.click(screen.getByLabelText("Retro"));
    expect(navigate).toHaveBeenLastCalledWith("/the-collector/console/arcade");
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

  it("lines up with Steam's content, not with full-bleed art under Core's Art Hero Home", async () => {
    stubBoxes();
    render(<SteamHome artHero />);
    await load(consoles);
    expect(document.querySelector(".tc-shelf")?.previousElementSibling).toHaveClass("steam-recents");
    expect(shelfStyle().getPropertyValue("--tc-inset")).toBe("48px");
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

  it("falls back to its own geometry when there is no Steam row to measure", async () => {
    render(<ConsoleShelfRow />);
    await load(consoles);
    expect(document.querySelector(".tc-shelf")).toHaveAttribute("data-geometry", "fallback");
    expect(shelfStyle().getPropertyValue("--tc-capsule-h")).toBe("240px");
    expect(document.querySelector("style")?.textContent).toContain("height:calc(var(--tc-capsule-h) * .82)");
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
