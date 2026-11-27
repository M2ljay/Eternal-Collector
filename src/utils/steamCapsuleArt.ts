/**
 * The portrait capsule art Steam's own library shows for a shortcut, as an ordered
 * list of image URLs to try.
 *
 * Synchronous and local: it reads Steam's `appStore` only, never the plugin
 * backend or the network, so the Home row and the console page can call it while
 * they render.
 *
 * Order:
 * 1. `appStore.GetCustomVerticalCapsuleURLs(overview)` — the custom grid art with
 *    the `?v=<rt_custom_image_mtime>` cache-buster Steam's own capsules use. The
 *    plugin's cover lands there through `SetCustomArtworkForApp`.
 * 2. `/customimages/<appId>p.png` / `.jpg` (with the same cache-buster) — the same
 *    grid files without Steam's listing. The backend also writes the cached RomM
 *    cover to `<appId>p.png`, so this is the plugin's already-cached cover, read
 *    without a backend call.
 * 3. `appStore.GetVerticalCapsuleURLForApp(overview)` — whatever else Steam would
 *    draw for the app.
 *
 * Duplicates and empty values are dropped; an exception from Steam's store leaves
 * the grid URLs alone.
 */
export function capsuleArtSources(appId: number): string[] {
  if (!Number.isInteger(appId) || appId <= 0) return [];
  let custom: unknown[] = [];
  let generated: unknown;
  let version: unknown;
  try {
    const store = typeof appStore === "undefined" ? undefined : appStore;
    const overview = store?.GetAppOverviewByAppID(appId) ?? null;
    if (store && overview) {
      version = overview.rt_custom_image_mtime;
      const listed = store.GetCustomVerticalCapsuleURLs?.(overview);
      if (Array.isArray(listed)) custom = listed;
      generated = store.GetVerticalCapsuleURLForApp?.(overview);
    }
  } catch {
    custom = [];
    generated = undefined;
  }
  const suffix = typeof version === "number" && version > 0 ? `?v=${version}` : "";
  const grid = [`/customimages/${appId}p.png${suffix}`, `/customimages/${appId}p.jpg${suffix}`];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const url of [...custom, ...grid, generated]) {
    if (typeof url !== "string" || url === "" || seen.has(url)) continue;
    seen.add(url);
    out.push(url);
  }
  return out;
}
