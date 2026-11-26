-- =============================================================================
-- 027_add_rom_achievement_progress.sql — the achievement snapshot
-- =============================================================================
--
-- Backs the RomAchievementProgress aggregate: the user's RetroAchievements
-- progress per ROM as RomM last reported it (GET /api/users/me,
-- ra_progression.results[]), so the console page shows progress offline and
-- straight after Steam starts. One row per ROM the user has progress in; a ROM
-- with a set but no progress has no row. The whole table is replaced from one
-- answer, keyed through roms.ra_id, so a row is never older than fetched_at.
--
-- earned_hardcore <= earned <= total is the shape RomM reports; the CHECKs keep a
-- malformed answer from being stored rather than shown. highest_award_kind is
-- RomM's string ('mastered', 'beaten-hardcore', ...), NULL when none was given.
--
-- Per-ROM state owned by the ROM: rom_id references roms ON DELETE CASCADE, like
-- every other per-ROM table.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 27.
-- -----------------------------------------------------------------------------
CREATE TABLE rom_achievement_progress (
    rom_id             INTEGER NOT NULL PRIMARY KEY REFERENCES roms(rom_id) ON DELETE CASCADE,
    earned             INTEGER NOT NULL CHECK (earned >= 0),
    earned_hardcore    INTEGER NOT NULL CHECK (earned_hardcore >= 0 AND earned_hardcore <= earned),
    total              INTEGER NOT NULL CHECK (total > 0 AND earned <= total),
    highest_award_kind TEXT,
    fetched_at         TEXT    NOT NULL               -- ISO-8601; when RomM's answer was read
) STRICT;
