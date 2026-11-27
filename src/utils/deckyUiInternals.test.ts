import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// @decky/ui comes from the loader at runtime: 4.x on Decky 3.3.1 (named class
// modules, findClassModule) and 5.x on Decky 4.0 (adds module-scope findVar).
// Each shape is loaded fresh so the module-level lookups run against it.
async function loadWith(ui: Record<string, unknown>) {
  vi.resetModules();
  vi.doMock("@decky/ui", () => ui);
  return import("./deckyUiInternals");
}

const appDetails = { HeaderLoaded: "hl", InnerContainer: "ic", AppDetailsOverviewPanel: "op" };
const playSection = { PlayBarDetailLabel: "pl", Container: "pc" };
const appAction = { PlayButtonContainer: "pb" };
const styler = { AppDetailsRoot: "ar", PlaySection: "ps" };
const header = { TopCapsule: "tc", ImgContainer: "img" };
const named = {
  appDetailsHeaderClasses: header,
  appDetailsClasses: appDetails,
  playSectionClasses: playSection,
  appActionButtonClasses: appAction,
  basicAppDetailsSectionStylerClasses: styler,
};
const unnamed = {
  appDetailsHeaderClasses: undefined,
  appDetailsClasses: undefined,
  playSectionClasses: undefined,
  appActionButtonClasses: undefined,
  basicAppDetailsSectionStylerClasses: undefined,
};
const modules: unknown[] = [{ Other: "x" }, appDetails, playSection, appAction, styler, header];
const finderOver = (values: unknown[]) => (filter: (v: unknown) => boolean) => values.find((v) => filter(v));

describe("deckyUiInternals", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.doUnmock("@decky/ui");
    vi.restoreAllMocks();
  });

  it("uses the named class modules when the loader provides them", async () => {
    const findClassModule = vi.fn();
    const m = await loadWith({ ...named, findSP: () => undefined, findClassModule });
    expect(m.appDetailsClasses).toBe(appDetails);
    expect(m.playSectionClasses).toBe(playSection);
    expect(m.missingDeckyUiLookups()).toEqual([]);
    expect(findClassModule).not.toHaveBeenCalled();
  });

  it("Decky 3.3.1: falls back to findClassModule when a named module is undefined", async () => {
    const m = await loadWith({ ...unnamed, findSP: () => undefined, findClassModule: finderOver(modules) });
    expect(m.appDetailsClasses).toBe(appDetails);
    expect(m.appActionButtonClasses).toBe(appAction);
    expect(m.basicAppDetailsSectionStylerClasses).toBe(styler);
    expect(m.appDetailsHeaderClasses).toBe(header);
    expect(m.missingDeckyUiLookups()).toEqual([]);
  });

  it("Decky 4.0: falls back to module-scope findVar when findClassModule misses", async () => {
    const findVar = vi.fn(finderOver([42, null, ...modules]));
    const m = await loadWith({ ...unnamed, findSP: () => undefined, findClassModule: () => undefined, findVar });
    expect(m.playSectionClasses).toBe(playSection);
    expect(m.appDetailsClasses).toBe(appDetails);
    expect(findVar).toHaveBeenCalled();
  });

  it("rejects a finder answer that lacks the keys", async () => {
    const m = await loadWith({ ...unnamed, findSP: () => undefined, findClassModule: () => ({ Other: "x" }) });
    expect(m.appDetailsClasses).toBeUndefined();
  });

  it("missing or throwing finders leave every module undefined and record the misses", async () => {
    const boom = () => {
      throw new Error("hostile module");
    };
    const m = await loadWith({ ...unnamed, findSP: boom, findClassModule: boom, findVar: boom });
    expect(m.appDetailsClasses).toBeUndefined();
    expect(m.playSectionClasses).toBeUndefined();
    expect([...m.missingDeckyUiLookups()].sort()).toEqual([
      "appActionButtonClasses",
      "appDetailsClasses",
      "appDetailsHeaderClasses",
      "basicAppDetailsSectionStylerClasses",
      "playSectionClasses",
    ]);
    expect(m.findSP()).toBeUndefined();
  });

  it("a mock without the finder exports does not throw on load", async () => {
    vi.resetModules();
    vi.doMock("@decky/ui", () => ({ ...unnamed, findSP: () => window }));
    const m = await import("./deckyUiInternals");
    expect(m.appDetailsClasses).toBeUndefined();
    expect(m.findSP()).toBe(window);
  });
});
