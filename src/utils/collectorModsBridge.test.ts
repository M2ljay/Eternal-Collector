import { describe, it, expect, beforeEach, vi } from "vitest";
import * as backend from "../api/backend";
import * as cachedStore from "./cachedGameDetailStore";
import {
  COLLECTOR_MODS_GLOBAL,
  COLLECTOR_MODS_READY_EVENT,
  createCollectorModsBridge,
  installCollectorModsBridge,
  isEntryName,
  type CollectorModsBridge,
} from "./collectorModsBridge";
import type { GameModsInfo, ModTarget } from "../types/mods";

vi.mock("./cachedGameDetailStore", () => ({
  getCachedGameDetail: vi.fn(),
  invalidateCachedGameDetail: vi.fn(),
}));

const APP_ID = 3_000_000_001;
const ROM_ID = 42;

function target(overrides: Partial<ModTarget> = {}): ModTarget {
  return {
    target_id: "textures",
    label: "Texture pack",
    scope: "game",
    path: "C:\\Emu\\Dolphin\\User\\Load\\Textures\\GALE01",
    exists: true,
    game_folder: "GALE01",
    notes: [],
    installed: [{ name: "pack", is_dir: true, size: 10, files: 2, modified: 1, partial: false }],
    installed_truncated: false,
    setting: {
      label: "Load custom textures",
      file: "Dolphin.ini",
      section: "Settings",
      key: "HiresTextures",
      state: "off",
      can_enable: true,
    },
    accepts: "archive_or_folder",
    ...overrides,
  };
}

function modsInfo(targets: ModTarget[] = [target()]): GameModsInfo {
  return {
    success: true,
    emulator: { id: "dolphin", label: "Dolphin", exe: "C:\\Emu\\Dolphin\\Dolphin.exe" },
    game_id: "GALE01",
    targets,
    omitted: [],
    note: null,
  };
}

let bridge: CollectorModsBridge;
const isRomApp = vi.fn((appId: number) => appId === APP_ID);

beforeEach(() => {
  vi.resetAllMocks();
  isRomApp.mockImplementation((appId: number) => appId === APP_ID);
  vi.mocked(cachedStore.getCachedGameDetail).mockImplementation((appId: number) =>
    Promise.resolve(
      appId === APP_ID
        ? {
            found: true,
            rom_id: ROM_ID,
            rom_name: "Super Smash Bros. Melee",
            platform_slug: "ngc",
            platform_name: "Nintendo GameCube",
            installed: true,
          }
        : { found: false },
    ),
  );
  vi.mocked(backend.getGameMods).mockResolvedValue(modsInfo());
  bridge = createCollectorModsBridge({ isRomApp });
});

describe("collector mods bridge", () => {
  it("answers isRomApp from the injected set and refuses a non-integer appId", () => {
    expect(bridge.isRomApp(APP_ID)).toBe(true);
    expect(bridge.isRomApp(7)).toBe(false);
    expect(bridge.isRomApp(1.5)).toBe(false);
    expect(isRomApp).not.toHaveBeenCalledWith(1.5);
  });

  it("describes the ROM with its emulator, identifier family and game id", async () => {
    await expect(bridge.getRomInfo(APP_ID)).resolves.toEqual({
      appId: APP_ID,
      romId: ROM_ID,
      name: "Super Smash Bros. Melee",
      platformSlug: "ngc",
      platformName: "Nintendo GameCube",
      installed: true,
      locale: globalThis.navigator.language,
      emulator: "dolphin",
      family: "gc-wii",
      gameId: "GALE01",
    });
    expect(backend.getGameMods).toHaveBeenCalledWith(ROM_ID);
  });

  it("answers null for an app that is not a ROM, and no emulator when mods are unsupported", async () => {
    await expect(bridge.getRomInfo(99)).resolves.toBeNull();
    vi.mocked(backend.getGameMods).mockResolvedValue({ success: false, reason: "unsupported", message: "x" });
    await expect(bridge.getRomInfo(APP_ID)).resolves.toMatchObject({ emulator: null, family: null, gameId: null });
  });

  it("passes getTargets' answer through unchanged", async () => {
    const info = modsInfo();
    vi.mocked(backend.getGameMods).mockResolvedValue(info);
    await expect(bridge.getTargets(APP_ID)).resolves.toBe(info);
  });

  it("answers not_a_rom without calling any mods callable for an unknown app", async () => {
    await expect(bridge.getTargets(99)).resolves.toEqual({
      success: false,
      reason: "not_a_rom",
      message: "App 99 is not a ROM in The Collector.",
    });
    expect(backend.getGameMods).not.toHaveBeenCalled();
  });

  it("lists sources for the named target, or for the first target when none is named", async () => {
    vi.mocked(backend.listModSources).mockResolvedValue({ success: true, folder: "D", entries: [], truncated: false });
    await bridge.listSources(APP_ID, "patch");
    expect(backend.listModSources).toHaveBeenLastCalledWith(ROM_ID, "patch");
    await bridge.listSources(APP_ID);
    expect(backend.listModSources).toHaveBeenLastCalledWith(ROM_ID, "textures");
  });

  it("answers no_target when a game has no mod folder and none is named", async () => {
    vi.mocked(backend.getGameMods).mockResolvedValue({ ...modsInfo([]), note: "No known mod folder." });
    await expect(bridge.listSources(APP_ID)).resolves.toEqual({
      success: false,
      reason: "no_target",
      message: "No known mod folder.",
    });
    expect(backend.listModSources).not.toHaveBeenCalled();
  });

  it("maps preview and install onto the callables' (rom, target, source) order", async () => {
    await bridge.preview(APP_ID, "melee-hd.zip", "textures");
    expect(backend.previewModInstall).toHaveBeenCalledWith(ROM_ID, "textures", "melee-hd.zip");
    await bridge.install(APP_ID, "melee-hd.zip", "textures", "fp1");
    expect(backend.installMod).toHaveBeenCalledWith(ROM_ID, "textures", "melee-hd.zip", "fp1");
  });

  it.each(["C:\\Users\\me\\Downloads\\x.zip", "sub/x.zip", "..", "", "D:x.zip"])(
    "refuses the source %j as a path and never calls the backend",
    async (source) => {
      await expect(bridge.preview(APP_ID, source, "textures")).resolves.toMatchObject({
        success: false,
        reason: "invalid_source",
      });
      await expect(bridge.install(APP_ID, source, "textures", "fp")).resolves.toMatchObject({
        success: false,
        reason: "invalid_source",
      });
      expect(backend.previewModInstall).not.toHaveBeenCalled();
      expect(backend.installMod).not.toHaveBeenCalled();
    },
  );

  it("refuses an install without a fingerprint", async () => {
    await expect(bridge.install(APP_ID, "a.zip", "textures", "")).resolves.toMatchObject({
      reason: "invalid_argument",
    });
    expect(backend.installMod).not.toHaveBeenCalled();
  });

  it("reads installed entries and the setting from the target's own listing", async () => {
    await expect(bridge.listInstalled(APP_ID, "textures")).resolves.toEqual({
      success: true,
      target_id: "textures",
      entries: target().installed,
      truncated: false,
    });
    await expect(bridge.readSetting(APP_ID, "textures")).resolves.toEqual({
      success: true,
      target_id: "textures",
      setting: target().setting,
    });
    await expect(bridge.readSetting(APP_ID, "nope")).resolves.toMatchObject({ success: false, reason: "not_found" });
  });

  it("removes by listed entry name or the whole game folder, and refuses a path", async () => {
    await bridge.remove(APP_ID, "textures", "pack");
    expect(backend.removeMod).toHaveBeenLastCalledWith(ROM_ID, "textures", "pack");
    await bridge.remove(APP_ID, "textures", null);
    expect(backend.removeMod).toHaveBeenLastCalledWith(ROM_ID, "textures", null);
    await expect(bridge.remove(APP_ID, "textures", "..\\x")).resolves.toMatchObject({ reason: "invalid_argument" });
    expect(backend.removeMod).toHaveBeenCalledTimes(2);
  });

  it("maps enableSetting and openFolder onto their callables", async () => {
    await bridge.enableSetting(APP_ID, "textures");
    expect(backend.enableModSetting).toHaveBeenCalledWith(ROM_ID, "textures");
    await bridge.openFolder(APP_ID, "textures");
    expect(backend.openModFolder).toHaveBeenCalledWith(ROM_ID, "textures");
  });

  it("turns a rejected callable into a bridge_error failure instead of throwing", async () => {
    vi.mocked(backend.installMod).mockRejectedValue(new Error("socket closed"));
    await expect(bridge.install(APP_ID, "a.zip", "textures", "fp")).resolves.toEqual({
      success: false,
      reason: "bridge_error",
      message: "install failed: socket closed",
    });
  });

  it("refuses a non-integer appId without a lookup", async () => {
    await expect(bridge.openFolder("12" as never, "textures")).resolves.toMatchObject({
      reason: "invalid_argument",
    });
    expect(cachedStore.getCachedGameDetail).not.toHaveBeenCalled();
  });
});

describe("isEntryName", () => {
  it("accepts a plain Downloads entry name", () => {
    expect(isEntryName("Melee HD v2.1.zip")).toBe(true);
  });
});

describe("installCollectorModsBridge", () => {
  it("publishes a versioned global, announces it, and withdraws it", () => {
    const ready = vi.fn();
    globalThis.addEventListener(COLLECTOR_MODS_READY_EVENT, ready);
    const uninstall = installCollectorModsBridge({ isRomApp });
    const g = globalThis as unknown as Record<string, CollectorModsBridge | undefined>;
    expect(g[COLLECTOR_MODS_GLOBAL]?.version).toBe(1);
    expect(ready).toHaveBeenCalledTimes(1);
    uninstall();
    expect(g[COLLECTOR_MODS_GLOBAL]).toBeUndefined();
    globalThis.removeEventListener(COLLECTOR_MODS_READY_EVENT, ready);
  });
});
