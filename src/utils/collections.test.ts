import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createOrUpdateRomMCollections,
  createOrUpdateCollections,
  clearPlatformCollection,
  clearAllRomMCollections,
} from "./collections";

// The real module pulls in @decky/ui + the route patch; only RomM-shortcut
// membership is read here.
const rommAppIds = vi.hoisted(() => new Set<number>());
vi.mock("../patches/gameDetailPatch", () => ({
  isRomMAppId: (appId: number) => rommAppIds.has(appId),
}));

// Steam's collection identity is case-insensitive, so a collection whose
// displayName differs only by case from the one we're syncing is the SAME Steam
// collection. These tests pin that our create/find + cleanup match it
// case-insensitively — otherwise a colliding new create overwrites it and its
// games are lost (#1569). The getHostname mock (test-setup) resolves "test".

interface FakeDnd {
  RemoveApps: ReturnType<typeof vi.fn>;
  AddApps: ReturnType<typeof vi.fn>;
}
interface FakeCollection {
  id: string;
  displayName: string;
  allApps: unknown[];
  AsDragDropCollection: () => FakeDnd;
  Save: ReturnType<typeof vi.fn>;
  Delete: ReturnType<typeof vi.fn>;
  dnd: FakeDnd;
}

function fakeCollection(displayName: string): FakeCollection {
  const dnd: FakeDnd = { RemoveApps: vi.fn(), AddApps: vi.fn() };
  return {
    id: `id-${displayName}`,
    displayName,
    allApps: [],
    AsDragDropCollection: () => dnd,
    Save: vi.fn().mockResolvedValue(undefined),
    Delete: vi.fn().mockResolvedValue(undefined),
    dnd,
  };
}

describe("createOrUpdateRomMCollections — case-insensitive identity (#1569)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("updates an existing case-variant collection instead of creating a duplicate", async () => {
    // Steam already holds "RomM: [7 Up] (test)"; the reporter now emits the
    // folded-first-seen casing "7 up". Must UPDATE the existing one, not create a
    // colliding "7 up" that Steam merges over the top of.
    const existing = fakeCollection("RomM: [7 Up] (test)");
    const NewUnsavedCollection = vi.fn();
    vi.stubGlobal("collectionStore", { userCollections: [existing], NewUnsavedCollection });

    await createOrUpdateRomMCollections({ "7 up": [1001, 1002] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(existing.Save).toHaveBeenCalledTimes(1);
    expect(existing.dnd.AddApps).toHaveBeenCalledTimes(1);
  });

  it("creates a new collection when nothing matches even case-insensitively", async () => {
    // Non-vacuous complement: the find isn't matching everything — a genuinely
    // new name still creates.
    const created = fakeCollection("RomM: [brand new] (test)");
    const NewUnsavedCollection = vi.fn(() => created);
    vi.stubGlobal("collectionStore", { userCollections: [], NewUnsavedCollection });

    await createOrUpdateRomMCollections({ "brand new": [1] });

    expect(NewUnsavedCollection).toHaveBeenCalledTimes(1);
    expect(created.Save).toHaveBeenCalledTimes(1);
  });
});

describe("createOrUpdateCollections (platform) — case-insensitive identity (#1569)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("updates an existing case-variant platform collection instead of creating a duplicate", async () => {
    const existing = fakeCollection("RomM: Game Boy (test)");
    const NewUnsavedCollection = vi.fn();
    vi.stubGlobal("collectionStore", { userCollections: [existing], NewUnsavedCollection });

    await createOrUpdateCollections({ "game boy": [1001] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(existing.Save).toHaveBeenCalledTimes(1);
  });

  it("does not begin another collection mutation after cancellation", async () => {
    let settle!: () => void;
    const first = fakeCollection("RomM: First (test)");
    const pendingSave = new Promise<void>((resolve) => {
      settle = resolve;
    });
    first.Save.mockReturnValueOnce(pendingSave);
    const second = fakeCollection("RomM: Second (test)");
    vi.stubGlobal("collectionStore", { userCollections: [first, second], NewUnsavedCollection: vi.fn() });
    const controller = new AbortController();
    const applying = createOrUpdateCollections({ First: [1], Second: [2] }, undefined, controller.signal);
    await Promise.resolve();

    controller.abort();
    settle();
    await applying;

    expect(first.Save).toHaveBeenCalledTimes(1);
    expect(second.dnd.AddApps).not.toHaveBeenCalled();
    expect(second.Save).not.toHaveBeenCalled();
  });
});

describe("clearPlatformCollection — case-insensitive identity (#1569)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("deletes a case-variant scoped collection", async () => {
    // We ask to clear "game boy"; the live collection is "RomM: Game Boy (test)".
    const scoped = fakeCollection("RomM: Game Boy (test)");
    vi.stubGlobal("collectionStore", { userCollections: [scoped] });

    await clearPlatformCollection("game boy");

    expect(scoped.Delete).toHaveBeenCalledTimes(1);
  });
});

const WINDOWS_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Valve Steam Client";
const DECK_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Valve Steam Client";

describe("collections on Windows — plain names", () => {
  let userCollections: FakeCollection[];
  let NewUnsavedCollection: ReturnType<typeof vi.fn>;

  /** A collection holding the given app ids (RomM or not, per `rommAppIds`). */
  const holding = (displayName: string, appIds: number[]): FakeCollection => ({
    ...fakeCollection(displayName),
    allApps: appIds.map((appid) => ({ appid })),
  });

  const stubStore = (initial: FakeCollection[]): void => {
    userCollections = [...initial];
    // A created collection becomes visible to later lookups once saved, as in Steam.
    NewUnsavedCollection = vi.fn((name: string) => {
      const created = fakeCollection(name);
      created.Save.mockImplementation(() => {
        userCollections.push(created);
      });
      return created;
    });
    vi.stubGlobal("collectionStore", {
      get userCollections() {
        return userCollections;
      },
      NewUnsavedCollection,
    });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(WINDOWS_UA);
    vi.stubGlobal("SteamClient", { System: { GetSystemInfo: vi.fn().mockResolvedValue({ sHostname: "test" }) } });
    rommAppIds.clear();
    [1, 2, 3].forEach((id) => rommAppIds.add(id));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const created = (): string[] => NewUnsavedCollection.mock.calls.map((c) => c[0] as string);

  it("names a platform collection after the platform alone", async () => {
    stubStore([]);
    await createOrUpdateCollections({ "Nintendo 64": [1, 2] });
    expect(created()).toEqual(["Nintendo 64"]);
  });

  it("names a RomM collection [name]", async () => {
    stubStore([]);
    await createOrUpdateRomMCollections({ Favourites: [1] });
    expect(created()).toEqual(["[Favourites]"]);
  });

  it("keeps the host-scoped names off Windows", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(DECK_UA);
    stubStore([]);
    await createOrUpdateCollections({ "Nintendo 64": [1] });
    await createOrUpdateRomMCollections({ Favourites: [1] });
    expect(created()).toEqual(["RomM: Nintendo 64 (test)", "RomM: [Favourites] (test)"]);
  });

  it("updates a case-variant plain collection instead of creating another", async () => {
    const existing = holding("nintendo 64", [1]);
    stubStore([existing]);
    await createOrUpdateCollections({ "Nintendo 64": [1, 2] });
    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(existing.Save).toHaveBeenCalledTimes(1);
  });

  it("retires the RomM-only old-style platform collections once the new one exists", async () => {
    const scoped = holding("RomM: Nintendo 64 (test)", [1, 2]);
    const legacy = holding("ROMM: nintendo 64", [3]);
    stubStore([scoped, legacy]);

    await createOrUpdateCollections({ "Nintendo 64": [1, 2, 3] });

    expect(created()).toEqual(["Nintendo 64"]);
    expect(scoped.Delete).toHaveBeenCalledTimes(1);
    expect(legacy.Delete).toHaveBeenCalledTimes(1);
  });

  it("retires the RomM-only old-style RomM collections once the new one exists", async () => {
    const scoped = holding("RomM: [Favourites] (test)", [1]);
    const legacy = holding("RomM: [Favourites]", [2]);
    stubStore([scoped, legacy]);

    await createOrUpdateRomMCollections({ Favourites: [1, 2] });

    expect(scoped.Delete).toHaveBeenCalledTimes(1);
    expect(legacy.Delete).toHaveBeenCalledTimes(1);
  });

  it("never retires an old-style collection that also holds games which are not RomM shortcuts", async () => {
    const mixed = holding("RomM: Nintendo 64 (test)", [1, 900]);
    const romOnly = holding("RomM: Nintendo 64", [2]);
    stubStore([mixed, romOnly]);

    await createOrUpdateCollections({ "Nintendo 64": [1, 2] });

    expect(mixed.Delete).not.toHaveBeenCalled();
    expect(romOnly.Delete).toHaveBeenCalledTimes(1);
  });

  it("never retires an old-style collection whose apps have not loaded (reads as empty)", async () => {
    const unloaded = holding("RomM: Nintendo 64 (test)", []);
    stubStore([unloaded]);

    await createOrUpdateCollections({ "Nintendo 64": [1] });

    expect(unloaded.Delete).not.toHaveBeenCalled();
  });

  it("keeps the old-style collection when the new one was never saved", async () => {
    const scoped = holding("RomM: Nintendo 64 (test)", [1]);
    stubStore([scoped]);
    NewUnsavedCollection.mockImplementation((name: string) => {
      const failing = fakeCollection(name);
      failing.Save.mockRejectedValue(new Error("save failed"));
      return failing;
    });

    await createOrUpdateCollections({ "Nintendo 64": [1] });

    expect(scoped.Delete).not.toHaveBeenCalled();
  });

  it("retires nothing off Windows", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(DECK_UA);
    const legacy = holding("RomM: Nintendo 64", [1]);
    stubStore([legacy]);

    await createOrUpdateCollections({ "Nintendo 64": [1] });

    expect(legacy.Delete).not.toHaveBeenCalled();
  });

  it("stops retiring once the run is aborted", async () => {
    const scoped = holding("RomM: Nintendo 64 (test)", [1]);
    stubStore([holding("Nintendo 64", [1]), scoped]);
    const controller = new AbortController();
    const existingNew = userCollections[0]!;
    existingNew.Save.mockImplementation(() => {
      controller.abort();
    });

    await createOrUpdateCollections({ "Nintendo 64": [1] }, undefined, controller.signal);

    expect(scoped.Delete).not.toHaveBeenCalled();
  });

  it("clears a plain platform collection only while it holds nothing but RomM shortcuts", async () => {
    const romOnly = holding("Nintendo 64", [1, 2]);
    stubStore([romOnly]);
    await clearPlatformCollection("nintendo 64");
    expect(romOnly.Delete).toHaveBeenCalledTimes(1);

    const mixed = holding("Nintendo 64", [1, 900]);
    stubStore([mixed]);
    await clearPlatformCollection("Nintendo 64");
    expect(mixed.Delete).not.toHaveBeenCalled();
  });

  it("clears every RomM-only plain collection but no mixed or empty one", async () => {
    const romOnly = holding("[Favourites]", [1]);
    const mixed = holding("Nintendo 64", [2, 900]);
    const empty = holding("SNES", []);
    const scoped = holding("RomM: GBA (test)", [900]);
    stubStore([romOnly, mixed, empty, scoped]);

    await clearAllRomMCollections();

    expect(romOnly.Delete).toHaveBeenCalledTimes(1);
    expect(mixed.Delete).not.toHaveBeenCalled();
    expect(empty.Delete).not.toHaveBeenCalled();
    expect(scoped.Delete).toHaveBeenCalledTimes(1);
  });

  it("never clears a user's own plain-named collection off Windows", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(DECK_UA);
    const own = holding("Nintendo 64", [1, 2]);
    stubStore([own]);

    await clearAllRomMCollections();
    await clearPlatformCollection("Nintendo 64");

    expect(own.Delete).not.toHaveBeenCalled();
  });
});
