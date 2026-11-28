import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { showModal } from "@decky/ui";
import { RomPageChips } from "./RomPageChips";
import { BUILTIN_CARD_ORDER, romOverviewCards, saveSyncChip, type RomOverviewCardsProps } from "./RomOverviewCards";
import { ExtensionOverviewCards } from "./GamePageExtensions";
import { RomMediaTab } from "./RomMediaTab";
import { SaveSyncIcon } from "./icons";
import { consoleFamily, core, familyTones } from "../theme/coreTokens";
import { corePageCss, starfieldSvg, CORE_PAGE_CLASS, GAME_VIEW, GAME_VIEW_CLASS } from "../utils/corePageStyles";
import type { SaveStatus } from "../types";

function status(display?: "synced" | "pending" | "conflict" | "none"): SaveStatus {
  return {
    rom_id: 1,
    files: [],
    playtime: { total_seconds: 0, session_count: 0, last_session_start: null, last_session_duration_sec: null },
    device_id: "d",
    last_sync_check_at: null,
    ...(display ? { save_sync_display: { status: display, label: "", last_sync_at: null } } : {}),
  } as unknown as SaveStatus;
}

describe("consoleFamily", () => {
  it.each([
    ["psx", "playstation"],
    ["PS2", "playstation"],
    ["snes", "nintendo"],
    ["3ds", "nintendo"],
    ["genesis-slash-megadrive", "sega"],
    ["xbox360", "xbox"],
    ["neogeoaes", "retro"],
    ["", "retro"],
  ])("%s is %s", (slug, family) => {
    expect(consoleFamily(slug)).toBe(family);
  });
});

describe("RomPageChips", () => {
  it("shows the platform chip in its family tone, and no The Collector chip", () => {
    const { container } = render(<RomPageChips platformName="Super Nintendo" platformSlug="snes" />);
    const chip = container.querySelector<HTMLElement>(".romm-core-chip-tone")!;
    expect(chip.textContent).toBe("Super Nintendo");
    expect(chip.dataset.coreFamily).toBe("nintendo");
    expect(chip.style.background.toLowerCase()).toBe(familyTones.nintendo.toLowerCase());
    expect(chip.style.color.toLowerCase()).toBe(core.black.toLowerCase());
    expect(container.textContent).not.toContain("The Collector");
  });

  it("draws nothing until the platform is known", () => {
    const { container } = render(<RomPageChips platformName="" platformSlug="" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("saveSyncChip", () => {
  it("says Off when save sync is off, whatever the status", () => {
    expect(saveSyncChip(false, status("synced"), 0).label).toBe("Off");
  });

  it("puts a conflict first, crimson with white text", () => {
    expect(saveSyncChip(true, status("synced"), 1)).toEqual({
      label: "Conflict",
      background: core.crimson,
      color: core.white,
    });
  });

  it("uses black text on the green and amber fills", () => {
    expect(saveSyncChip(true, status("synced"), 0)).toEqual({
      label: "Synced with RomM",
      background: core.success,
      color: core.black,
    });
    expect(saveSyncChip(true, status("pending"), 0).color).toBe(core.black);
  });

  it("does not claim anything before a status has been read", () => {
    expect(saveSyncChip(true, null, 0).label).toBe("Not checked yet");
    expect(saveSyncChip(true, status("none"), 0).label).toBe("No saves yet");
  });
});

describe("Overview cards", () => {
  const ctx = {
    appId: 5,
    romId: 1,
    name: "x",
    platformSlug: "snes",
    platformName: "SNES",
    installed: true,
    locale: "en",
  };
  const props = (over: Partial<RomOverviewCardsProps> = {}): RomOverviewCardsProps => ({
    raId: 7,
    achievements: { earned: 3, total: 50 },
    saveSyncEnabled: true,
    saveStatus: status("synced"),
    conflictCount: 0,
    onOpenTab: vi.fn(),
    ...over,
  });

  it("shows the RetroAchievements card only for a game RA knows, and the cards open their tabs", () => {
    expect(romOverviewCards(props({ raId: null })).map((c) => c.key)).toEqual(["saves"]);
    const onOpenTab = vi.fn();
    const { getByText } = render(
      <ExtensionOverviewCards entries={[]} ctx={ctx} builtins={romOverviewCards(props({ onOpenTab }))} />,
    );
    expect(getByText("3 / 50")).not.toBeNull();
    fireEvent.click(getByText("RetroAchievements"));
    expect(onOpenTab).toHaveBeenCalledWith("achievements");
    fireEvent.click(getByText("Save sync"));
    expect(onOpenTab).toHaveBeenLastCalledWith("saves");
  });

  it("does not open a Saves tab that save sync being off has removed", () => {
    const onOpenTab = vi.fn();
    const { getByText } = render(
      <ExtensionOverviewCards
        entries={[]}
        ctx={ctx}
        builtins={romOverviewCards(props({ saveSyncEnabled: false, saveStatus: null, onOpenTab }))}
      />,
    );
    fireEvent.click(getByText("Save sync"));
    expect(onOpenTab).not.toHaveBeenCalled();
  });

  it("places registered cards among its own by order: Mods at 20 between, Club at 40 after", () => {
    const card = (id: string, order: number | undefined) => ({
      seq: order ?? 0,
      revision: 0,
      extension: {
        id,
        kind: "overviewCard" as const,
        label: id,
        ...(order === undefined ? {} : { order }),
        render: () => id.toUpperCase(),
      },
    });
    const { container } = render(
      <ExtensionOverviewCards
        entries={[card("club", 40), card("forge.mods.card", 20), card("late", undefined)]}
        ctx={ctx}
        builtins={romOverviewCards(props())}
      />,
    );
    const order = Array.from(container.querySelectorAll(".romm-core-card-slot, .romm-ext-card")).map(
      (el) => el.getAttribute("data-extension-id") ?? el.textContent.slice(0, 10),
    );
    expect(order).toEqual(["RetroAchie", "forge.mods.card", "Save syncS", "club", "late"]);
    expect(BUILTIN_CARD_ORDER).toEqual({ achievements: 10, saves: 30 });
  });
});

describe("RomMediaTab", () => {
  it("shows the cover and opens the artwork picker for this ROM", () => {
    vi.mocked(showModal).mockClear();
    const { container, getByText } = render(
      <RomMediaTab appId={5} romId={42} romName="Super Metroid" coverBase64="AAAA" />,
    );
    expect(container.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,AAAA");
    fireEvent.click(getByText("Choose artwork…"));
    const modal = vi.mocked(showModal).mock.calls[0]?.[0] as { props: { romId: number; appId: number } };
    expect(modal.props).toMatchObject({ romId: 42, appId: 5 });
  });

  it("says so when there is no cover yet", () => {
    const { container } = render(<RomMediaTab appId={5} romId={42} romName="x" coverBase64={null} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("No cover yet.");
  });
});

describe("corePageCss", () => {
  it("keeps every star at or under Core UI's 24% ceiling", () => {
    const opacities = [...starfieldSvg().matchAll(/fill-opacity='([\d.]+)'/g)].map((m) => Number(m[1]));
    expect(opacities.length).toBeGreaterThan(0);
    expect(Math.max(...opacities)).toBeLessThanOrEqual(0.24);
  });

  it("paints the still starfield only while Core UI is on, and steps aside for Core's own", () => {
    const css = corePageCss();
    expect(css).toContain(`.${CORE_PAGE_CLASS} > .romm-core-stars { display: none;`);
    expect(css).toContain(`html[data-core-ui] .${CORE_PAGE_CLASS}:not([data-core-ui-host="1"]) > .romm-core-stars`);
  });

  it("keeps screen two, the Core UI host, painted black and holding no art", () => {
    const css = corePageCss();
    expect(css).toMatch(new RegExp(`\\.${CORE_PAGE_CLASS} \\{[^}]*background-color: #000000`));
    expect(css).toMatch(/\.romm-core-stars \{[^}]*top: 0;/);
  });

  it("scopes every rule to the ROM page", () => {
    const rules = corePageCss()
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.includes("{"));
    for (const rule of rules) {
      expect(rule.includes(`.${GAME_VIEW_CLASS}`) || rule.includes(`.${CORE_PAGE_CLASS}`)).toBe(true);
    }
  });

  it("lays screen one out like Clean Gameview, on ROM pages only", () => {
    expect(GAME_VIEW).toEqual({ playbar: 80, footer: 40, logo: 120, brightness: 0.6 });
    const css = corePageCss();
    expect(css).toContain(
      ".romm-core-playbar { height: calc(var(--romm-gv-playbar, 80px) + var(--romm-gv-footer, 40px))",
    );
    expect(css).toMatch(/\.romm-core-playbar \{[^}]*background: transparent !important/);
    expect(css).toMatch(
      /\.romm-native-menu-btn \{ width: 48px !important; height: 48px !important;[^}]*background: #000000/,
    );
  });

  it("uses square focus and the float radius only for floating cards", () => {
    const css = corePageCss();
    expect(css).toMatch(/\.romm-core-card \{[^}]*border-radius: var\(--core-radius-float, 10px\)/);
    expect(css).toMatch(/\.romm-core-card\.gpfocus \{[^}]*outline: 2px solid #D7263D/);
    expect(css).not.toMatch(/glow|text-shadow/);
  });
});

describe("SaveSyncIcon", () => {
  it.each([
    [false, "synced", "off"],
    [true, "synced", "synced"],
    [true, "pending", "pending"],
    [true, "conflict", "conflict"],
    [true, null, "unknown"],
  ] as const)("enabled=%s status=%s is drawn as %s", (enabled, value, shown) => {
    const { container } = render(<SaveSyncIcon enabled={enabled} status={value} />);
    const svg = container.querySelector("svg")!;
    expect(svg.dataset.saveSync).toBe(shown);
    expect(svg.getAttribute("stroke")).toBe(shown === "conflict" ? "#EA5A68" : "currentColor");
  });
});
