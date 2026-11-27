import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { showModal } from "@decky/ui";
import { RomPageHeader, playLine } from "./RomPageHeader";
import { RomOverviewCards, saveSyncChip } from "./RomOverviewCards";
import { RomMediaTab } from "./RomMediaTab";
import { coreStatusLine } from "./RomMPlaySection";
import { consoleFamily, core, familyTones } from "../theme/coreTokens";
import { corePageCss, starfieldSvg, CORE_PAGE_CLASS } from "../utils/corePageStyles";
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

describe("RomPageHeader", () => {
  it("joins whichever play facts are known", () => {
    expect(playLine("3 days ago", "12 hours")).toBe("Last played 3 days ago · 12 hours played");
    expect(playLine("", "12 hours")).toBe("12 hours played");
    expect(playLine("", "")).toBe("");
  });

  it("shows the title, the platform chip in its family tone and The Collector chip", () => {
    const { container, getByText } = render(
      <RomPageHeader
        name="Super Metroid"
        platformName="Super Nintendo"
        platformSlug="snes"
        lastPlayed="3 days ago"
        playtime=""
      />,
    );
    expect(getByText("Super Metroid").className).toBe("romm-core-title");
    const chip = container.querySelector<HTMLElement>(".romm-core-chip-tone")!;
    expect(chip.textContent).toBe("Super Nintendo");
    expect(chip.dataset.coreFamily).toBe("nintendo");
    expect(chip.style.background.toLowerCase()).toBe(familyTones.nintendo.toLowerCase());
    expect(chip.style.color.toLowerCase()).toBe(core.black.toLowerCase());
    expect(container.textContent).toContain("The Collector");
    expect(container.textContent).toContain("Last played 3 days ago");
  });

  it("leaves the platform chip out until the platform is known", () => {
    const { container } = render(<RomPageHeader name="" platformName="" platformSlug="" lastPlayed="" playtime="" />);
    expect(container.querySelector(".romm-core-chip-tone")).toBeNull();
    expect(container.querySelector(".romm-core-title")).toBeNull();
    expect(container.querySelector(".romm-core-play-line")).toBeNull();
  });
});

describe("coreStatusLine", () => {
  it("names the emulator and whether the game is on disk", () => {
    expect(coreStatusLine("RetroArch: Snes9x", true)).toBe("RetroArch: Snes9x · Installed");
    expect(coreStatusLine(null, false)).toBe("Not installed");
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

describe("RomOverviewCards", () => {
  it("shows the RetroAchievements card only for a game RA knows, and opens its tab", () => {
    const onOpenTab = vi.fn();
    const { getByText, queryByText, rerender } = render(
      <RomOverviewCards
        raId={null}
        achievements={null}
        saveSyncEnabled={true}
        saveStatus={status("synced")}
        conflictCount={0}
        onOpenTab={onOpenTab}
      />,
    );
    expect(queryByText("RetroAchievements")).toBeNull();
    rerender(
      <RomOverviewCards
        raId={7}
        achievements={{ earned: 3, total: 50 }}
        saveSyncEnabled={true}
        saveStatus={status("synced")}
        conflictCount={0}
        onOpenTab={onOpenTab}
      />,
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
      <RomOverviewCards
        raId={null}
        achievements={null}
        saveSyncEnabled={false}
        saveStatus={null}
        conflictCount={0}
        onOpenTab={onOpenTab}
      />,
    );
    fireEvent.click(getByText("Save sync"));
    expect(onOpenTab).not.toHaveBeenCalled();
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

  it("scopes every rule to the ROM page", () => {
    const rules = corePageCss()
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.includes("{"));
    for (const rule of rules) {
      expect(rule.includes(`.${CORE_PAGE_CLASS}`)).toBe(true);
    }
  });

  it("uses square focus and the float radius only for floating cards", () => {
    const css = corePageCss();
    expect(css).toMatch(/\.romm-core-card \{[^}]*border-radius: var\(--core-radius-float, 10px\)/);
    expect(css).toMatch(/\.romm-core-card\.gpfocus \{[^}]*outline: 2px solid #D7263D/);
    expect(css).not.toMatch(/glow|text-shadow/);
  });
});
