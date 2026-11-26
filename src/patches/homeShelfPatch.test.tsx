import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Component, createElement, forwardRef, memo, type ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { routerHook } from "@decky/api";
import { debugLog, logInfo, logWarn } from "../api/backend";
import {
  HOME_ROUTE,
  MAX_FAILURES,
  RECENTS_ROW_MATCHERS,
  SHELF_KEY,
  describeTree,
  getHomeShelfDiagnostics,
  insertAfterRecentsRow,
  recordShelfFailure,
  registerHomeShelfPatch,
  resetHomeShelfPatchForTests,
  unregisterHomeShelfPatch,
  wrapComponentType,
} from "./homeShelfPatch";
import { resetConsoleShelfStore, setHomeShelfEnabled } from "../utils/consoleShelfStore";

vi.mock("../api/backend", () => ({
  debugLog: vi.fn().mockResolvedValue(undefined),
  logInfo: vi.fn(),
  logWarn: vi.fn(),
  getConsoleShelf: vi.fn(),
}));

const shelfBehaviour = { throws: false };
vi.mock("../components/collector/ConsoleShelfRow", () => ({
  ConsoleShelfRow: () => {
    if (shelfBehaviour.throws) throw new Error("shelf exploded");
    return createElement("section", { "data-testid": "shelf" }, "The Collector");
  },
}));

// A stand-in for Steam's Home: a memo route component rendering the component
// that holds the rows, the second of which is the Recent games row.
const RecentsRow = (_p: { showBackground: boolean; autoFocus: boolean }) => <div data-testid="recents">Recent</div>;
const RecentsCarousel = (_p: { games: number[]; onItemFocus: () => void; showFeaturedItem: boolean }) => (
  <div data-testid="carousel">Carousel</div>
);
const Rows = ({ variant }: { variant: "section" | "carousel" | "none" }) => (
  <div data-testid="rows">
    <div data-testid="hero">Hero</div>
    {variant === "section" && createElement(RecentsRow, { showBackground: false, autoFocus: true })}
    {variant === "carousel" && (
      <div className="wrapper">
        <RecentsCarousel games={[1, 2]} onItemFocus={() => {}} showFeaturedItem={false} />
      </div>
    )}
    <div data-testid="next-row">Next</div>
  </div>
);
const Home = memo(({ variant }: { variant: "section" | "carousel" | "none" }) => (
  <div data-testid="home">
    <Rows variant={variant} />
  </div>
));

type RoutePatchFn = (props: { path: string; children: ReactNode }) => { path: string; children: ReactNode };

function routePatch(): RoutePatchFn {
  const calls = vi.mocked(routerHook.addPatch).mock.calls;
  return calls[calls.length - 1]![1] as unknown as RoutePatchFn;
}

function renderHome(variant: "section" | "carousel" | "none" = "section") {
  const props = routePatch()({ path: HOME_ROUTE, children: <Home variant={variant} /> });
  return { props, ...render(<>{props.children}</>) };
}

function order(): string[] {
  return [...screen.getByTestId("rows").querySelectorAll("[data-testid]")].map((el) => el.getAttribute("data-testid")!);
}

beforeEach(() => {
  resetHomeShelfPatchForTests();
  resetConsoleShelfStore();
  shelfBehaviour.throws = false;
  vi.mocked(routerHook.addPatch).mockClear();
  vi.mocked(routerHook.removePatch).mockClear();
  vi.mocked(logInfo).mockClear();
  vi.mocked(logWarn).mockClear();
  vi.mocked(debugLog).mockClear();
  registerHomeShelfPatch();
});

afterEach(() => {
  resetHomeShelfPatchForTests();
  vi.useRealTimers();
});

describe("Home shelf route patch", () => {
  it("inserts the shelf right after Steam's Recent games row and logs the matcher once", () => {
    const { rerender, props } = renderHome();
    expect(order()).toEqual(["hero", "recents", "shelf", "next-row"]);
    rerender(<>{props.children}</>);
    expect(screen.getAllByTestId("shelf")).toHaveLength(1);
    expect(logInfo).toHaveBeenCalledTimes(1);
    expect(logInfo).toHaveBeenCalledWith(expect.stringContaining('matcher "recents-section"'));
    expect(getHomeShelfDiagnostics().matchedBy).toBe("recents-section");
  });

  it("falls back to the tile-list contract when the section wrapper is not in the output", () => {
    renderHome("carousel");
    const wrapper = document.querySelector(".wrapper")!;
    expect([...wrapper.children].map((c) => c.getAttribute("data-testid"))).toEqual(["carousel", "shelf"]);
    expect(getHomeShelfDiagnostics().matchedBy).toBe("recents-carousel");
  });

  it("leaves Home untouched when switched off", () => {
    setHomeShelfEnabled(false);
    renderHome();
    expect(order()).toEqual(["hero", "recents", "next-row"]);
  });

  it("an unrecognised Home is left as Steam rendered it, and the miss is logged with an outline", async () => {
    vi.useFakeTimers();
    renderHome("none");
    expect(order()).toEqual(["hero", "next-row"]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(logWarn).toHaveBeenCalledWith(expect.stringContaining("Recent games row was not found on Home"));
    expect(vi.mocked(debugLog).mock.calls.some(([line]) => line.includes("The Collector home tree:"))).toBe(true);
  });

  it("a shelf render error is caught: Home stays intact and the failure is counted", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    shelfBehaviour.throws = true;
    renderHome();
    expect(order()).toEqual(["hero", "recents", "next-row"]);
    expect(getHomeShelfDiagnostics().failures).toBe(1);
    expect(logWarn).toHaveBeenCalledWith(expect.stringContaining("Home shelf render failed (1/3): shelf exploded"));
    spy.mockRestore();
  });

  it(`switches itself off after ${MAX_FAILURES} failures and then returns Steam's route untouched`, () => {
    for (let i = 0; i < MAX_FAILURES; i++) recordShelfFailure("render", new Error(`f${i}`));
    expect(getHomeShelfDiagnostics().disabled).toBe(true);
    expect(logWarn).toHaveBeenCalledWith(expect.stringContaining("switched off until the plugin reloads"));
    const input = { path: HOME_ROUTE, children: <Home variant="section" /> };
    expect(routePatch()(input)).toBe(input);
  });

  it("an exception while patching returns the native output and counts a failure", () => {
    RECENTS_ROW_MATCHERS.unshift({
      name: "boom",
      test: () => {
        throw new Error("matcher threw");
      },
    });
    try {
      renderHome();
      expect(order()).toEqual(["hero", "recents", "next-row"]);
      expect(getHomeShelfDiagnostics().failures).toBeGreaterThan(0);
      expect(logWarn).toHaveBeenCalledWith(expect.stringContaining("Home shelf patch failed"));
    } finally {
      RECENTS_ROW_MATCHERS.shift();
    }
  });

  it("register is idempotent and unregister removes the patch", () => {
    registerHomeShelfPatch();
    expect(routerHook.addPatch).toHaveBeenCalledTimes(1);
    unregisterHomeShelfPatch();
    expect(routerHook.removePatch).toHaveBeenCalledWith(HOME_ROUTE, expect.any(Function));
    unregisterHomeShelfPatch();
    expect(routerHook.removePatch).toHaveBeenCalledTimes(1);
  });

  it("a route without children is returned as is", () => {
    const input = { path: HOME_ROUTE, children: undefined as unknown as ReactNode };
    expect(routePatch()(input)).toBe(input);
  });
});

describe("insertAfterRecentsRow", () => {
  const extra = <i key={SHELF_KEY} />;

  it("returns the very same tree when nothing matches", () => {
    const tree = (
      <div>
        <span />
        text
      </div>
    );
    expect(insertAfterRecentsRow(tree, extra)).toEqual({ tree, matchedBy: null });
    expect(insertAfterRecentsRow("plain", extra).matchedBy).toBeNull();
  });

  it("finds the row inside nested arrays and under a single child, copying instead of mutating", () => {
    const rowEl = createElement(RecentsRow, { key: "r", showBackground: true, autoFocus: false });
    const nested = createElement("div", null, [[createElement("p", { key: "p" }), rowEl]]);
    const original = nested.props;
    const { tree, matchedBy } = insertAfterRecentsRow(nested, extra);
    expect(matchedBy).toBe("recents-section");
    expect(tree).not.toBe(nested);
    expect(nested.props).toBe(original);
    const { container } = render(tree);
    expect(container.querySelector("[data-testid=recents] + i")).not.toBeNull();

    const single = createElement("section", null, createElement(RecentsRow, { showBackground: true, autoFocus: true }));
    const out = insertAfterRecentsRow(single, extra);
    expect(render(out.tree).container.querySelector("section > [data-testid=recents] + i")).not.toBeNull();
  });

  it("a matching root gets the shelf as its sibling", () => {
    const rowEl = createElement("b", { showBackground: true, autoFocus: true });
    const out = insertAfterRecentsRow(rowEl, extra);
    expect(Array.isArray(out.tree)).toBe(true);
    expect(out.matchedBy).toBe("recents-section");
  });

  it("never adds a second shelf", () => {
    const tree = createElement("div", null, [
      createElement("b", { key: "r", showBackground: true, autoFocus: true }),
      createElement("i", { key: SHELF_KEY }),
    ]);
    const out = insertAfterRecentsRow(tree, extra);
    expect(out.tree).toBe(tree);
  });
});

describe("wrapComponentType", () => {
  const hook = (out: ReactNode) => <div data-testid="wrapped">{out}</div>;

  it("wraps function, memo, forwardRef and class components, and caches one wrapper per type", () => {
    const Fn = () => <span>fn</span>;
    const Memo = memo(() => <span>memo</span>);
    const Fwd = forwardRef<HTMLSpanElement>(function Fwd(_p, ref) {
      return <span ref={ref}>fwd</span>;
    });
    class Cls extends Component {
      render() {
        return <span>cls</span>;
      }
    }
    for (const [type, text] of [
      [Fn, "fn"],
      [Memo, "memo"],
      [Fwd, "fwd"],
      [Cls, "cls"],
    ] as const) {
      const Wrapped = wrapComponentType(type, 9, hook);
      expect(wrapComponentType(type, 9, hook)).toBe(Wrapped);
      expect(wrapComponentType(Wrapped, 9, hook)).toBe(Wrapped);
      const { unmount } = render(createElement(Wrapped));
      expect(screen.getByTestId("wrapped")).toHaveTextContent(text);
      unmount();
    }
  });

  it("returns types it cannot wrap unchanged", () => {
    expect(wrapComponentType("div", 9, hook)).toBe("div");
    expect(wrapComponentType(null, 9, hook)).toBeNull();
    const provider = { $$typeof: Symbol.for("react.provider") };
    expect(wrapComponentType(provider, 9, hook)).toBe(provider);
  });
});

describe("describeTree", () => {
  it("outlines types and prop names, bounded", () => {
    const lines = describeTree(
      <div className="x">
        <Rows variant="section" />
      </div>,
    );
    expect(lines[0]).toBe("div key=null props=[className]");
    expect(lines[1]).toBe("  Rows key=null props=[variant]");
    expect(describeTree([<p key="a" />, <p key="b" />], 5, 1)).toHaveLength(1);
  });
});
