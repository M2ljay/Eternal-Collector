-- =============================================================================
-- 029_add_ra_game_journals.sql — the user's own achievement goals and notes
-- =============================================================================
--
-- Backs the RaGameJournal aggregate: per RetroAchievements game, the user's
-- free-text notes and the achievements they pinned as goals. Two tables, one
-- aggregate: ra_game_journals holds the scalars, ra_achievement_goals the goals.
--
-- Keyed by the RetroAchievements game id (roms.ra_id), with no foreign key onto
-- roms: every version of a game shares one achievement set, and this is writing
-- the user did that exists nowhere else, so a purge of a ROM row must not
-- cascade it away. A journal row with no notes and no goals is deleted by the
-- repository rather than kept empty.
--
-- ra_game_journals is a cascade parent (its goals reference it ON DELETE
-- CASCADE), so the repository UPSERTs it and never uses INSERT OR REPLACE,
-- which would delete-then-insert the parent and wipe its goals.
--
-- Goals keep the achievement's title, description and points as they were when
-- pinned, so the cross-game list reads offline. unlocked_at is NULL until an
-- unlock is seen; unlocked_hardcore is 0/1.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 29.
-- -----------------------------------------------------------------------------
CREATE TABLE ra_game_journals (
    ra_game_id       INTEGER NOT NULL PRIMARY KEY CHECK (ra_game_id > 0),
    game_title       TEXT    NOT NULL CHECK (game_title <> ''),
    notes            TEXT    NOT NULL DEFAULT '' CHECK (length(notes) <= 4000),
    notes_updated_at TEXT                                  -- ISO-8601; NULL when there are no notes
) STRICT;

CREATE TABLE ra_achievement_goals (
    ra_game_id        INTEGER NOT NULL REFERENCES ra_game_journals(ra_game_id) ON DELETE CASCADE,
    achievement_id    INTEGER NOT NULL CHECK (achievement_id > 0),
    title             TEXT    NOT NULL CHECK (title <> ''),
    description       TEXT    NOT NULL DEFAULT '',
    points            INTEGER NOT NULL CHECK (points >= 0),
    pinned_at         TEXT    NOT NULL CHECK (pinned_at <> ''),
    unlocked_at       TEXT,                                -- ISO-8601 UTC; NULL until unlocked
    unlocked_hardcore INTEGER NOT NULL DEFAULT 0 CHECK (unlocked_hardcore IN (0, 1)),
    PRIMARY KEY (ra_game_id, achievement_id)
) STRICT;
