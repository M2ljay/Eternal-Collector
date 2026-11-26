import { describe, it, expect } from "vitest";
import { saveSyncToastBody, withSavestateClause } from "./saveSyncToast";

describe("saveSyncToastBody", () => {
  it("names uploads when saves only moved up", () => {
    expect(saveSyncToastBody(2, 0)).toBe("Saves uploaded to RomM");
  });

  it("names downloads when saves only moved down", () => {
    expect(saveSyncToastBody(0, 3)).toBe("Saves downloaded from RomM");
  });

  it("names both counts when a run went both ways", () => {
    expect(saveSyncToastBody(1, 2)).toBe("Saves synced with RomM (1 up, 2 down)");
  });

  it("returns null for a no-op run (nothing transferred)", () => {
    expect(saveSyncToastBody(0, 0)).toBeNull();
  });

  it("treats absent counts as zero → null", () => {
    expect(saveSyncToastBody(undefined, undefined)).toBeNull();
  });

  it("treats a missing upload count as zero", () => {
    expect(saveSyncToastBody(undefined, 1)).toBe("Saves downloaded from RomM");
  });
});

describe("withSavestateClause", () => {
  it("leaves the body alone when no savestate was backed up", () => {
    expect(withSavestateClause("Saves uploaded to RomM", 0)).toBe("Saves uploaded to RomM");
    expect(withSavestateClause(null, 0)).toBeNull();
  });

  it("treats an absent count as zero", () => {
    expect(withSavestateClause("Saves uploaded to RomM", undefined)).toBe("Saves uploaded to RomM");
    expect(withSavestateClause(null, undefined)).toBeNull();
  });

  it("appends the plural clause to the save-sync body", () => {
    expect(withSavestateClause("Saves uploaded to RomM", 2)).toBe("Saves uploaded to RomM · 2 savestates backed up");
  });

  it("uses the singular for one savestate", () => {
    expect(withSavestateClause("Saves downloaded from RomM", 1)).toBe(
      "Saves downloaded from RomM · 1 savestate backed up",
    );
  });

  it("stands alone when the save sync had nothing to say", () => {
    expect(withSavestateClause(null, 3)).toBe("3 savestates backed up to RomM");
    expect(withSavestateClause(null, 1)).toBe("1 savestate backed up to RomM");
  });
});
