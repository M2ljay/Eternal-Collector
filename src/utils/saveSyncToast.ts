/**
 * Save-sync completion toast copy (#250, #1481) — the single source of the
 * per-direction wording for every surface that confirms a sync. A run can move
 * saves either way (a pre-launch download OR a row-9 upload; a post-exit upload
 * OR a row-5/10 adopt-download), so a single "synced" line hid which direction
 * actually ran.
 *
 * ``saveSyncToastBody`` names the single direction when saves moved only one
 * way, both counts when a run went both ways, and returns ``null`` when nothing
 * transferred so a no-op sync fires no toast. Every surface renders through this
 * helper from the per-direction counts on its result — pre-launch
 * (``CustomPlayButton``), post-exit (``sessionManager``, from the
 * ``finalize_game_session`` payload), and the manual per-game sync
 * (``RomMPlaySection``). The backend delivers the counts as data, never this
 * copy; it owns only the offline/failure body it renders itself (#1481).
 */

/**
 * The toast body for a completed save-sync, or ``null`` for a no-op run.
 *
 * @param uploaded - files POSTed to RomM this run (absent → 0).
 * @param downloaded - files pulled from RomM this run, including a 409-backstop
 *   download of an upload that lost the currency race (absent → 0).
 */
export function saveSyncToastBody(uploaded?: number, downloaded?: number): string | null {
  const up = uploaded ?? 0;
  const down = downloaded ?? 0;
  if (up > 0 && down > 0) return `Saves synced with RomM (${up} up, ${down} down)`;
  if (up > 0) return "Saves uploaded to RomM";
  if (down > 0) return "Saves downloaded from RomM";
  return null;
}

/**
 * The after-exit toast body with the savestate backup's clause added (ADR-0031).
 *
 * Nothing changes when no savestate was backed up. Otherwise the clause follows
 * whichever body the save sync produced ("Saves uploaded to RomM · 2 savestates
 * backed up"), or stands alone when the save sync had nothing to say.
 *
 * @param body - the save-sync toast body, or ``null`` when none fires.
 * @param savestatesBackedUp - savestates uploaded after the save sync (absent → 0).
 */
export function withSavestateClause(body: string | null, savestatesBackedUp?: number): string | null {
  const count = savestatesBackedUp ?? 0;
  if (count <= 0) return body;
  const noun = count === 1 ? "savestate" : "savestates";
  if (body === null) return `${count} ${noun} backed up to RomM`;
  return `${body} · ${count} ${noun} backed up`;
}
