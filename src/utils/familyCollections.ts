/**
 * Maps a console-family collection's source name ("PlayStation", …) to its
 * family. The collection itself is found through the ownership record
 * (`owned_steam_collections`, family `console_family`) in `utils/collections.ts`,
 * never by a name lookup.
 */

import { FAMILY_NAMES, FAMILY_ORDER, type ConsoleFamily } from "../theme/coreTokens";

/** The family whose collection source is named *sourceName* ("PlayStation", …), if any. */
export function familyOfSource(sourceName: string): ConsoleFamily | undefined {
  const name = sourceName.toLowerCase();
  return FAMILY_ORDER.find((f) => FAMILY_NAMES[f].toLowerCase() === name);
}
