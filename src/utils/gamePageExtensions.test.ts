import { describe, it, expect, beforeEach, vi } from "vitest";
import * as backend from "../api/backend";
import {
  GAME_PAGE_GLOBAL,
  GAME_PAGE_READY_EVENT,
  _resetGamePageExtensionsForTests,
  extensionLabel,
  getGamePageExtensions,
  hasGamePageExtension,
  installGamePageRegistry,
  listGamePageExtensions,
  onGamePageExtensionsChange,
  registerGamePageExtension,
  visibleExtensions,
  type GamePageExtension,
  type GamePageRegistryGlobal,
  type RomPageContext,
} from "./gamePageExtensions";

vi.mock("../api/backend", () => ({ logError: vi.fn(), logWarn: vi.fn() }));

const ctx: RomPageContext = {
  appId: 1,
  romId: 7,
  name: "Melee",
  platformSlug: "ngc",
  platformName: "GameCube",
  installed: true,
  locale: "en",
};

function ext(overrides: Partial<GamePageExtension> = {}): GamePageExtension {
  return { id: "forge.mods", kind: "tab", label: "Mods", render: () => null, ...overrides };
}

beforeEach(() => {
  _resetGamePageExtensionsForTests();
  vi.mocked(backend.logError).mockClear();
  vi.mocked(backend.logWarn).mockClear();
});

describe("registerGamePageExtension", () => {
  it("adds and removes an extension, notifying subscribers each time", () => {
    const listener = vi.fn();
    const stop = onGamePageExtensionsChange(listener);
    const unregister = registerGamePageExtension(ext());
    expect(listGamePageExtensions()).toEqual([{ id: "forge.mods", kind: "tab" }]);
    unregister();
    expect(listGamePageExtensions()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
  });

  it("hands out a new snapshot on every change and the same one in between", () => {
    const before = getGamePageExtensions();
    expect(getGamePageExtensions()).toBe(before);
    registerGamePageExtension(ext());
    expect(getGamePageExtensions()).not.toBe(before);
  });

  it("replaces a registration with the same id, and the old unregister no longer removes the new one", () => {
    const teardown = vi.fn();
    const first = registerGamePageExtension(ext({ label: "Old", subscribe: () => teardown }));
    registerGamePageExtension(ext({ label: "New" }));
    expect(teardown).toHaveBeenCalledTimes(1);
    first();
    expect(getGamePageExtensions().map((r) => r.extension.label)).toEqual(["New"]);
  });

  it.each([
    ["no id", { id: "" }],
    ["a bad kind", { kind: "bar" as never }],
    ["no render", { render: undefined as never }],
    ["a bad order", { order: Number.NaN }],
  ])("refuses an extension with %s and logs why", (_label, overrides) => {
    const unregister = registerGamePageExtension(ext(overrides));
    expect(listGamePageExtensions()).toEqual([]);
    expect(backend.logWarn).toHaveBeenCalledWith(expect.stringContaining("Game page extension refused"));
    expect(() => unregister()).not.toThrow();
  });

  it("moves the registration's revision when the extension's own subscribe fires", () => {
    let fire: () => void = () => {};
    const teardown = vi.fn();
    const unregister = registerGamePageExtension(
      ext({
        subscribe: (onChange) => {
          fire = onChange;
          return teardown;
        },
      }),
    );
    const before = getGamePageExtensions();
    fire();
    expect(getGamePageExtensions()).not.toBe(before);
    expect(getGamePageExtensions()[0]?.revision).toBe(1);
    unregister();
    expect(teardown).toHaveBeenCalledTimes(1);
    fire();
    expect(getGamePageExtensions()).toEqual([]);
  });

  it("keeps the registration and logs when subscribe throws", () => {
    registerGamePageExtension(
      ext({
        subscribe: () => {
          throw new Error("boom");
        },
      }),
    );
    expect(listGamePageExtensions()).toHaveLength(1);
    expect(backend.logError).toHaveBeenCalledWith(expect.stringContaining("subscribe threw: Error: boom"));
  });
});

describe("visibleExtensions", () => {
  it("filters by kind and availability and orders by order, then registration", () => {
    registerGamePageExtension(ext({ id: "b", order: 50 }));
    registerGamePageExtension(ext({ id: "a" }));
    registerGamePageExtension(ext({ id: "c", order: 50 }));
    registerGamePageExtension(ext({ id: "card", kind: "overviewCard" }));
    registerGamePageExtension(ext({ id: "hidden", isAvailable: (c) => c.platformSlug === "psp" }));
    expect(visibleExtensions(getGamePageExtensions(), "tab", ctx).map((r) => r.extension.id)).toEqual(["b", "c", "a"]);
    expect(visibleExtensions(getGamePageExtensions(), "overviewCard", ctx).map((r) => r.extension.id)).toEqual([
      "card",
    ]);
  });

  it("treats an isAvailable that throws as unavailable and logs it", () => {
    registerGamePageExtension(
      ext({
        isAvailable: () => {
          throw new Error("nope");
        },
      }),
    );
    expect(visibleExtensions(getGamePageExtensions(), "tab", ctx)).toEqual([]);
    expect(backend.logError).toHaveBeenCalledWith(expect.stringContaining("isAvailable threw: Error: nope"));
  });
});

describe("extensionLabel", () => {
  it("calls a label function with the locale and falls back to the id when it throws", () => {
    expect(extensionLabel(ext({ label: (l) => (l === "fr" ? "Mods (fr)" : "Mods") }), "fr")).toBe("Mods (fr)");
    expect(
      extensionLabel(
        ext({
          label: () => {
            throw new Error("x");
          },
        }),
        "en",
      ),
    ).toBe("forge.mods");
    expect(backend.logError).toHaveBeenCalledWith(expect.stringContaining("label threw"));
  });
});

describe("hasGamePageExtension", () => {
  it("answers by id", () => {
    registerGamePageExtension(ext({ id: "other" }));
    expect(hasGamePageExtension(getGamePageExtensions(), "forge.mods")).toBe(false);
    registerGamePageExtension(ext());
    expect(hasGamePageExtension(getGamePageExtensions(), "forge.mods")).toBe(true);
  });
});

describe("installGamePageRegistry", () => {
  it("publishes a versioned global, announces it, and withdraws it with every registration", () => {
    const ready = vi.fn();
    globalThis.addEventListener(GAME_PAGE_READY_EVENT, ready);
    const uninstall = installGamePageRegistry();
    const api = (globalThis as unknown as Record<string, GamePageRegistryGlobal | undefined>)[GAME_PAGE_GLOBAL];
    expect(api?.version).toBe(1);
    expect(ready).toHaveBeenCalledTimes(1);

    const teardown = vi.fn();
    api?.register(ext({ subscribe: () => teardown }));
    expect(api?.list()).toEqual([{ id: "forge.mods", kind: "tab" }]);

    uninstall();
    expect((globalThis as unknown as Record<string, unknown>)[GAME_PAGE_GLOBAL]).toBeUndefined();
    expect(listGamePageExtensions()).toEqual([]);
    expect(teardown).toHaveBeenCalledTimes(1);
    globalThis.removeEventListener(GAME_PAGE_READY_EVENT, ready);
  });

  it("leaves a newer registry in place when an older one uninstalls", () => {
    const uninstallOld = installGamePageRegistry();
    const uninstallNew = installGamePageRegistry();
    const current = (globalThis as unknown as Record<string, unknown>)[GAME_PAGE_GLOBAL];
    uninstallOld();
    expect((globalThis as unknown as Record<string, unknown>)[GAME_PAGE_GLOBAL]).toBe(current);
    uninstallNew();
  });
});
