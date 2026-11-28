-- =============================================================================
-- 031_allow_console_family_steam_collections.sql — the "console_family" collection family
-- =============================================================================
--
-- Lets owned_steam_collections record the plugin's five console-family
-- collections (PlayStation, Nintendo, Sega, Xbox, Retro; family
-- 'console_family', source_name the family's display name), beside the
-- per-platform, per-RomM-collection and installed ones. SQLite cannot alter a
-- CHECK constraint, so the table is rebuilt with the wider family list and every
-- row copied across unchanged. A leaf table with no foreign keys onto or from
-- it, so the rebuild touches nothing else.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 31.
-- -----------------------------------------------------------------------------
CREATE TABLE owned_steam_collections_031 (
    collection_id TEXT NOT NULL PRIMARY KEY CHECK (collection_id <> ''),
    family        TEXT NOT NULL CHECK (family IN ('platform', 'romm', 'installed', 'console_family')),
    source_name   TEXT NOT NULL CHECK (source_name <> ''),
    source_key    TEXT NOT NULL CHECK (source_key <> ''),
    display_name  TEXT NOT NULL CHECK (display_name <> ''),
    yielded_to    TEXT,
    UNIQUE (family, source_key)
) STRICT;

INSERT INTO owned_steam_collections_031
    (collection_id, family, source_name, source_key, display_name, yielded_to)
SELECT collection_id, family, source_name, source_key, display_name, yielded_to
FROM owned_steam_collections;

DROP TABLE owned_steam_collections;

ALTER TABLE owned_steam_collections_031 RENAME TO owned_steam_collections;
