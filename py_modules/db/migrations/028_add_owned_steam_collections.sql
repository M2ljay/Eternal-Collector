-- =============================================================================
-- 028_add_owned_steam_collections.sql — which Steam collections the plugin made
-- =============================================================================
--
-- Backs the OwnedSteamCollection aggregate: one row per Steam collection the
-- plugin created on this device (or adopted once from the name-scoped era). A
-- collection name proves nothing about who made it, so this table is the only
-- ownership proof the frontend accepts before it renames, refills or deletes a
-- collection; a collection without a row is the user's and is never touched.
--
-- collection_id is Steam's own collection id. Each source (one platform, or one
-- synced RomM collection) owns at most one collection: source_key is the
-- casefolded source_name, unique per family, and the repository replaces the old
-- row when a source is recorded against a new collection id.
--
-- display_name is the name the plugin last gave the collection. yielded_to is
-- the name of the user's collection that already held the wanted name, NULL
-- when nothing was in the way.
--
-- A leaf table with no foreign keys: Steam collections are not ROM state.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 28.
-- -----------------------------------------------------------------------------
CREATE TABLE owned_steam_collections (
    collection_id TEXT NOT NULL PRIMARY KEY CHECK (collection_id <> ''),
    family        TEXT NOT NULL CHECK (family IN ('platform', 'romm')),
    source_name   TEXT NOT NULL CHECK (source_name <> ''),
    source_key    TEXT NOT NULL CHECK (source_key <> ''),
    display_name  TEXT NOT NULL CHECK (display_name <> ''),
    yielded_to    TEXT,
    UNIQUE (family, source_key)
) STRICT;
