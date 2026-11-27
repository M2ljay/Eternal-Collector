/**
 * Game case cover art: puts a SteamGridDB case grid on a shortcut's portrait
 * capsule.
 *
 * The backend picks the grid (curated case-template authors first, then the
 * platform's case shape, then score; never NSFW) and hands the raw image here,
 * because Decky's Python has no image decoder. This module letterboxes it into
 * Steam's 600x900 capsule on black — never stretched — hands the PNG back for the
 * backend's cache, and sets it on the tile with SetCustomArtworkForApp. Hero,
 * logo, wide grid and icon are left alone (utils/artwork.ts owns them).
 */

import { getArtworkBase64, getCaseArtSource, saveCaseArt, debugLog, logError } from "../api/backend";
import type { CaseArtSource } from "../api/backend";
import {
  capturePruneLeaseAdmission,
  isPruneLeaseCancellation,
  isPruneLeaseCancelled,
  mountPruneLeaseOwner,
  withPruneLeases,
} from "./pruneLease";

export type CoverStyle = "case" | "plain";

export const CAPSULE_WIDTH = 600;
export const CAPSULE_HEIGHT = 900;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Fit an image inside the capsule keeping its aspect: scaled until one side meets
 * the box and centred on the other. The same rule as `letterbox_rect` in
 * py_modules/domain/case_art.py.
 */
export function letterboxRect(width: number, height: number, boxW = CAPSULE_WIDTH, boxH = CAPSULE_HEIGHT): Rect {
  if (!(width > 0) || !(height > 0)) throw new Error("image size must be positive");
  const scale = Math.min(boxW / width, boxH / height);
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));
  return { x: Math.floor((boxW - w) / 2), y: Math.floor((boxH - h) / 2), w, h };
}

/** The image type from its first bytes; SteamGridDB serves PNG, JPEG and WebP. */
export function sniffImageMime(base64: string): string {
  const head = atob(base64.slice(0, 24));
  if (head.startsWith("\x89PNG")) return "image/png";
  if (head.startsWith("\xff\xd8")) return "image/jpeg";
  if (head.startsWith("RIFF") && head.slice(8, 12) === "WEBP") return "image/webp";
  return "image/png";
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("grid image failed to decode"));
    img.src = src;
  });
}

/**
 * Draw the grid letterboxed on a black 600x900 canvas and return it as PNG base64.
 * One image is decoded at a time and the canvas is dropped right after, so the
 * renderer only holds this image transiently.
 */
export async function letterboxToPng(base64: string): Promise<string> {
  const img = await loadImage(`data:${sniffImageMime(base64)};base64,${base64}`);
  const canvas = document.createElement("canvas");
  canvas.width = CAPSULE_WIDTH;
  canvas.height = CAPSULE_HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d canvas");
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, CAPSULE_WIDTH, CAPSULE_HEIGHT);
  const r = letterboxRect(img.naturalWidth || img.width, img.naturalHeight || img.height);
  ctx.drawImage(img, r.x, r.y, r.w, r.h);
  const url = canvas.toDataURL("image/png");
  canvas.width = 0;
  canvas.height = 0;
  return url.slice(url.indexOf(",") + 1);
}

export type CaseArtOutcome = "applied" | "current" | "plain" | "none" | "no_api_key" | "failed";

/** Newest-apply-wins per appId, as in utils/artwork.ts: a stale apply never overwrites a newer one. */
const generations = new Map<number, number>();

export interface ApplyCaseArtOptions {
  /** The user asked for Refresh Artwork: re-download even what is cached. */
  refresh?: boolean;
  /** A grid the user chose in the picker. */
  gridId?: number | null;
}

/**
 * Apply the ROM's case cover to its shortcut's portrait capsule.
 *
 * - Plain cover style: nothing, except on Refresh, where the plain cover is put
 *   back on the tile (it may still show case art from before the switch).
 * - Case art already on the tile: nothing.
 * - Cached case art not on the tile yet: applied without any download.
 * - Otherwise the chosen grid is downloaded, letterboxed, stored and applied.
 * - No usable grid: the plain cover stays.
 *
 * Fail-soft: every failure is logged and reported as `"failed"`; the plain cover
 * the sync applied stays on the tile. Only a prune-lease cancellation (the page
 * was left mid-apply) is rethrown, so callers can tell teardown from failure.
 */
export async function applyCaseArt(
  romId: number,
  appId: number,
  options: ApplyCaseArtOptions = {},
): Promise<CaseArtOutcome> {
  const owner = `artwork:${appId}`;
  mountPruneLeaseOwner(owner);
  const admission = capturePruneLeaseAdmission(owner);
  const generation = (generations.get(appId) ?? 0) + 1;
  generations.set(appId, generation);
  const superseded = () => generations.get(appId) !== generation;

  let source: CaseArtSource | undefined;
  try {
    source = await getCaseArtSource(romId, options.gridId ?? null, !!options.refresh);
  } catch (e) {
    logError(`applyCaseArt: source request failed for rom ${romId}: ${e}`);
    return "failed";
  }
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- the wire answer is untyped at runtime; a backend without this callable answers nothing
  if (!source) return "failed";
  if (!source.success) {
    if (source.reason === "no_api_key") return "no_api_key";
    void debugLog(`applyCaseArt: rom ${romId}: ${source.reason} — ${source.message}`);
    return "failed";
  }
  if (source.state === "current") return "current";
  if (source.state === "none") return "none";
  if (source.state === "plain") {
    if (options.refresh) await reapplyPlainCover(romId, appId, superseded);
    return "plain";
  }

  const image = source;
  return withPruneLeases(
    [image.prune_lease_token],
    "Case art apply",
    async (signal) => {
      let png = image.base64;
      if (image.state === "fetched") {
        png = await letterboxToPng(image.base64);
        if (isPruneLeaseCancelled(signal) || superseded()) return "failed";
        const saved = await saveCaseArt(romId, image.grid_id, png, image.manual);
        if (!saved.success) {
          logError(`applyCaseArt: backend refused the case image for rom ${romId}: ${saved.reason}`);
          return "failed";
        }
      }
      if (isPruneLeaseCancelled(signal) || superseded()) return "failed";
      await SteamClient.Apps.SetCustomArtworkForApp(appId, png, "png", 0);
      return "applied";
    },
    owner,
    admission,
  ).catch((e: unknown): CaseArtOutcome => {
    // Leaving the game page is teardown, not a failure the caller should toast.
    if (isPruneLeaseCancellation(e, admission)) throw e;
    logError(`applyCaseArt: failed for rom ${romId} (appId ${appId}): ${e}`);
    return "failed";
  });
}

async function reapplyPlainCover(romId: number, appId: number, superseded: () => boolean): Promise<void> {
  try {
    const { base64 } = await getArtworkBase64(romId);
    if (base64 && !superseded()) await SteamClient.Apps.SetCustomArtworkForApp(appId, base64, "png", 0);
  } catch (e) {
    logError(`applyCaseArt: could not put the plain cover back for rom ${romId}: ${e}`);
  }
}
