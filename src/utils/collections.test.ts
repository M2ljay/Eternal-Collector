import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  reconcileSteamCollections,
  clearPlatformCollection,
  clearAllRomMCollections,
  reconcileInstalledRomsCollection,
  requestInstalledRomsCollectionUpdate,
  watchInstalledRomsCollection,
} from "./collections";
import type { OwnedSteamCollection } from "../types";

// The real module pulls in @decky/ui + the route patch; only RomM-shortcut
// membership is read here.
const rommAppIds = vi.hoisted(() => new Set<number>());
vi.mock("../patches/gameDetailPatch", () => ({
  isRomMAppId: (appId: number) => rommAppIds.has(appId),
}));

// The backend's ownership record, kept in memory with the same replace-by-source
// rule as the SQLite repository.
const backend = vi.hoisted(() => ({
  records: [] as OwnedSteamCollection[],
  nameStyle: "classic" as "classic" | "clean",
  adoptionDone: false,
  readFails: false,
  recordFails: false,
  installedEnabled: true,
  installedAppIds: [] as number[],
  installedReadFails: false,
}));
vi.mock("../api/backend", () => ({
  logInfo: vi.fn(),
  logWarn: vi.fn(),
  logError: vi.fn(),
  getOwnedSteamCollections: vi.fn(() =>
    Promise.resolve(
      backend.readFails
        ? { success: false, reason: "boom", message: "boom" }
        : {
            success: true,
            name_style: backend.nameStyle,
            adoption_done: backend.adoptionDone,
            collections: backend.records.map((r) => ({ ...r })),
          },
    ),
  ),
  recordOwnedSteamCollection: vi.fn(
    (
      collection_id: string,
      family: "platform" | "romm" | "installed",
      source_name: string,
      display_name: string,
      yielded_to,
    ) => {
      if (backend.recordFails) return Promise.resolve({ success: false, reason: "x", message: "x" });
      backend.records = backend.records.filter(
        (r) =>
          r.collection_id !== collection_id &&
          !(r.family === family && r.source_name.toLowerCase() === source_name.toLowerCase()),
      );
      backend.records.push({ collection_id, family, source_name, display_name, yielded_to: yielded_to ?? null });
      return Promise.resolve({ success: true });
    },
  ),
  forgetOwnedSteamCollection: vi.fn((collection_id: string) => {
    backend.records = backend.records.filter((r) => r.collection_id !== collection_id);
    return Promise.resolve({ success: true });
  }),
  getInstalledRomAppIds: vi.fn(() =>
    Promise.resolve(
      backend.installedReadFails
        ? { success: false, enabled: false, app_ids: [], reason: "boom", message: "boom" }
        : { success: true, enabled: backend.installedEnabled, app_ids: [...backend.installedAppIds] },
    ),
  ),
  finishSteamCollectionAdoption: vi.fn(() => {
    backend.adoptionDone = true;
    return Promise.resolve({ success: true });
  }),
}));

const WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Valve Steam Client";

/**
 * An in-memory collectionStore. A created collection appears once saved, as in
 * Steam. `displayName` reads `m_strName`, so writing that field renames in place
 * unless the store is built with `renameable: false`.
 */
class FakeCollection {
  m_strName: string | undefined;
  allApps: { appid: number }[];
  Save = vi.fn(() => {
    if (!this.store.collections.includes(this)) this.store.collections.push(this);
    return Promise.resolve();
  });
  Delete = vi.fn(() => {
    if (this.store.deleteFails) return Promise.reject(new Error("delete refused"));
    this.store.collections = this.store.collections.filter((c) => c !== this);
    return Promise.resolve();
  });
  private readonly fixedName: string;

  constructor(
    private readonly store: FakeStore,
    readonly id: string,
    name: string,
    appIds: number[],
  ) {
    this.fixedName = name;
    if (store.renameable) this.m_strName = name;
    this.allApps = appIds.map((appid) => ({ appid }));
  }

  get displayName(): string {
    return this.m_strName ?? this.fixedName;
  }

  AsDragDropCollection() {
    return {
      AddApps: (overviews: { appid: number }[]) => {
        for (const o of overviews) if (!this.allApps.some((a) => a.appid === o.appid)) this.allApps.push(o);
      },
      RemoveApps: (overviews: { appid: number }[]) => {
        const gone = new Set(overviews.map((o) => o.appid));
        this.allApps = this.allApps.filter((a) => !gone.has(a.appid));
      },
    };
  }
}

class FakeStore {
  collections: FakeCollection[] = [];
  deleteFails = false;
  shortcutsLoaded = true;
  private next = 1;

  constructor(readonly renameable = true) {}

  add(name: string, appIds: number[] = [], id?: string): FakeCollection {
    const c = new FakeCollection(this, id ?? `uc-seed-${this.next++}`, name, appIds);
    this.collections.push(c);
    return c;
  }

  install(): void {
    vi.stubGlobal("collectionStore", {
      get userCollections() {
        return store.collections;
      },
      get deckDesktopApps() {
        return store.shortcutsLoaded ? { apps: new Map() } : undefined;
      },
      NewUnsavedCollection: (name: string) => new FakeCollection(store, `uc-new-${store.next++}`, name, []),
    });
  }

  names(): string[] {
    return this.collections.map((c) => c.displayName).sort();
  }

  named(name: string): FakeCollection | undefined {
    return this.collections.find((c) => c.displayName === name);
  }
}

let store: FakeStore;

function own(
  collection: FakeCollection,
  family: "platform" | "romm" | "installed",
  source: string,
  yieldedTo: string | null = null,
) {
  backend.records.push({
    collection_id: collection.id,
    family,
    source_name: source,
    display_name: collection.displayName,
    yielded_to: yieldedTo,
  });
}

function recordFor(family: "platform" | "romm" | "installed", source: string): OwnedSteamCollection | undefined {
  return backend.records.find((r) => r.family === family && r.source_name.toLowerCase() === source.toLowerCase());
}

async function sync(
  platformAppIds: Record<string, number[]>,
  rommCollectionAppIds: Record<string, number[]> = {},
  cancelled = false,
  signal?: AbortSignal,
): Promise<void> {
  await reconcileSteamCollections({ platformAppIds, rommCollectionAppIds, cancelled }, signal);
}

beforeEach(() => {
  backend.records = [];
  backend.nameStyle = "classic";
  backend.adoptionDone = true;
  backend.readFails = false;
  backend.recordFails = false;
  backend.installedEnabled = true;
  backend.installedAppIds = [];
  backend.installedReadFails = false;
  rommAppIds.clear();
  [1, 2, 3, 4, 5].forEach((id) => rommAppIds.add(id));
  store = new FakeStore();
  store.install();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("reconcileSteamCollections — Classic names", () => {
  it("creates the host-scoped names off Windows and records them", async () => {
    await sync({ "Nintendo 64": [1] }, { Favourites: [2] });

    expect(store.names()).toEqual(["RomM: Nintendo 64 (test)", "RomM: [Favourites] (test)"]);
    expect(recordFor("platform", "Nintendo 64")?.display_name).toBe("RomM: Nintendo 64 (test)");
    expect(recordFor("romm", "Favourites")?.collection_id).toBe(store.named("RomM: [Favourites] (test)")?.id);
  });

  it("keeps the plain Windows names", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);

    await sync({ "Nintendo 64": [1] }, { Favourites: [2] });

    expect(store.names()).toEqual(["Nintendo 64", "[Favourites]"]);
  });

  it("updates an owned case-variant collection instead of creating another (#1569)", async () => {
    const existing = store.add("RomM: [7 Up] (test)", [9]);
    own(existing, "romm", "7 Up");

    await sync({}, { "7 up": [1, 2] });

    expect(store.collections).toHaveLength(1);
    expect(existing.allApps.map((a) => a.appid)).toEqual([1, 2]);
  });

  it("recreates an owned collection the user deleted in Steam and moves the record to it", async () => {
    backend.records.push({
      collection_id: "uc-gone",
      family: "platform",
      source_name: "Nintendo 64",
      display_name: "RomM: Nintendo 64 (test)",
      yielded_to: null,
    });

    await sync({ "Nintendo 64": [1] });

    const created = store.named("RomM: Nintendo 64 (test)");
    expect(created).toBeDefined();
    expect(backend.records).toEqual([
      {
        collection_id: created!.id,
        family: "platform",
        source_name: "Nintendo 64",
        display_name: "RomM: Nintendo 64 (test)",
        yielded_to: null,
      },
    ]);
  });
});

describe("reconcileSteamCollections — Clean names", () => {
  beforeEach(() => {
    backend.nameStyle = "clean";
  });

  it("names collections after the platform and the RomM collection alone", async () => {
    await sync({ "PlayStation 2": [1], "Nintendo 64": [2] }, { Favourites: [3] });

    expect(store.names()).toEqual(["Favourites", "Nintendo 64", "PlayStation 2"]);
    expect(recordFor("romm", "Favourites")?.yielded_to).toBeNull();
  });

  it("never takes over, refills or deletes the user's own collections", async () => {
    const vr = store.add("VR", [100]);
    const completed = store.add("Completed", [1, 2]);

    await sync({ "PlayStation 2": [1] }, { VR: [2], Completed: [3] });

    expect(vr.allApps.map((a) => a.appid)).toEqual([100]);
    expect(completed.allApps.map((a) => a.appid)).toEqual([1, 2]);
    expect(vr.Save).not.toHaveBeenCalled();
    expect(completed.Save).not.toHaveBeenCalled();
    expect(vr.Delete).not.toHaveBeenCalled();
    expect(completed.Delete).not.toHaveBeenCalled();
    expect(store.names()).toEqual(["Completed", "Completed (RomM)", "PlayStation 2", "VR", "VR (RomM)"]);
    expect(recordFor("romm", "VR")).toMatchObject({ display_name: "VR (RomM)", yielded_to: "VR" });
    expect(backend.records.some((r) => r.collection_id === vr.id || r.collection_id === completed.id)).toBe(false);
  });

  it("treats a same-named collection of the user's as theirs whatever it holds", async () => {
    const mine = store.add("PlayStation 2", [1, 2]);

    await sync({ "PlayStation 2": [1, 2, 3] });

    expect(mine.allApps.map((a) => a.appid)).toEqual([1, 2]);
    expect(store.named("PlayStation 2 (RomM)")?.allApps.map((a) => a.appid)).toEqual([1, 2, 3]);
  });

  it("counts on further suffixes when the suffixed name is taken too", async () => {
    store.add("VR", [100]);
    store.add("VR (RomM)", [101]);

    await sync({}, { VR: [1] });

    expect(store.named("VR (RomM 2)")).toBeDefined();
    expect(recordFor("romm", "VR")?.yielded_to).toBe("VR");
  });

  it("gives the bare name to the platform when a RomM collection shares it", async () => {
    await sync({ Arcade: [1] }, { Arcade: [2] });

    expect(recordFor("platform", "Arcade")?.display_name).toBe("Arcade");
    expect(recordFor("romm", "Arcade")).toMatchObject({ display_name: "Arcade (RomM)", yielded_to: null });
  });

  it("takes the wanted name back once the user's collection is gone", async () => {
    const owned = store.add("VR (RomM)", [1]);
    own(owned, "romm", "VR", "VR");

    await sync({}, { VR: [1] });

    expect(owned.displayName).toBe("VR");
    expect(recordFor("romm", "VR")).toMatchObject({ collection_id: owned.id, display_name: "VR", yielded_to: null });
  });
});

describe("reconcileSteamCollections — switching style", () => {
  it("renames owned collections in place, keeping their id and games", async () => {
    const n64 = store.add("RomM: Nintendo 64 (test)", [1, 2]);
    own(n64, "platform", "Nintendo 64");
    backend.nameStyle = "clean";

    await sync({ "Nintendo 64": [1, 2] });

    expect(store.collections).toEqual([n64]);
    expect(n64.displayName).toBe("Nintendo 64");
    expect(n64.allApps.map((a) => a.appid)).toEqual([1, 2]);
    expect(recordFor("platform", "Nintendo 64")).toMatchObject({ collection_id: n64.id, display_name: "Nintendo 64" });
  });

  it("copies into a new collection and deletes only the plugin's old one when Steam will not rename", async () => {
    store = new FakeStore(false);
    store.install();
    const old = store.add("RomM: [Favourites] (test)", [1, 50]);
    own(old, "romm", "Favourites");
    const usersOwn = store.add("Favourites old", [1]);
    backend.nameStyle = "clean";
    const order: string[] = [];
    old.Delete.mockImplementation(() => {
      order.push(`delete old, record now ${recordFor("romm", "Favourites")?.collection_id}`);
      store.collections = store.collections.filter((c) => c !== old);
      return Promise.resolve();
    });

    await sync({}, { Favourites: [1, 2] });

    const fresh = store.named("Favourites");
    expect(fresh).toBeDefined();
    expect(fresh!.id).not.toBe(old.id);
    expect(order).toEqual([`delete old, record now ${fresh!.id}`]);
    expect(fresh!.allApps.map((a) => a.appid)).toEqual([1, 2]);
    expect(recordFor("romm", "Favourites")?.collection_id).toBe(fresh!.id);
    expect(usersOwn.Delete).not.toHaveBeenCalled();
  });

  it("keeps the old collection when the copy cannot be recorded", async () => {
    store = new FakeStore(false);
    store.install();
    const old = store.add("RomM: [Favourites] (test)", [1]);
    own(old, "romm", "Favourites");
    backend.nameStyle = "clean";
    backend.recordFails = true;

    await sync({}, { Favourites: [1] });

    expect(old.Delete).not.toHaveBeenCalled();
    expect(recordFor("romm", "Favourites")?.collection_id).toBe(old.id);
  });
});

describe("reconcileSteamCollections — stale cleanup", () => {
  it("deletes only recorded collections whose source is gone", async () => {
    const snes = store.add("RomM: Super Nintendo (test)", [1]);
    own(snes, "platform", "Super Nintendo");
    const faves = store.add("RomM: [Faves] (test)", [2]);
    own(faves, "romm", "Faves");
    const lookalike = store.add("RomM: Game Boy (test)", [3]);
    const users = store.add("Completed", [4]);

    await sync({ "Nintendo 64": [1] });

    expect(snes.Delete).toHaveBeenCalledTimes(1);
    expect(faves.Delete).toHaveBeenCalledTimes(1);
    expect(lookalike.Delete).not.toHaveBeenCalled();
    expect(users.Delete).not.toHaveBeenCalled();
    expect(backend.records.map((r) => r.source_name)).toEqual(["Nintendo 64"]);
  });

  it("deletes nothing on a cancelled run but still creates what it reached", async () => {
    const snes = store.add("RomM: Super Nintendo (test)", [1]);
    own(snes, "platform", "Super Nintendo");

    await sync({ "Nintendo 64": [1] }, {}, true);

    expect(snes.Delete).not.toHaveBeenCalled();
    expect(recordFor("platform", "Super Nintendo")).toBeDefined();
    expect(store.named("RomM: Nintendo 64 (test)")).toBeDefined();
  });

  it("keeps the record when Steam refuses the delete", async () => {
    const snes = store.add("RomM: Super Nintendo (test)", [1]);
    own(snes, "platform", "Super Nintendo");
    store.deleteFails = true;

    await sync({});

    expect(recordFor("platform", "Super Nintendo")).toBeDefined();
  });

  it("forgets a stale record whose collection is already gone", async () => {
    backend.records.push({
      collection_id: "uc-gone",
      family: "platform",
      source_name: "Super Nintendo",
      display_name: "Super Nintendo",
      yielded_to: null,
    });

    await sync({});

    expect(backend.records).toEqual([]);
  });

  it("frees a stale collection's name for an active source", async () => {
    backend.nameStyle = "clean";
    const stale = store.add("Arcade", [1]);
    own(stale, "romm", "Arcade");

    await sync({ Arcade: [2] });

    expect(stale.Delete).toHaveBeenCalled();
    expect(recordFor("platform", "Arcade")?.display_name).toBe("Arcade");
  });
});

describe("reconcileSteamCollections — adopting pre-record collections", () => {
  beforeEach(() => {
    backend.adoptionDone = false;
  });

  it("adopts this host's RomM-prefixed collection and renames it under Clean", async () => {
    const n64 = store.add("RomM: Nintendo 64 (test)", [1, 100]);
    backend.nameStyle = "clean";

    await sync({ "Nintendo 64": [1] });

    expect(n64.displayName).toBe("Nintendo 64");
    expect(recordFor("platform", "Nintendo 64")?.collection_id).toBe(n64.id);
    expect(backend.adoptionDone).toBe(true);
  });

  it("adopts a plain Windows collection only while it holds nothing but RomM shortcuts", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    const n64 = store.add("Nintendo 64", [1, 2]);
    const ps2 = store.add("PlayStation 2", [1, 100]);

    await sync({ "Nintendo 64": [1], "PlayStation 2": [2] });

    expect(recordFor("platform", "Nintendo 64")?.collection_id).toBe(n64.id);
    expect(ps2.allApps.map((a) => a.appid)).toEqual([1, 100]);
    expect(recordFor("platform", "PlayStation 2")).toMatchObject({
      display_name: "PlayStation 2 (RomM)",
      yielded_to: "PlayStation 2",
    });
  });

  it("never adopts another device's collection", async () => {
    const other = store.add("RomM: Nintendo 64 (steamdeck)", [1]);

    await sync({ "Nintendo 64": [1] });

    expect(backend.records.some((r) => r.collection_id === other.id)).toBe(false);
    expect(other.Save).not.toHaveBeenCalled();
  });

  it("is not marked done after a cancelled run", async () => {
    await sync({ "Nintendo 64": [1] }, {}, true);

    expect(backend.adoptionDone).toBe(false);
  });

  it("does not adopt once it is done", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    backend.adoptionDone = true;
    const n64 = store.add("Nintendo 64", [1]);

    await sync({ "Nintendo 64": [1] });

    expect(backend.records.some((r) => r.collection_id === n64.id)).toBe(false);
    expect(recordFor("platform", "Nintendo 64")?.display_name).toBe("Nintendo 64 (RomM)");
  });
});

describe("reconcileSteamCollections — refusals", () => {
  it("touches nothing when the ownership record cannot be read", async () => {
    backend.readFails = true;
    const n64 = store.add("RomM: Nintendo 64 (test)", [1]);

    await sync({ "Nintendo 64": [1, 2] });

    expect(store.collections).toEqual([n64]);
    expect(n64.Save).not.toHaveBeenCalled();
  });

  it("does not begin another collection after cancellation", async () => {
    const controller = new AbortController();
    controller.abort();

    await sync({ "Nintendo 64": [1] }, { Favourites: [2] }, false, controller.signal);

    expect(store.collections).toEqual([]);
  });
});

describe("clearPlatformCollection / clearAllRomMCollections", () => {
  it("clears only the platform's recorded collection", async () => {
    const n64 = store.add("RomM: Nintendo 64 (test)", [1]);
    own(n64, "platform", "Nintendo 64");
    const lookalike = store.add("Nintendo 64", [1]);

    await clearPlatformCollection("nintendo 64");

    expect(n64.Delete).toHaveBeenCalledTimes(1);
    expect(lookalike.Delete).not.toHaveBeenCalled();
    expect(backend.records).toEqual([]);
  });

  it("clears nothing for a platform the plugin owns no collection for", async () => {
    const users = store.add("RomM: Nintendo 64 (test)", [1]);

    await clearPlatformCollection("Nintendo 64");

    expect(users.Delete).not.toHaveBeenCalled();
  });

  it("clears every recorded collection and nothing else", async () => {
    const n64 = store.add("Nintendo 64", [1]);
    own(n64, "platform", "Nintendo 64");
    const faves = store.add("Favourites", [2]);
    own(faves, "romm", "Favourites");
    const romOnlyUsers = store.add("Completed", [1, 2]);

    await clearAllRomMCollections();

    expect(n64.Delete).toHaveBeenCalled();
    expect(faves.Delete).toHaveBeenCalled();
    expect(romOnlyUsers.Delete).not.toHaveBeenCalled();
    expect(backend.records).toEqual([]);
  });
});

describe("reconcileInstalledRomsCollection", () => {
  it("is named like a platform: plain on Windows", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    backend.installedAppIds = [1, 2];

    await reconcileInstalledRomsCollection();

    expect(store.names()).toEqual(["Installed ROMs"]);
    expect(appIdsOf(store.named("Installed ROMs"))).toEqual([1, 2]);
    expect(recordFor("installed", "Installed ROMs")?.collection_id).toBe(store.named("Installed ROMs")?.id);
  });

  it("follows the name style off Windows", async () => {
    await reconcileInstalledRomsCollection();
    expect(store.names()).toEqual(["RomM: Installed ROMs (test)"]);

    backend.nameStyle = "clean";
    await reconcileInstalledRomsCollection();
    expect(store.names()).toEqual(["Installed ROMs"]);
    expect(backend.records).toHaveLength(1);
  });

  it("refills its recorded collection to exactly the installed set", async () => {
    backend.nameStyle = "clean";
    const owned = store.add("Installed ROMs", [1, 2, 3]);
    own(owned, "installed", "Installed ROMs");
    backend.installedAppIds = [2, 4];

    await reconcileInstalledRomsCollection();

    expect(store.collections).toHaveLength(1);
    expect(appIdsOf(owned)).toEqual([2, 4]);
  });

  it("keeps the collection, empty, when nothing is installed", async () => {
    backend.nameStyle = "clean";
    const owned = store.add("Installed ROMs", [1]);
    own(owned, "installed", "Installed ROMs");

    await reconcileInstalledRomsCollection();

    expect(appIdsOf(owned)).toEqual([]);
    expect(owned.Delete).not.toHaveBeenCalled();
  });

  it("never touches the user's own collection of that name; its own gets the (RomM) suffix", async () => {
    backend.nameStyle = "clean";
    const users = store.add("Installed ROMs", [42]);
    backend.installedAppIds = [1];

    await reconcileInstalledRomsCollection();

    expect(appIdsOf(users)).toEqual([42]);
    expect(users.Save).not.toHaveBeenCalled();
    expect(appIdsOf(store.named("Installed ROMs (RomM)"))).toEqual([1]);
    expect(recordFor("installed", "Installed ROMs")).toMatchObject({
      display_name: "Installed ROMs (RomM)",
      yielded_to: "Installed ROMs",
    });
  });

  it("switched off, deletes only its recorded collection and forgets it", async () => {
    backend.nameStyle = "clean";
    const owned = store.add("Installed ROMs (RomM)", [1]);
    own(owned, "installed", "Installed ROMs", "Installed ROMs");
    const users = store.add("Installed ROMs", [1]);
    backend.installedEnabled = false;

    await reconcileInstalledRomsCollection();

    expect(owned.Delete).toHaveBeenCalledTimes(1);
    expect(users.Delete).not.toHaveBeenCalled();
    expect(store.names()).toEqual(["Installed ROMs"]);
    expect(backend.records).toEqual([]);
  });

  it("switched off with no record, creates and deletes nothing", async () => {
    backend.nameStyle = "clean";
    const users = store.add("Installed ROMs", [1]);
    backend.installedEnabled = false;

    await reconcileInstalledRomsCollection();

    expect(users.Delete).not.toHaveBeenCalled();
    expect(store.names()).toEqual(["Installed ROMs"]);
  });

  it("touches nothing when the record or the installed set cannot be read", async () => {
    backend.readFails = true;
    await reconcileInstalledRomsCollection();
    backend.readFails = false;
    backend.installedReadFails = true;
    await reconcileInstalledRomsCollection();

    expect(store.collections).toEqual([]);
    expect(backend.records).toEqual([]);
  });

  it("a sync's stale cleanup leaves the installed collection alone", async () => {
    backend.nameStyle = "clean";
    const owned = store.add("Installed ROMs", [1]);
    own(owned, "installed", "Installed ROMs");

    await sync({ "Nintendo 64": [1] });

    expect(owned.Delete).not.toHaveBeenCalled();
    expect(recordFor("installed", "Installed ROMs")).toBeDefined();
  });

  it("Remove all clears the installed collection with the rest of the plugin's own", async () => {
    const owned = store.add("Installed ROMs", [1]);
    own(owned, "installed", "Installed ROMs");

    await clearAllRomMCollections();

    expect(owned.Delete).toHaveBeenCalled();
    expect(backend.records).toEqual([]);
  });

  it("concurrent passes make one collection, not two", async () => {
    backend.nameStyle = "clean";
    backend.installedAppIds = [1];

    await Promise.all([reconcileInstalledRomsCollection(), reconcileInstalledRomsCollection()]);

    expect(store.names()).toEqual(["Installed ROMs"]);
    expect(backend.records).toHaveLength(1);
  });

  describe("at plugin start", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("waits for a recorded collection Steam has not loaded yet instead of making another", async () => {
      backend.nameStyle = "clean";
      backend.installedAppIds = [1];
      backend.records.push({
        collection_id: "uc-late",
        family: "installed",
        source_name: "Installed ROMs",
        display_name: "Installed ROMs",
        yielded_to: null,
      });
      store.shortcutsLoaded = false;

      const done = reconcileInstalledRomsCollection({ waitForSteam: true });
      await vi.advanceTimersByTimeAsync(3_000);
      store.shortcutsLoaded = true;
      const late = store.add("Installed ROMs", [], "uc-late");
      await vi.advanceTimersByTimeAsync(1_000);
      await done;

      expect(store.collections).toEqual([late]);
      expect(appIdsOf(late)).toEqual([1]);
      expect(recordFor("installed", "Installed ROMs")?.collection_id).toBe("uc-late");
    });

    it("gives up waiting after a bound and recreates a collection the user deleted", async () => {
      backend.nameStyle = "clean";
      backend.records.push({
        collection_id: "uc-gone",
        family: "installed",
        source_name: "Installed ROMs",
        display_name: "Installed ROMs",
        yielded_to: null,
      });

      const done = reconcileInstalledRomsCollection({ waitForSteam: true });
      await vi.advanceTimersByTimeAsync(31_000);
      await done;

      expect(store.names()).toEqual(["Installed ROMs"]);
      expect(recordFor("installed", "Installed ROMs")?.collection_id).toBe(store.named("Installed ROMs")?.id);
    });
  });
});

describe("installed-collection triggers", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    backend.nameStyle = "clean";
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("collapses a burst of requests into one reconcile", async () => {
    backend.installedAppIds = [1];
    const { getInstalledRomAppIds } = await import("../api/backend");
    vi.mocked(getInstalledRomAppIds).mockClear();
    requestInstalledRomsCollectionUpdate();
    requestInstalledRomsCollectionUpdate();
    requestInstalledRomsCollectionUpdate();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(vi.mocked(getInstalledRomAppIds)).toHaveBeenCalledTimes(1);
    expect(appIdsOf(store.named("Installed ROMs"))).toEqual([1]);
  });

  it.each([
    [
      "an adoption",
      () => new CustomEvent("romm_data_changed", { detail: { type: "rom_adopted" as const, rom_id: 1 } }),
    ],
    [
      "a version switch",
      () =>
        new CustomEvent("romm_data_changed", { detail: { type: "version_switched" as const, app_id: 1, rom_id: 2 } }),
    ],
    [
      "a removed-game cleanup",
      () =>
        new CustomEvent("romm_data_changed", { detail: { type: "rom_pruned" as const, app_ids: [1], rom_ids: [1] } }),
    ],
    ["an uninstall", () => new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: 1 } })],
  ])("reconciles after %s", async (_label, event) => {
    backend.installedAppIds = [3];
    const stop = watchInstalledRomsCollection();
    globalThis.dispatchEvent(event());
    await vi.advanceTimersByTimeAsync(1_000);
    stop();

    expect(appIdsOf(store.named("Installed ROMs"))).toEqual([3]);
  });

  it("ignores changes that do not move an install, and stops listening when stopped", async () => {
    const stop = watchInstalledRomsCollection();
    globalThis.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "metadata", rom_id: 1 } }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.collections).toEqual([]);

    stop();
    globalThis.dispatchEvent(new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: 1 } }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(store.collections).toEqual([]);
  });
});

function appIdsOf(c: FakeCollection | undefined): number[] | undefined {
  return c?.allApps.map((a) => a.appid);
}
