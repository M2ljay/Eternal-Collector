import { describe, it, expect, vi, afterEach } from "vitest";

// The insertion point must be found by class (class map current) and, when the
// class map lags the Steam build, by the native overview panel's props.
const tree = (innerClass: string, panelClass: string) => {
  const overview = {
    props: { className: panelClass, children: { props: { details: {}, overview: { appid: 7 }, bFastRender: true } } },
  };
  const inner = { props: { className: innerClass, children: [{ props: {} }, overview] } };
  return { inner, root: { props: { children: { props: { children: [inner] } } } } };
};

function findInReactTree(node: unknown, filter: (x: unknown) => boolean, seen = new Set<unknown>()): unknown {
  if (node === null || typeof node !== "object" || seen.has(node)) return undefined;
  seen.add(node);
  if (filter(node)) return node;
  for (const child of Object.values(node)) {
    const found = findInReactTree(child, filter, seen);
    if (found) return found;
  }
  return undefined;
}

async function loadWith(appDetailsClasses: Record<string, string> | undefined) {
  vi.resetModules();
  vi.doMock("@decky/ui", () => ({ findInReactTree, afterPatch: vi.fn(), createReactTreePatcher: vi.fn() }));
  vi.doMock("../utils/deckyUiInternals", () => ({
    appDetailsClasses,
    playSectionClasses: undefined,
    basicAppDetailsSectionStylerClasses: undefined,
    missingDeckyUiLookups: () => [],
  }));
  vi.doMock("../api/backend", () => ({ debugLog: vi.fn().mockResolvedValue(undefined), logWarn: vi.fn() }));
  vi.doMock("../components/RomMPlaySection", () => ({ RomMPlaySection: () => null }));
  vi.doMock("../components/RomMGameInfoPanel", () => ({ RomMGameInfoPanel: () => null }));
  return import("./gameDetailPatch");
}

describe("gameDetailPatch insertion point", () => {
  afterEach(() => {
    for (const id of [
      "@decky/ui",
      "../utils/deckyUiInternals",
      "../api/backend",
      "../components/RomMPlaySection",
      "../components/RomMGameInfoPanel",
    ])
      vi.doUnmock(id);
  });

  it("finds InnerContainer by its class-map class", async () => {
    const m = await loadWith({ InnerContainer: "ic", AppDetailsOverviewPanel: "mapped" });
    const { inner, root } = tree("x ic", "native");
    expect(m.findInsertionPoint(root)).toBe(inner);
    expect(m.overviewPanelClass(inner.props.children, 1)).toBe("mapped");
  });

  it("falls back to the native overview panel when the class map lags the Steam build", async () => {
    const m = await loadWith({ InnerContainer: "stale", AppDetailsOverviewPanel: "" });
    const { inner, root } = tree("renamed", "native-panel");
    expect(m.findInsertionPoint(root)).toBe(inner);
    expect(m.overviewPanelClass(inner.props.children, m.findNativeOverviewIndex(inner.props.children))).toBe(
      "native-panel",
    );
  });

  it("works with no class map at all and finds nothing in an unrelated tree", async () => {
    const m = await loadWith(undefined);
    const { inner, root } = tree("renamed", "native-panel");
    expect(m.findInsertionPoint(root)).toBe(inner);
    expect(m.findInsertionPoint({ props: { children: [{ props: {} }] } })).toBeUndefined();
    expect(m.overviewPanelClass([{ props: {} }], -1)).toBe("");
  });
});
