/**
 * The Collector's mods bridge — `window.__eternalCollectorMods`.
 *
 * Lets another plugin (Forge) install mods into a ROM game's emulator folders
 * through The Collector's own game-mods callables, naming the game by its Steam
 * appId. It is a thin wrapper: every rule of the Mods panel holds unchanged —
 * a target is named by its id, a source by its Downloads entry name, an
 * installed entry by the name the backend listed, an install must echo its
 * preview's fingerprint, and nothing is deleted (removal moves to the backup
 * folder). No path is ever accepted. Every answer keeps the
 * `{success, reason, message}` failure shape and no wrapper throws.
 * Contract: `docs/architecture/game-mods.md#forge-bridge`.
 */

import {
  enableModSetting,
  getCachedGameDetail,
  getGameMods,
  installMod,
  listModBuiltins,
  listModSources,
  openModFolder,
  previewModInstall,
  removeMod,
  setModBuiltin,
} from "../api/backend";
import type {
  GameModsAnswer,
  ModBuiltinSetAnswer,
  ModBuiltinsAnswer,
  GameModsInfo,
  ModEntry,
  ModFailure,
  ModInstallAnswer,
  ModOpenAnswer,
  ModPreviewAnswer,
  ModRemoveAnswer,
  ModSetting,
  ModSettingAnswer,
  ModSourcesAnswer,
} from "../types/mods";
import type { RomPageContext } from "./gamePageExtensions";

export const COLLECTOR_MODS_GLOBAL = "__eternalCollectorMods";
/** Dispatched on `window` each time the bridge is installed. */
export const COLLECTOR_MODS_READY_EVENT = "eternal_collector_mods_ready";
export const COLLECTOR_MODS_VERSION = 1;

export type BridgeRomInfo = Omit<RomPageContext, "openTab"> & {
  emulator: string | null;
  family: string | null;
  gameId: string | null;
};

export type ListInstalledAnswer =
  { success: true; target_id: string; entries: ModEntry[]; truncated: boolean } | ModFailure;

export type ReadSettingAnswer = { success: true; target_id: string; setting: ModSetting | null } | ModFailure;

export interface CollectorModsBridge {
  readonly version: number;
  isRomApp(appId: number): boolean;
  getRomInfo(appId: number): Promise<BridgeRomInfo | null>;
  getTargets(appId: number): Promise<GameModsAnswer>;
  listSources(appId: number, targetId?: string): Promise<ModSourcesAnswer>;
  preview(appId: number, source: string, targetId: string): Promise<ModPreviewAnswer>;
  install(appId: number, source: string, targetId: string, fingerprint: string): Promise<ModInstallAnswer>;
  listInstalled(appId: number, targetId: string): Promise<ListInstalledAnswer>;
  remove(appId: number, targetId: string, name: string | null): Promise<ModRemoveAnswer>;
  readSetting(appId: number, targetId: string): Promise<ReadSettingAnswer>;
  enableSetting(appId: number, targetId: string): Promise<ModSettingAnswer>;
  openFolder(appId: number, targetId: string): Promise<ModOpenAnswer>;
  /** v1 addition: the entries of a `builtinToggle` target (codes, cheats, patches) and whether each is on. */
  listBuiltins(appId: number, targetId: string): Promise<ModBuiltinsAnswer>;
  /** v1 addition: switch one listed entry, named by the `entry_id` `listBuiltins` answered. */
  setBuiltin(appId: number, targetId: string, entryId: string, enabled: boolean): Promise<ModBuiltinSetAnswer>;
}

export interface CollectorModsBridgeDeps {
  /** Whether *appId* is one of The Collector's ROM shortcuts (the game page patch's set). */
  readonly isRomApp: (appId: number) => boolean;
}

/**
 * The identifier family an emulator names its per-game mod folders by
 * (`domain/game_mods.py` `IDENTIFIER_FAMILIES`, values from `domain/disc_ids.py`).
 * RetroArch's soft patch is named after the ROM file instead, so it has none.
 */
const IDENTIFIER_FAMILIES: Readonly<Record<string, string>> = {
  dolphin: "gc-wii",
  ppsspp: "psp",
  pcsx2: "ps2",
  azahar: "3ds",
};

function failure(reason: string, message: string): ModFailure {
  return { success: false, reason, message };
}

function validAppId(appId: unknown): appId is number {
  return typeof appId === "number" && Number.isInteger(appId) && appId > 0;
}

function validId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/**
 * A Downloads entry name as the Mods panel lists it: one plain name, never a
 * path. The backend refuses anything else too (`GameModFilesAdapter.source_path`);
 * refusing here keeps a path from ever leaving the frontend.
 */
export function isEntryName(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value !== "." && value !== ".." && !/[/\\:\0]/.test(value);
}

type Resolved = { romId: number } | ModFailure;

async function resolveRom(appId: unknown): Promise<Resolved> {
  if (!validAppId(appId)) return failure("invalid_argument", "appId must be a positive integer.");
  const detail = await getCachedGameDetail(appId);
  if (!detail.found || !detail.rom_id) return failure("not_a_rom", `App ${appId} is not a ROM in The Collector.`);
  return { romId: detail.rom_id };
}

function isFailure(value: Resolved): value is ModFailure {
  return "success" in value;
}

async function guarded<T>(what: string, run: () => Promise<T | ModFailure>): Promise<T | ModFailure> {
  try {
    return await run();
  } catch (e) {
    return failure("bridge_error", `${what} failed: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function withRom<T>(
  what: string,
  appId: unknown,
  run: (romId: number) => Promise<T | ModFailure>,
): Promise<T | ModFailure> {
  return guarded(what, async () => {
    const resolved = await resolveRom(appId);
    return isFailure(resolved) ? resolved : run(resolved.romId);
  });
}

async function targetOf(
  romId: number,
  targetId: string,
): Promise<{ info: GameModsInfo; target: GameModsInfo["targets"][number] } | ModFailure> {
  const info = await getGameMods(romId);
  if (!info.success) return info;
  const target = info.targets.find((t) => t.target_id === targetId);
  if (!target) return failure("not_found", `This game has no '${targetId}' mod folder.`);
  return { info, target };
}

export function createCollectorModsBridge(deps: CollectorModsBridgeDeps): CollectorModsBridge {
  const bridge: CollectorModsBridge = {
    version: COLLECTOR_MODS_VERSION,

    isRomApp(appId: number): boolean {
      try {
        return validAppId(appId) && deps.isRomApp(appId);
      } catch {
        return false;
      }
    },

    async getRomInfo(appId: number): Promise<BridgeRomInfo | null> {
      try {
        if (!validAppId(appId)) return null;
        const detail = await getCachedGameDetail(appId);
        if (!detail.found || !detail.rom_id) return null;
        const mods = await getGameMods(detail.rom_id).catch(() => null);
        const emulator = mods?.success ? (mods.emulator?.id ?? null) : null;
        return {
          appId,
          romId: detail.rom_id,
          name: detail.rom_name || "",
          platformSlug: detail.platform_slug || "",
          platformName: detail.platform_name || "",
          installed: detail.installed ?? false,
          locale: globalThis.navigator.language || "en",
          emulator,
          family: emulator ? (IDENTIFIER_FAMILIES[emulator] ?? null) : null,
          gameId: mods?.success ? mods.game_id : null,
        };
      } catch {
        return null;
      }
    },

    getTargets: (appId) => withRom("getTargets", appId, (romId) => getGameMods(romId)),

    listSources: (appId, targetId) =>
      withRom("listSources", appId, async (romId): Promise<ModSourcesAnswer> => {
        if (targetId !== undefined && !validId(targetId))
          return failure("invalid_argument", "targetId must be a string.");
        let target = targetId;
        if (target === undefined) {
          const info = await getGameMods(romId);
          if (!info.success) return info;
          const first = info.targets[0];
          if (!first) return failure("no_target", info.note ?? "This game has no known mod folder.");
          target = first.target_id;
        }
        return listModSources(romId, target);
      }),

    preview: (appId, source, targetId) =>
      withRom("preview", appId, async (romId): Promise<ModPreviewAnswer> => {
        if (!isEntryName(source))
          return failure("invalid_source", "source must be a Downloads entry name, not a path.");
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        return previewModInstall(romId, targetId, source);
      }),

    install: (appId, source, targetId, fingerprint) =>
      withRom("install", appId, async (romId): Promise<ModInstallAnswer> => {
        if (!isEntryName(source))
          return failure("invalid_source", "source must be a Downloads entry name, not a path.");
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        if (!validId(fingerprint)) return failure("invalid_argument", "fingerprint must be the preview's fingerprint.");
        return installMod(romId, targetId, source, fingerprint);
      }),

    listInstalled: (appId, targetId) =>
      withRom("listInstalled", appId, async (romId): Promise<ListInstalledAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        const found = await targetOf(romId, targetId);
        if ("success" in found) return found;
        return {
          success: true,
          target_id: targetId,
          entries: found.target.installed,
          truncated: found.target.installed_truncated,
        };
      }),

    remove: (appId, targetId, name) =>
      withRom("remove", appId, async (romId): Promise<ModRemoveAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        if (name !== null && !isEntryName(name))
          return failure("invalid_argument", "name must be an entry name the backend listed, or null.");
        return removeMod(romId, targetId, name);
      }),

    readSetting: (appId, targetId) =>
      withRom("readSetting", appId, async (romId): Promise<ReadSettingAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        const found = await targetOf(romId, targetId);
        if ("success" in found) return found;
        return { success: true, target_id: targetId, setting: found.target.setting };
      }),

    enableSetting: (appId, targetId) =>
      withRom("enableSetting", appId, async (romId): Promise<ModSettingAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        return enableModSetting(romId, targetId);
      }),

    openFolder: (appId, targetId) =>
      withRom("openFolder", appId, async (romId): Promise<ModOpenAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        return openModFolder(romId, targetId);
      }),

    listBuiltins: (appId, targetId) =>
      withRom("listBuiltins", appId, async (romId): Promise<ModBuiltinsAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        return listModBuiltins(romId, targetId);
      }),

    setBuiltin: (appId, targetId, entryId, enabled) =>
      withRom("setBuiltin", appId, async (romId): Promise<ModBuiltinSetAnswer> => {
        if (!validId(targetId)) return failure("invalid_argument", "targetId must be a string.");
        if (!validId(entryId)) return failure("invalid_argument", "entryId must be an entry_id listBuiltins answered.");
        if (typeof enabled !== "boolean") return failure("invalid_argument", "enabled must be true or false.");
        return setModBuiltin(romId, targetId, entryId, enabled);
      }),
  };
  return Object.freeze(bridge);
}

/**
 * Publish the bridge on `window` and announce it. Returns the uninstall
 * function, which withdraws the global only if it is still this one.
 */
export function installCollectorModsBridge(deps: CollectorModsBridgeDeps): () => void {
  const bridge = createCollectorModsBridge(deps);
  const target = globalThis as unknown as Record<string, unknown>;
  target[COLLECTOR_MODS_GLOBAL] = bridge;
  globalThis.dispatchEvent(
    new CustomEvent(COLLECTOR_MODS_READY_EVENT, { detail: { version: COLLECTOR_MODS_VERSION } }),
  );
  return () => {
    if (target[COLLECTOR_MODS_GLOBAL] === bridge) delete target[COLLECTOR_MODS_GLOBAL];
  };
}
