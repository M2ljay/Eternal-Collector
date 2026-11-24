/**
 * Steam collection management for RomM platforms.
 * Uses Steam's internal collectionStore API.
 *
 * Collection names are machine-scoped to prevent cross-device conflicts
 * when Steam Cloud syncs collections: "RomM: Platform (hostname)". On Windows
 * they are plain instead: "Platform" and "[Collection]".
 */

import { logInfo, logWarn, logError } from "../api/backend";
import { isRomMAppId } from "../patches/gameDetailPatch";

let _hostname = "";

export async function getHostname(): Promise<string> {
  if (_hostname) return _hostname;
  try {
    const info = await SteamClient.System.GetSystemInfo();
    _hostname = info.sHostname || "unknown";
  } catch {
    _hostname = "unknown";
  }
  return _hostname;
}

function getOverviews(appIds: number[]): AppStoreOverview[] {
  const overviews: AppStoreOverview[] = [];
  for (const appId of appIds) {
    if (typeof appStore !== "undefined") {
      const overview = appStore.GetAppOverviewByAppID(appId);
      if (overview) {
        overviews.push(overview);
        continue;
      }
    }
    // Fallback: construct a minimal overview
    overviews.push({ appid: appId, display_name: "", strDisplayName: "" });
  }
  return overviews;
}

/**
 * Replace an existing collection's apps. Returns false when the signal aborted
 * mid-write, so the caller stops the whole run instead of moving to the next
 * collection.
 */
async function replaceCollectionApps(
  existing: SteamCollection,
  overviews: AppStoreOverview[],
  signal?: AbortSignal,
): Promise<boolean> {
  const existingApps = existing.allApps;
  if (existingApps.length > 0) {
    if (signal?.aborted) return false;
    existing.AsDragDropCollection().RemoveApps(existingApps);
  }
  if (signal?.aborted) return false;
  existing.AsDragDropCollection().AddApps(overviews);
  if (signal?.aborted) return false;
  await existing.Save();
  return true;
}

/** Create a new collection holding exactly *overviews*. False means aborted mid-write. */
async function createCollectionWithApps(
  collectionName: string,
  overviews: AppStoreOverview[],
  signal?: AbortSignal,
): Promise<boolean> {
  const collection = collectionStore.NewUnsavedCollection(collectionName, undefined, []);
  if (signal?.aborted) return false;
  collection.AsDragDropCollection().AddApps(overviews);
  if (signal?.aborted) return false;
  await collection.Save();
  return true;
}

/** Point one collection name at exactly *overviews*, creating it if it is new. */
async function saveCollection(
  collectionName: string,
  noun: string,
  overviews: AppStoreOverview[],
  appCount: number,
  signal?: AbortSignal,
): Promise<boolean> {
  // Case-insensitive match: Steam collapses collection names by a
  // case-insensitive identity, so a case-variant collection ("RomM: [7 Up]
  // (host)" vs "RomM: [7 up] (host)") must be UPDATED, not shadowed by a
  // colliding new create that then overwrites it and loses its games (#1569).
  const target = collectionName.toLowerCase();
  const existing = collectionStore.userCollections.find((c) => c.displayName.toLowerCase() === target);

  if (existing) {
    logInfo(`Updating ${noun} "${collectionName}" with ${appCount} apps`);
    if (!(await replaceCollectionApps(existing, overviews, signal))) return false;
  } else {
    logInfo(`Creating ${noun} "${collectionName}" with ${appCount} apps`);
    if (!(await createCollectionWithApps(collectionName, overviews, signal))) return false;
  }
  logInfo(`Successfully saved ${noun} "${collectionName}"`);
  return true;
}

function plainCollectionNames(): boolean {
  return navigator.userAgent.includes("Windows");
}

function platformCollectionName(platformName: string, hostname: string): string {
  return plainCollectionNames() ? platformName : `RomM: ${platformName} (${hostname})`;
}

function rommCollectionName(collName: string, hostname: string): string {
  return plainCollectionNames() ? `[${collName}]` : `RomM: [${collName}] (${hostname})`;
}

/** Case-insensitive lookup: Steam's collection identity is case-insensitive (#1569). */
function findCollection(name: string): SteamCollection | undefined {
  const target = name.toLowerCase();
  return collectionStore.userCollections.find((c) => c.displayName.toLowerCase() === target);
}

/** True for a non-empty collection whose every app is a RomM shortcut. */
function isRomMOnlyCollection(c: SteamCollection): boolean {
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- `allApps` is a Steam-internal mobx field; a collection that has not loaded its apps yet must read as empty, not throw.
  const apps = c.allApps || [];
  return apps.length > 0 && apps.every((a) => isRomMAppId(a.appid));
}

/**
 * Under plain names, delete the old-style collections each new name replaces —
 * only once the new collection exists, so the games are never left without one.
 */
async function retireOldCollectionNames(pairs: Array<[string, string[]]>, signal?: AbortSignal): Promise<void> {
  if (!plainCollectionNames()) return;
  for (const [newName, oldNames] of pairs) {
    if (!findCollection(newName)) continue;
    for (const oldName of oldNames) {
      const old = findCollection(oldName);
      if (!old || old.displayName.toLowerCase() === newName.toLowerCase()) continue;
      if (signal?.aborted) return;
      logInfo(`Removing old-style collection "${old.displayName}" (now "${newName}")`);
      await old.Delete();
    }
  }
}

/**
 * Write one family of collections, reporting progress per entry. A failure on
 * one collection is logged and the rest still run; an abort stops the run.
 */
async function saveCollectionFamily(
  entries: Array<[string, number[]]>,
  noun: string,
  collectionNameFor: (source: string) => string,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  let idx = 0;
  for (const [source, appIds] of entries) {
    if (signal?.aborted) return;
    idx++;
    onProgress?.(idx, entries.length, source);
    const collectionName = collectionNameFor(source);
    const overviews = getOverviews(appIds);

    try {
      if (!(await saveCollection(collectionName, noun, overviews, appIds.length, signal))) return;
    } catch (colErr) {
      logError(`Failed to save ${noun} "${collectionName}": ${colErr}`);
    }
  }
}

export async function createOrUpdateCollections(
  platformAppIds: Record<string, number[]>,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, skipping collections");
      return;
    }

    const hostname = await getHostname();
    if (signal?.aborted) return;
    logInfo(
      `Creating/updating collections for platforms: ${Object.keys(platformAppIds).join(", ")} (hostname: ${hostname})`,
    );

    await saveCollectionFamily(
      Object.entries(platformAppIds),
      "collection",
      (platformName) => platformCollectionName(platformName, hostname),
      onProgress,
      signal,
    );
    await retireOldCollectionNames(
      Object.keys(platformAppIds).map((p) => [
        platformCollectionName(p, hostname),
        [`RomM: ${p} (${hostname})`, `RomM: ${p}`],
      ]),
      signal,
    );
  } catch (e) {
    logError(`Failed to update collections: ${e}`);
  }
}

export async function createOrUpdateRomMCollections(
  collectionAppIds: Record<string, number[]>,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, skipping RomM collections");
      return;
    }

    const hostname = await getHostname();
    if (signal?.aborted) return;
    logInfo(`Creating/updating RomM collections: ${Object.keys(collectionAppIds).join(", ")} (hostname: ${hostname})`);

    await saveCollectionFamily(
      Object.entries(collectionAppIds),
      "RomM collection",
      (collName) => rommCollectionName(collName, hostname),
      onProgress,
      signal,
    );
    await retireOldCollectionNames(
      Object.keys(collectionAppIds).map((n) => [
        rommCollectionName(n, hostname),
        [`RomM: [${n}] (${hostname})`, `RomM: [${n}]`],
      ]),
      signal,
    );
  } catch (e) {
    logError(`Failed to update RomM collections: ${e}`);
  }
}

export async function clearPlatformCollection(platformName: string, signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear platform collection");
      return;
    }
    const hostname = await getHostname();
    if (signal?.aborted) return;
    const scopedName = `RomM: ${platformName} (${hostname})`;
    const legacyName = `RomM: ${platformName}`;

    // Case-insensitive match on the full name: Steam's collection identity is
    // case-insensitive, so a case-variant of this platform's collection is the
    // SAME Steam collection and must still be found for deletion (#1569).
    const scopedTarget = scopedName.toLowerCase();
    const legacyTarget = legacyName.toLowerCase();

    // Delete the machine-scoped collection
    const scoped = collectionStore.userCollections.find((c) => c.displayName.toLowerCase() === scopedTarget);
    if (scoped) {
      logInfo(`Deleting collection "${scopedName}" (id=${scoped.id})`);
      if (signal?.aborted) return;
      await scoped.Delete();
    }

    // Also clean up legacy collection (without hostname suffix) if it exists
    const legacy = collectionStore.userCollections.find((c) => c.displayName.toLowerCase() === legacyTarget);
    if (legacy) {
      logInfo(`Deleting legacy collection "${legacyName}" (id=${legacy.id})`);
      if (signal?.aborted) return;
      await legacy.Delete();
    }

    // A plain-named collection is deleted only while it holds nothing but RomM
    // shortcuts: the name alone could be a collection the user made themselves.
    const plain = plainCollectionNames() ? findCollection(platformName) : undefined;
    if (plain && isRomMOnlyCollection(plain)) {
      logInfo(`Deleting collection "${plain.displayName}" (id=${plain.id})`);
      if (signal?.aborted) return;
      await plain.Delete();
    }

    if (!scoped && !legacy && !plain) {
      logInfo(`Collection "${scopedName}" not found, nothing to clear`);
    }
  } catch (e) {
    logError(`Failed to clear platform collection: ${e}`);
  }
}

export async function clearAllRomMCollections(signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear collections");
      return;
    }
    const hostname = await getHostname();
    if (signal?.aborted) return;
    const suffix = ` (${hostname})`;
    const lowerSuffix = suffix.toLowerCase();

    // Match collections belonging to this machine OR legacy ones without any hostname suffix.
    // Covers both platform collections ("RomM: PlatformName (hostname)") and
    // RomM collection-based collections ("RomM: [CollectionName] (hostname)").
    // Legacy collections match "RomM: ..." but do NOT have a parenthesized suffix.
    // This avoids deleting collections from other devices like "RomM: N64 (othermachine)".
    // Prefix + host-suffix are compared case-insensitively (Steam's collection
    // identity is case-insensitive, so a case-variant of one of our names is the
    // same collection and must still be swept, #1569).
    const rommCollections = collectionStore.userCollections.filter((c) => {
      const lower = c.displayName.toLowerCase();
      if (plainCollectionNames() && !lower.startsWith("romm: ") && isRomMOnlyCollection(c)) return true;
      if (!lower.startsWith("romm: ")) return false;
      // This machine's scoped collections (both platform and RomM collection style)
      if (lower.endsWith(lowerSuffix)) return true;
      // Legacy collections: start with "RomM: " but have no " (...)" suffix at all
      if (!/\s\([^)]+\)$/.test(c.displayName)) return true;
      return false;
    });

    logInfo(`Deleting ${rommCollections.length} RomM collections (hostname: ${hostname})`);
    for (const c of rommCollections) {
      if (signal?.aborted) return;
      logInfo(`Deleting collection "${c.displayName}" (id=${c.id})`);
      await c.Delete();
    }
  } catch (e) {
    logError(`Failed to clear collections: ${e}`);
  }
}
