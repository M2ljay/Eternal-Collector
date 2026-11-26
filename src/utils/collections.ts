/**
 * The plugin's own Steam collections, managed through Steam's internal
 * collectionStore.
 *
 * Ownership is the backend's record of Steam collection ids, never a name: a
 * collection with no record is the user's, and nothing here renames, refills or
 * deletes it, whatever it is called. See "Collection management" in
 * docs/architecture/steam-non-steam-shortcuts.md.
 */

import {
  finishSteamCollectionAdoption,
  forgetOwnedSteamCollection,
  getOwnedSteamCollections,
  logError,
  logInfo,
  logWarn,
  recordOwnedSteamCollection,
} from "../api/backend";
import { isRomMAppId } from "../patches/gameDetailPatch";
import type { CollectionNameStyle, OwnedSteamCollection, SteamCollectionFamily } from "../types";

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

/** The suffix a collection gets when the name it wants is already taken. */
export const NAME_TAKEN_SUFFIX = "RomM";
const MAX_SUFFIX_ATTEMPTS = 9;

export interface CollectionMaps {
  platformAppIds: Record<string, number[]>;
  rommCollectionAppIds: Record<string, number[]>;
  /**
   * A cancelled run's maps list only the sources it reached, so they are not
   * the complete active set and the stale cleanup must not run.
   */
  cancelled: boolean;
}

interface Source {
  family: SteamCollectionFamily;
  name: string;
  appIds: number[];
}

interface Ownership {
  style: CollectionNameStyle;
  adoptionDone: boolean;
  hostname: string;
  byId: Map<string, OwnedSteamCollection>;
  byKey: Map<string, OwnedSteamCollection>;
}

function sourceKey(family: SteamCollectionFamily, name: string): string {
  return `${family}:${name.toLowerCase()}`;
}

function plainCollectionNames(): boolean {
  return navigator.userAgent.includes("Windows");
}

/** The name the plugin has always given a source on this OS. */
export function classicCollectionName(family: SteamCollectionFamily, source: string, hostname: string): string {
  if (plainCollectionNames()) return family === "platform" ? source : `[${source}]`;
  return family === "platform" ? `RomM: ${source} (${hostname})` : `RomM: [${source}] (${hostname})`;
}

export function wantedCollectionName(
  style: CollectionNameStyle,
  family: SteamCollectionFamily,
  source: string,
  hostname: string,
): string {
  return style === "clean" ? source : classicCollectionName(family, source, hostname);
}

/** Names this device may have used for a source before ownership was recorded. */
function preRecordNames(family: SteamCollectionFamily, source: string, hostname: string): string[] {
  const label = family === "platform" ? source : `[${source}]`;
  const names = [classicCollectionName(family, source, hostname), `RomM: ${label} (${hostname})`, `RomM: ${label}`];
  return names.filter((name, i) => names.findIndex((n) => n.toLowerCase() === name.toLowerCase()) === i);
}

function liveCollections(): SteamCollection[] {
  return collectionStore.userCollections;
}

function liveById(id: string): SteamCollection | undefined {
  return liveCollections().find((c) => c.id === id);
}

/** Case-insensitive: Steam folds collection names by case (#1569). */
function liveByName(name: string): SteamCollection[] {
  const target = name.toLowerCase();
  return liveCollections().filter((c) => c.displayName.toLowerCase() === target);
}

/** True for a non-empty collection whose every app is a RomM shortcut. */
function isRomMOnlyCollection(c: SteamCollection): boolean {
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- `allApps` is a Steam-internal mobx field; a collection that has not loaded its apps yet must read as empty, not throw.
  const apps = c.allApps || [];
  return apps.length > 0 && apps.every((a) => isRomMAppId(a.appid));
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
    overviews.push({ appid: appId, display_name: "", strDisplayName: "" });
  }
  return overviews;
}

async function loadOwnership(): Promise<Ownership | null> {
  try {
    const answer = await getOwnedSteamCollections();
    if (!answer.success) {
      logWarn(`Steam collections left alone: the ownership record could not be read (${answer.message ?? ""})`);
      return null;
    }
    const byId = new Map<string, OwnedSteamCollection>();
    const byKey = new Map<string, OwnedSteamCollection>();
    for (const record of answer.collections) {
      byId.set(record.collection_id, record);
      byKey.set(sourceKey(record.family, record.source_name), record);
    }
    return {
      style: answer.name_style === "clean" ? "clean" : "classic",
      adoptionDone: answer.adoption_done,
      hostname: await getHostname(),
      byId,
      byKey,
    };
  } catch (e) {
    logWarn(`Steam collections left alone: the ownership record could not be read (${e})`);
    return null;
  }
}

async function record(
  ownership: Ownership,
  collectionId: string,
  family: SteamCollectionFamily,
  sourceName: string,
  displayName: string,
  yieldedTo: string | null,
): Promise<boolean> {
  try {
    const result = await recordOwnedSteamCollection(collectionId, family, sourceName, displayName, yieldedTo);
    if (!result.success) {
      logError(`Could not record Steam collection "${displayName}" as the plugin's: ${result.message ?? ""}`);
      return false;
    }
  } catch (e) {
    logError(`Could not record Steam collection "${displayName}" as the plugin's: ${e}`);
    return false;
  }
  const entry: OwnedSteamCollection = {
    collection_id: collectionId,
    family,
    source_name: sourceName,
    display_name: displayName,
    yielded_to: yieldedTo,
  };
  const key = sourceKey(family, sourceName);
  const previous = ownership.byKey.get(key);
  if (previous && previous.collection_id !== collectionId) ownership.byId.delete(previous.collection_id);
  ownership.byId.set(collectionId, entry);
  ownership.byKey.set(key, entry);
  return true;
}

async function forget(ownership: Ownership, owned: OwnedSteamCollection): Promise<void> {
  try {
    const result = await forgetOwnedSteamCollection(owned.collection_id);
    if (!result.success) {
      logError(`Could not forget Steam collection "${owned.display_name}": ${result.message ?? ""}`);
      return;
    }
  } catch (e) {
    logError(`Could not forget Steam collection "${owned.display_name}": ${e}`);
    return;
  }
  ownership.byId.delete(owned.collection_id);
  ownership.byKey.delete(sourceKey(owned.family, owned.source_name));
}

/**
 * Delete one owned collection, then forget it. The record goes only once the
 * collection is gone, so a failed delete leaves it owned and retried later.
 */
async function deleteOwned(ownership: Ownership, owned: OwnedSteamCollection, signal?: AbortSignal): Promise<void> {
  const live = liveById(owned.collection_id);
  if (live) {
    if (signal?.aborted) return;
    logInfo(`Deleting collection "${live.displayName}" (id=${live.id})`);
    try {
      await live.Delete();
    } catch (e) {
      logError(`Failed to delete collection "${live.displayName}": ${e}`);
      return;
    }
  }
  await forget(ownership, owned);
}

/**
 * Bring this device's pre-record collections under the record, once. A
 * collection is adopted only under a name this device used for the source, and
 * only when it carries the plugin's own "RomM: " prefix or holds nothing but
 * RomM shortcuts — so a user's collection that merely shares a name stays theirs.
 */
async function adoptPreRecordCollections(ownership: Ownership, sources: Source[], signal?: AbortSignal): Promise<void> {
  for (const source of sources) {
    if (signal?.aborted) return;
    if (ownership.byKey.has(sourceKey(source.family, source.name))) continue;
    for (const name of preRecordNames(source.family, source.name, ownership.hostname)) {
      const candidate = liveByName(name).find((c) => !ownership.byId.has(c.id));
      if (!candidate) continue;
      if (!name.toLowerCase().startsWith("romm: ") && !isRomMOnlyCollection(candidate)) {
        logInfo(`Not adopting "${candidate.displayName}": it holds games that are not RomM shortcuts`);
        continue;
      }
      logInfo(`Adopting existing collection "${candidate.displayName}" as the plugin's`);
      await record(ownership, candidate.id, source.family, source.name, candidate.displayName, null);
      break;
    }
  }
}

interface PickedName {
  name: string;
  yieldedTo: string | null;
}

/**
 * The name a source's collection gets: the wanted one when it is free, else the
 * wanted one with a suffix. A name is taken when another live collection holds
 * it, or another source already took it in this run.
 */
function pickName(
  ownership: Ownership,
  wanted: string,
  owned: SteamCollection | undefined,
  reserved: Set<string>,
): PickedName | null {
  let yieldedTo: string | null = null;
  for (let attempt = 0; attempt <= MAX_SUFFIX_ATTEMPTS; attempt++) {
    const suffix =
      attempt === 0 ? "" : attempt === 1 ? ` (${NAME_TAKEN_SUFFIX})` : ` (${NAME_TAKEN_SUFFIX} ${attempt})`;
    const name = `${wanted}${suffix}`;
    if (reserved.has(name.toLowerCase())) continue;
    const holders = liveByName(name).filter((c) => c.id !== owned?.id);
    if (holders.length === 0) return { name, yieldedTo };
    const userHolder = holders.find((c) => !ownership.byId.has(c.id));
    if (attempt === 0 && userHolder) yieldedTo = userHolder.displayName;
  }
  return null;
}

/** Create a collection holding exactly *overviews* and return it, or null if aborted. */
async function createCollection(
  name: string,
  overviews: AppStoreOverview[],
  signal?: AbortSignal,
): Promise<SteamCollection | null> {
  const collection = collectionStore.NewUnsavedCollection(name, undefined, []);
  if (signal?.aborted) return null;
  collection.AsDragDropCollection().AddApps(overviews);
  if (signal?.aborted) return null;
  await collection.Save();
  return liveById(collection.id) ?? liveByName(name)[0] ?? collection;
}

/** Point an owned collection at exactly *overviews*. False means aborted mid-write. */
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

/**
 * Rename in place, keeping Steam's collection id and membership. The collection
 * object Steam hands out (src/types/steam.d.ts) has no rename method. Setting
 * its internal `m_strName` and saving is an unverified guess at where Steam
 * keeps the name, so the rename only counts when the store then reports the new
 * name; otherwise the old name is put back and the caller falls back to a copy.
 */
async function renameInPlace(collection: SteamCollection, name: string): Promise<boolean> {
  const internal = collection as unknown as { m_strName?: unknown };
  if (typeof internal.m_strName !== "string") return false;
  const previous = internal.m_strName;
  internal.m_strName = name;
  try {
    await collection.Save();
  } catch (e) {
    internal.m_strName = previous;
    logWarn(`Renaming collection "${previous}" in place failed: ${e}`);
    return false;
  }
  const after = liveById(collection.id) ?? collection;
  if (after.displayName.toLowerCase() === name.toLowerCase()) return true;
  internal.m_strName = previous;
  await collection.Save();
  return false;
}

/**
 * Rename an owned collection. In place where Steam allows it; otherwise a new
 * collection takes a copy of every game in the old one, is recorded, and only
 * then is the old one deleted — so its games exist in the new collection before
 * the old one goes. Returns the collection now carrying *name*, or null.
 */
async function renameOwned(
  ownership: Ownership,
  source: Source,
  owned: SteamCollection,
  name: string,
  yieldedTo: string | null,
  signal?: AbortSignal,
): Promise<SteamCollection | null> {
  logInfo(`Renaming collection "${owned.displayName}" to "${name}"`);
  if (await renameInPlace(owned, name)) return owned;
  if (signal?.aborted) return null;
  const copy = await createCollection(name, owned.allApps, signal);
  if (!copy) return null;
  if (!(await record(ownership, copy.id, source.family, source.name, copy.displayName, yieldedTo))) {
    logWarn(`Collection "${name}" was made but could not be recorded; "${owned.displayName}" is kept`);
    return null;
  }
  if (signal?.aborted) return copy;
  try {
    await owned.Delete();
  } catch (e) {
    logWarn(`Collection "${owned.displayName}" was replaced by "${name}" but could not be deleted: ${e}`);
  }
  return copy;
}

async function reconcileSource(
  ownership: Ownership,
  source: Source,
  reserved: Set<string>,
  signal?: AbortSignal,
): Promise<void> {
  const recorded = ownership.byKey.get(sourceKey(source.family, source.name));
  const owned = recorded ? liveById(recorded.collection_id) : undefined;
  const wanted = wantedCollectionName(ownership.style, source.family, source.name, ownership.hostname);
  const picked = pickName(ownership, wanted, owned, reserved);
  if (!picked) {
    logWarn(`No free collection name for "${source.name}": "${wanted}" and its suffixed forms are all taken`);
    return;
  }
  reserved.add(picked.name.toLowerCase());
  if (picked.yieldedTo) {
    logWarn(
      `"${picked.yieldedTo}" is your own collection, so the plugin's collection for "${source.name}" is "${picked.name}"`,
    );
  }
  const overviews = getOverviews(source.appIds);

  let target: SteamCollection | null;
  if (owned) {
    target =
      owned.displayName.toLowerCase() === picked.name.toLowerCase()
        ? owned
        : await renameOwned(ownership, source, owned, picked.name, picked.yieldedTo, signal);
    if (!target || signal?.aborted) return;
    logInfo(`Updating collection "${target.displayName}" with ${source.appIds.length} apps`);
    if (!(await replaceCollectionApps(target, overviews, signal))) return;
  } else {
    logInfo(`Creating collection "${picked.name}" with ${source.appIds.length} apps`);
    target = await createCollection(picked.name, overviews, signal);
    if (!target) return;
  }

  const current = ownership.byKey.get(sourceKey(source.family, source.name));
  const unchanged =
    current?.collection_id === target.id &&
    current.display_name === target.displayName &&
    current.source_name === source.name &&
    current.yielded_to === picked.yieldedTo;
  if (!unchanged) {
    await record(ownership, target.id, source.family, source.name, target.displayName, picked.yieldedTo);
  }
}

async function removeStaleOwned(ownership: Ownership, sources: Source[], signal?: AbortSignal): Promise<void> {
  const active = new Set(sources.map((s) => sourceKey(s.family, s.name)));
  for (const owned of [...ownership.byId.values()]) {
    if (signal?.aborted) return;
    if (active.has(sourceKey(owned.family, owned.source_name))) continue;
    logInfo(`Removing stale collection "${owned.display_name}"`);
    await deleteOwned(ownership, owned, signal);
  }
}

function sourcesOf(maps: CollectionMaps): Source[] {
  return [
    ...Object.entries(maps.platformAppIds).map(([name, appIds]) => ({ family: "platform" as const, name, appIds })),
    ...Object.entries(maps.rommCollectionAppIds).map(([name, appIds]) => ({ family: "romm" as const, name, appIds })),
  ];
}

/**
 * Bring the plugin's Steam collections in line with one sync's maps.
 *
 * Only recorded collections are renamed, refilled or deleted. The stale cleanup
 * runs before the writes, so a freed name is available to them, and only on a
 * run that was not cancelled. The one-time adoption of pre-record collections
 * is marked done only after such a run.
 */
export async function reconcileSteamCollections(maps: CollectionMaps, signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, skipping collections");
      return;
    }
    const ownership = await loadOwnership();
    if (!ownership || signal?.aborted) return;
    const sources = sourcesOf(maps);

    if (!ownership.adoptionDone) await adoptPreRecordCollections(ownership, sources, signal);
    if (!maps.cancelled) await removeStaleOwned(ownership, sources, signal);

    const reserved = new Set<string>();
    for (const source of sources) {
      if (signal?.aborted) return;
      try {
        await reconcileSource(ownership, source, reserved, signal);
      } catch (e) {
        logError(`Failed to save collection for "${source.name}": ${e}`);
      }
    }

    if (!maps.cancelled && !ownership.adoptionDone && !signal?.aborted) {
      await finishSteamCollectionAdoption();
    }
  } catch (e) {
    logError(`Failed to manage RomM collections: ${e}`);
  }
}

/** Delete the plugin's own collection for one platform, if it has one. */
export async function clearPlatformCollection(platformName: string, signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear platform collection");
      return;
    }
    const ownership = await loadOwnership();
    if (!ownership || signal?.aborted) return;
    const owned = ownership.byKey.get(sourceKey("platform", platformName));
    if (!owned) {
      logInfo(`The plugin owns no collection for "${platformName}", nothing to clear`);
      return;
    }
    await deleteOwned(ownership, owned, signal);
  } catch (e) {
    logError(`Failed to clear platform collection: ${e}`);
  }
}

/** Delete every collection the plugin owns on this device. */
export async function clearAllRomMCollections(signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear collections");
      return;
    }
    const ownership = await loadOwnership();
    if (!ownership || signal?.aborted) return;
    logInfo(`Deleting ${ownership.byId.size} collections the plugin owns`);
    for (const owned of [...ownership.byId.values()]) {
      if (signal?.aborted) return;
      await deleteOwned(ownership, owned, signal);
    }
  } catch (e) {
    logError(`Failed to clear collections: ${e}`);
  }
}
