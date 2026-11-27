// The game page extension host: other plugins' tabs and Overview cards on the
// ROM game page (`utils/gamePageExtensions.ts`), rendered by RomMGameInfoPanel.

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act, fireEvent } from "@testing-library/react";
import { createElement } from "react";
import { RomMGameInfoPanel } from "./RomMGameInfoPanel";
import * as backend from "../api/backend";
import type { CachedGameDetail } from "../api/backend";
import * as cachedStore from "../utils/cachedGameDetailStore";
import { _resetSharedReadsForTests } from "../api/sharedReads";
import {
  _resetGamePageExtensionsForTests,
  registerGamePageExtension,
  type RomPageContext,
} from "../utils/gamePageExtensions";

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  logError: vi.fn(),
}));
vi.mock("../utils/cachedGameDetailStore", () => ({
  getCachedGameDetail: vi.fn(),
  invalidateCachedGameDetail: vi.fn(),
}));
vi.mock("./VersionErrorCard", () => ({
  VersionErrorCard: () => createElement("div"),
  useVersionError: vi.fn(() => null),
}));
vi.mock("../utils/scrollHelpers", () => ({ scrollFocusedToCenter: vi.fn() }));

const flushAsync = () =>
  act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  });

function detail(overrides: Partial<CachedGameDetail> = {}): CachedGameDetail {
  return {
    found: true,
    rom_id: 1,
    rom_name: "Melee (USA)",
    platform_slug: "ngc",
    platform_name: "GameCube",
    installed: true,
    metadata: null,
    stale_fields: [],
    ...overrides,
  };
}

let appId = 9000;

beforeEach(() => {
  appId++;
  _resetGamePageExtensionsForTests();
  _resetSharedReadsForTests();
  vi.mocked(cachedStore.getCachedGameDetail).mockResolvedValue(detail());
  vi.mocked(backend.refreshMigrationState).mockResolvedValue({
    retrodeck: { pending: false },
    save_sort: { pending: false },
  });
  vi.mocked(backend.getInstalledRom).mockResolvedValue(null);
  vi.mocked(backend.getArtworkBase64).mockResolvedValue({ base64: null });
  vi.mocked(backend.logError).mockClear();
});

async function mountPanel() {
  const view = render(<RomMGameInfoPanel appId={appId} />);
  await flushAsync();
  return view;
}

function tabButton(container: HTMLElement, label: string): HTMLElement | undefined {
  return Array.from(container.querySelectorAll<HTMLElement>(".romm-tab")).find((b) => b.textContent === label);
}

describe("game page extensions on the ROM page", () => {
  it("keeps today's page when nothing is registered", async () => {
    const { container } = await mountPanel();
    expect(Array.from(container.querySelectorAll(".romm-tab")).map((b) => b.textContent)).toEqual([
      "Overview",
      "Media",
      "Details",
    ]);
    expect(container.querySelector(".romm-ext-card")).toBeNull();
  });

  it("adds a tab registered after the page rendered, after the built-in tabs, and opens it", async () => {
    const { container, getByTestId } = await mountPanel();
    act(() => {
      registerGamePageExtension({
        id: "forge.mods",
        kind: "tab",
        label: (locale) => (locale ? "Mods" : "?"),
        render: (ctx) => createElement("div", { "data-testid": "forge-tab" }, `mods for ${ctx.romId}`),
      });
    });
    expect(Array.from(container.querySelectorAll(".romm-tab")).map((b) => b.textContent)).toEqual([
      "Overview",
      "Media",
      "Details",
      "Mods",
    ]);
    fireEvent.click(tabButton(container, "Mods")!);
    expect(getByTestId("forge-tab").textContent).toBe("mods for 1");
    expect(container.textContent).not.toContain("Save sync");
  });

  it("shows a tab registered before the page mounted", async () => {
    registerGamePageExtension({ id: "early", kind: "tab", label: "Early", render: () => null });
    const { container } = await mountPanel();
    expect(tabButton(container, "Early")).toBeDefined();
  });

  it("renders Overview cards on the Overview only, and a card can open its extension's tab", async () => {
    let seen: RomPageContext | null = null;
    registerGamePageExtension({ id: "forge.mods", kind: "tab", label: "Mods", render: () => "TAB BODY" });
    registerGamePageExtension({
      id: "forge.mods.card",
      kind: "overviewCard",
      label: "Mods",
      render: (ctx) => {
        seen = ctx;
        return createElement("button", { onClick: () => ctx.openTab?.("forge.mods") }, "3 mods active");
      },
    });
    const { container, getByText } = await mountPanel();
    expect(container.querySelector(".romm-ext-card")?.textContent).toBe("3 mods active");
    expect(seen).toMatchObject({
      appId,
      romId: 1,
      name: "Melee (USA)",
      platformSlug: "ngc",
      platformName: "GameCube",
      installed: true,
    });
    fireEvent.click(getByText("3 mods active"));
    expect(container.textContent).toContain("TAB BODY");
    expect(container.querySelector(".romm-ext-card")).toBeNull();
  });

  it("hides an extension that throws, logs it, and keeps the page and its neighbours", async () => {
    registerGamePageExtension({
      id: "broken",
      kind: "overviewCard",
      label: "Broken",
      render: () => {
        throw new Error("kaboom");
      },
    });
    registerGamePageExtension({ id: "fine", kind: "overviewCard", label: "Fine", render: () => "FINE CARD" });
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { container } = await mountPanel();
    spy.mockRestore();
    expect(container.textContent).toContain("FINE CARD");
    expect(container.textContent).toContain("Save sync");
    expect(backend.logError).toHaveBeenCalledWith(
      expect.stringContaining("Game page extension broken failed to render and is hidden"),
    );
  });

  it("hides a tab whose isAvailable says no for this ROM", async () => {
    registerGamePageExtension({
      id: "psp-only",
      kind: "tab",
      label: "PSP",
      isAvailable: (ctx) => ctx.platformSlug === "psp",
      render: () => null,
    });
    const { container } = await mountPanel();
    expect(tabButton(container, "PSP")).toBeUndefined();
  });

  it("falls back to the Overview when the open extension tab unregisters", async () => {
    let unregister: () => void = () => {};
    unregister = registerGamePageExtension({ id: "x", kind: "tab", label: "X", render: () => "X BODY" });
    const { container } = await mountPanel();
    fireEvent.click(tabButton(container, "X")!);
    expect(container.textContent).toContain("X BODY");
    act(() => unregister());
    await flushAsync();
    expect(container.textContent).not.toContain("X BODY");
    expect(container.textContent).toContain("Save sync");
  });

  it("re-renders an extension when its own subscribe fires", async () => {
    let fire: () => void = () => {};
    let count = 0;
    registerGamePageExtension({
      id: "live",
      kind: "overviewCard",
      label: "Live",
      subscribe: (onChange) => {
        fire = onChange;
        return () => {};
      },
      render: () => `updates: ${count}`,
    });
    const { container } = await mountPanel();
    expect(container.textContent).toContain("updates: 0");
    count = 2;
    act(() => fire());
    expect(container.textContent).toContain("updates: 2");
  });

  it("hands extensions the switched-to version's ROM after a version switch", async () => {
    const seen: number[] = [];
    registerGamePageExtension({
      id: "watch",
      kind: "overviewCard",
      label: "Watch",
      render: (ctx) => {
        seen.push(ctx.romId);
        return `${ctx.name} #${ctx.romId}`;
      },
    });
    const { container } = await mountPanel();
    expect(container.textContent).toContain("Melee (USA) #1");

    vi.mocked(cachedStore.getCachedGameDetail).mockResolvedValue(detail({ rom_id: 2, rom_name: "Melee (Japan)" }));
    await act(async () => {
      globalThis.dispatchEvent(
        new CustomEvent("romm_data_changed", { detail: { type: "version_switched", app_id: appId, rom_id: 2 } }),
      );
    });
    await flushAsync();
    expect(container.textContent).toContain("Melee (Japan) #2");
    expect(seen[seen.length - 1]).toBe(2);
  });
});
