import { describe, it, expect, vi, afterEach } from "vitest";
import { capsuleArtSources } from "./steamCapsuleArt";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubStore(store: Record<string, unknown>) {
  vi.stubGlobal("appStore", store);
}

describe("capsuleArtSources", () => {
  it("uses Steam's own custom capsule URLs first, then the grid files, then Steam's generated capsule", () => {
    const overview = { appid: 7001, rt_custom_image_mtime: 1700000000 };
    const custom = vi.fn(() => ["https://steamloopback.host/customimages/7001p.png?v=1700000000"]);
    stubStore({
      GetAppOverviewByAppID: vi.fn(() => overview),
      GetCustomVerticalCapsuleURLs: custom,
      GetVerticalCapsuleURLForApp: vi.fn(() => "/assets/7001/library_600x900.jpg"),
    });
    expect(capsuleArtSources(7001)).toEqual([
      "https://steamloopback.host/customimages/7001p.png?v=1700000000",
      "/customimages/7001p.png?v=1700000000",
      "/customimages/7001p.jpg?v=1700000000",
      "/assets/7001/library_600x900.jpg",
    ]);
    expect(custom).toHaveBeenCalledWith(overview);
  });

  it("drops duplicates and empty values", () => {
    stubStore({
      GetAppOverviewByAppID: () => ({ appid: 7002 }),
      GetCustomVerticalCapsuleURLs: () => ["/customimages/7002p.png", "", "/customimages/7002p.png"],
      GetVerticalCapsuleURLForApp: () => "",
    });
    expect(capsuleArtSources(7002)).toEqual(["/customimages/7002p.png", "/customimages/7002p.jpg"]);
  });

  it("falls back to the grid files when Steam does not know the app or has no appStore", () => {
    expect(capsuleArtSources(7003)).toEqual(["/customimages/7003p.png", "/customimages/7003p.jpg"]);
    stubStore({ GetAppOverviewByAppID: () => null });
    expect(capsuleArtSources(7003)).toEqual(["/customimages/7003p.png", "/customimages/7003p.jpg"]);
  });

  it("survives a Steam store that throws", () => {
    stubStore({
      GetAppOverviewByAppID: () => ({ appid: 7004 }),
      GetCustomVerticalCapsuleURLs: () => {
        throw new Error("renamed");
      },
    });
    expect(capsuleArtSources(7004)).toEqual(["/customimages/7004p.png", "/customimages/7004p.jpg"]);
  });

  it("has nothing for an app id that is not a shortcut's", () => {
    expect(capsuleArtSources(0)).toEqual([]);
    expect(capsuleArtSources(Number.NaN)).toEqual([]);
  });
});
