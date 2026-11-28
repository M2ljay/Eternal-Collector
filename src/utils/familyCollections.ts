/**
 * Which Steam collection is the plugin's own collection for each console family,
 * as the ownership record says (`owned_steam_collections`, family
 * `console_family`). Filled by `utils/collections.ts` whenever it reads the
 * record, and read by the Home shelf when A is pressed — never by a name lookup,
 * and never with a backend call on the Home render path.
 */

import { FAMILY_NAMES, FAMILY_ORDER, type ConsoleFamily } from "../theme/coreTokens";

let byFamily = new Map<ConsoleFamily, string>();

/** The family whose collection source is named *sourceName* ("PlayStation", …), if any. */
export function familyOfSource(sourceName: string): ConsoleFamily | undefined {
  const name = sourceName.toLowerCase();
  return FAMILY_ORDER.find((f) => FAMILY_NAMES[f].toLowerCase() === name);
}

/** Replace the known family collections with those in a fresh read of the record. */
export function setFamilyCollections(
  records: readonly { family: string; source_name: string; collection_id: string }[],
): void {
  const next = new Map<ConsoleFamily, string>();
  for (const r of records) {
    const family = r.family === "console_family" ? familyOfSource(r.source_name) : undefined;
    if (family) next.set(family, r.collection_id);
  }
  byFamily = next;
}

/** The recorded collection id of a family's collection, if the plugin has one. */
export function familyCollectionId(family: ConsoleFamily): string | null {
  return byFamily.get(family) ?? null;
}

/** Test-only: forget every family collection. */
export function resetFamilyCollections(): void {
  byFamily = new Map();
}
