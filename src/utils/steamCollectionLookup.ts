/**
 * Read-only lookup of the user's Steam collections by name, for navigation.
 *
 * Writes to Steam's collections stay in `utils/collections.ts`, behind the
 * ownership record; this module only reads `collectionStore`, so it can sit on
 * paths (the Home row) that must not pull in the sync machinery.
 */

/**
 * The id of a Steam collection with this name, matched without regard to case as
 * Steam folds collection names by case (#1569); any owner. `null` when there is
 * none, or Steam's store is not there.
 */
export function collectionIdNamed(name: string): string | null {
  const target = name.toLowerCase();
  try {
    return collectionStore.userCollections.find((c) => c.displayName.toLowerCase() === target)?.id ?? null;
  } catch {
    return null;
  }
}
