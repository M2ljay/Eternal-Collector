import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as backend from "../api/backend";
import { applyCaseArt, letterboxRect, letterboxToPng, sniffImageMime } from "./caseArt";

const PNG_B64 = btoa("\x89PNG\r\n\x1a\n" + "\0".repeat(16));
const JPEG_B64 = btoa("\xff\xd8\xff\xe0" + "\0".repeat(16));
const WEBP_B64 = btoa("RIFF\0\0\0\0WEBPVP8 " + "\0".repeat(8));

interface DrawCall {
  fill: string;
  rects: number[][];
  image: number[];
}

/** A canvas + Image stand-in: happy-dom decodes no images and has no 2D context. */
function stubCanvas(natural: { w: number; h: number }, decodes = true): DrawCall {
  const draw: DrawCall = { fill: "", rects: [], image: [] };
  class FakeImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    naturalWidth = natural.w;
    naturalHeight = natural.h;
    width = natural.w;
    height = natural.h;
    set src(_value: string) {
      queueMicrotask(() => (decodes ? this.onload?.() : this.onerror?.()));
    }
  }
  vi.stubGlobal("Image", FakeImage);
  const ctx = {
    set fillStyle(v: string) {
      draw.fill = v;
    },
    fillRect: (...a: number[]) => draw.rects.push(a),
    drawImage: (_img: unknown, ...a: number[]) => {
      draw.image = a;
    },
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as never);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,TEVUVEVSQk9Y");
  return draw;
}

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  logError: vi.fn(),
}));

function errorLogged(): string {
  return vi
    .mocked(backend.logError)
    .mock.calls.map((c) => String(c[0]))
    .join("\n");
}

describe("letterboxRect", () => {
  it.each([
    [600, 900, { x: 0, y: 0, w: 600, h: 900 }],
    [1024, 1024, { x: 0, y: 150, w: 600, h: 600 }],
    [660, 930, { x: 0, y: 27, w: 600, h: 845 }],
    [342, 482, { x: 0, y: 27, w: 600, h: 846 }],
    [300, 900, { x: 150, y: 0, w: 300, h: 900 }],
  ])("fits %ix%i inside 600x900 and centres it (same rule as the backend)", (w, h, rect) => {
    expect(letterboxRect(w, h)).toEqual(rect);
  });

  it.each([
    [512, 512],
    [1920, 620],
    [104, 180],
  ])("never stretches %ix%i", (w, h) => {
    const r = letterboxRect(w, h);
    expect(r.w / r.h).toBeCloseTo(w / h, 1);
    expect(r.w === 600 || r.h === 900).toBe(true);
    expect(r.x).toBeGreaterThanOrEqual(0);
    expect(r.y).toBeGreaterThanOrEqual(0);
  });

  it("rejects an empty image", () => {
    expect(() => letterboxRect(0, 900)).toThrow();
  });
});

describe("sniffImageMime", () => {
  it("tells PNG, JPEG and WebP apart", () => {
    expect(sniffImageMime(PNG_B64)).toBe("image/png");
    expect(sniffImageMime(JPEG_B64)).toBe("image/jpeg");
    expect(sniffImageMime(WEBP_B64)).toBe("image/webp");
  });
});

describe("letterboxToPng", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("draws a square grid on a black 600x900 canvas, letterboxed top and bottom", async () => {
    const draw = stubCanvas({ w: 512, h: 512 });
    await expect(letterboxToPng(PNG_B64)).resolves.toBe("TEVUVEVSQk9Y");
    expect(draw.fill).toBe("#000");
    expect(draw.rects).toEqual([[0, 0, 600, 900]]);
    expect(draw.image).toEqual([0, 150, 600, 600]);
  });

  it("rejects when the grid cannot be decoded", async () => {
    stubCanvas({ w: 1, h: 1 }, false);
    await expect(letterboxToPng(PNG_B64)).rejects.toThrow("decode");
  });
});

describe("applyCaseArt", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("SteamClient", { Apps: { SetCustomArtworkForApp: vi.fn().mockResolvedValue(undefined) } });
    vi.mocked(backend.saveCaseArt).mockResolvedValue({ success: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("plain cover style changes nothing on an automatic pass", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({ success: true, state: "plain" });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("plain");
    expect(vi.mocked(backend.getCaseArtSource)).toHaveBeenCalledWith(41, null, false);
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).not.toHaveBeenCalled();
  });

  it("plain cover style on Refresh puts the plain cover back on the tile", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({ success: true, state: "plain" });
    vi.mocked(backend.getArtworkBase64).mockResolvedValue({ base64: "UExBSU4=" });
    await expect(applyCaseArt(41, 5000, { refresh: true })).resolves.toBe("plain");
    expect(vi.mocked(backend.getCaseArtSource)).toHaveBeenCalledWith(41, null, true);
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).toHaveBeenCalledWith(5000, "UExBSU4=", "png", 0);
  });

  it("case art already on the tile writes nothing and downloads nothing", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({ success: true, state: "current", grid_id: 9 });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("current");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).not.toHaveBeenCalled();
    expect(vi.mocked(backend.saveCaseArt)).not.toHaveBeenCalled();
  });

  it("cached case art is applied as is, without letterboxing or saving again", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({
      success: true,
      state: "cached",
      grid_id: 9,
      base64: "Q0FTRQ==",
    });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("applied");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).toHaveBeenCalledWith(5000, "Q0FTRQ==", "png", 0);
    expect(vi.mocked(backend.saveCaseArt)).not.toHaveBeenCalled();
  });

  it("a fetched grid is letterboxed, saved with its pick, then set on the portrait capsule only", async () => {
    stubCanvas({ w: 512, h: 512 });
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({
      success: true,
      state: "fetched",
      grid_id: 9,
      width: 512,
      height: 512,
      manual: true,
      base64: PNG_B64,
    });
    await expect(applyCaseArt(41, 5000, { gridId: 9 })).resolves.toBe("applied");
    expect(vi.mocked(backend.getCaseArtSource)).toHaveBeenCalledWith(41, 9, false);
    expect(vi.mocked(backend.saveCaseArt)).toHaveBeenCalledWith(41, 9, "TEVUVEVSQk9Y", true);
    const writes = vi.mocked(SteamClient.Apps.SetCustomArtworkForApp).mock.calls;
    expect(writes).toEqual([[5000, "TEVUVEVSQk9Y", "png", 0]]);
  });

  it("a refused save never reaches the tile", async () => {
    stubCanvas({ w: 600, h: 900 });
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({
      success: true,
      state: "fetched",
      grid_id: 9,
      width: 600,
      height: 900,
      manual: false,
      base64: PNG_B64,
    });
    vi.mocked(backend.saveCaseArt).mockResolvedValue({ success: false, reason: "invalid_payload" });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("failed");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).not.toHaveBeenCalled();
    expect(errorLogged()).toContain("refused");
  });

  it("no usable grid keeps the plain cover", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValue({ success: true, state: "none" });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("none");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).not.toHaveBeenCalled();
  });

  it("reports a missing API key and other failures without writing", async () => {
    vi.mocked(backend.getCaseArtSource).mockResolvedValueOnce({
      success: false,
      reason: "no_api_key",
      message: "x",
    });
    await expect(applyCaseArt(41, 5000)).resolves.toBe("no_api_key");
    vi.mocked(backend.getCaseArtSource).mockRejectedValueOnce(new Error("socket"));
    await expect(applyCaseArt(41, 5000)).resolves.toBe("failed");
    expect(errorLogged()).toContain("source request failed");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp)).not.toHaveBeenCalled();
  });

  it("a newer apply for the same shortcut wins over a slower older one", async () => {
    let release: (v: backend.CaseArtSource) => void = () => {};
    vi.mocked(backend.getCaseArtSource)
      .mockReturnValueOnce(new Promise((r) => (release = r)))
      .mockResolvedValueOnce({ success: true, state: "cached", grid_id: 2, base64: "TkVX" });
    const older = applyCaseArt(41, 5000);
    await expect(applyCaseArt(41, 5000)).resolves.toBe("applied");
    release({ success: true, state: "cached", grid_id: 1, base64: "T0xE" });
    await expect(older).resolves.toBe("failed");
    expect(vi.mocked(SteamClient.Apps.SetCustomArtworkForApp).mock.calls).toEqual([[5000, "TkVX", "png", 0]]);
  });
});
