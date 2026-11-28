/**
 * Where A on a family tile of The Collector's Home row goes.
 *
 * The Library groups consoles by family through a collection or a tab named after
 * the family ("PlayStation", "Nintendo", "Sega", "Xbox", "Retro"; Core's Library
 * tabs and TabMaster use the same names). A Steam collection with that name opens
 * at `/library/collection/<id>`. TabMaster's tabs are its own state with no route
 * or public API to select one, so they are not reached from here. Without such a
 * collection, the tile opens the console page of the family's most played console.
 */

import { Navigation } from "@decky/ui";
import { consoleFamily, FAMILY_NAMES, type ConsoleFamily } from "../theme/coreTokens";
import type { ShelfConsole } from "../types";
import { collectionIdNamed } from "./steamCollectionLookup";
import { consolePagePath } from "./consoleMedia";

/** The route a family tile opens, or `null` when the family has nowhere to go. */
export function familyRoute(family: ConsoleFamily, consoles: readonly ShelfConsole[]): string | null {
  const collection = collectionIdNamed(FAMILY_NAMES[family]);
  if (collection) return `/library/collection/${encodeURIComponent(collection)}`;
  const top = consoles.find((c) => consoleFamily(c.platform_slug) === family);
  return top ? consolePagePath(top.platform_slug) : null;
}

export function openFamily(family: ConsoleFamily, consoles: readonly ShelfConsole[]): void {
  const route = familyRoute(family, consoles);
  if (route) Navigation.Navigate(route);
}
