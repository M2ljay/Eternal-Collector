/**
 * Where A on a family tile of The Collector's Home row goes.
 *
 * The plugin keeps one Steam collection per console family; the ownership record
 * names it (`utils/familyCollections.ts`), and it opens at
 * `/library/collection/<id>` while Steam still has it. TabMaster's tabs are its own
 * state with no route or public API to select one, so they are not reached from
 * here. Without a family collection (the setting off, or none made yet), the tile
 * opens the console page of the family's most played console.
 */

import { Navigation } from "@decky/ui";
import { consoleFamily, type ConsoleFamily } from "../theme/coreTokens";
import type { ShelfConsole } from "../types";
import { familyCollectionId } from "./familyCollections";
import { consolePagePath } from "./consoleMedia";

function collectionIsLive(id: string): boolean {
  try {
    return collectionStore.userCollections.some((c) => c.id === id);
  } catch {
    return false;
  }
}

/** The route a family tile opens, or `null` when the family has nowhere to go. */
export function familyRoute(family: ConsoleFamily, consoles: readonly ShelfConsole[]): string | null {
  const collection = familyCollectionId(family);
  if (collection && collectionIsLive(collection)) return `/library/collection/${encodeURIComponent(collection)}`;
  const top = consoles.find((c) => consoleFamily(c.platform_slug) === family);
  return top ? consolePagePath(top.platform_slug) : null;
}

export function openFamily(family: ConsoleFamily, consoles: readonly ShelfConsole[]): void {
  const route = familyRoute(family, consoles);
  if (route) Navigation.Navigate(route);
}
