-- =============================================================================
-- 026_add_rom_savestate_sync_states.sql — savestate backup records
-- ADR-0031 (savestates are backed up to RomM, upload-only)
-- =============================================================================
--
-- Backs the RomSavestateSyncState aggregate, the name database-design.md reserved
-- for savestate work. One row per (rom_id, slot); the aggregate is every row of
-- one rom_id. slot is the backup vocabulary: 'auto' for RetroArch's .state.auto,
-- '0'..'9' for .state / .state1..9 (the keys RomM 5.5 snapshot banks use).
--
-- content_hash is the content this device last accounted for in the slot, by
-- uploading it or by recording it as a baseline; it is what the next backup
-- compares against, so it is NOT NULL and non-empty. The uploaded_* / server_*
-- columns describe the latest upload and are NULL for a slot that was only ever
-- baselined. core / core_version are kept here because servers before RomM 5.5
-- do not store them.
--
-- Per-ROM state owned by the ROM: rom_id references roms ON DELETE CASCADE, like
-- every other per-ROM table. A leaf table, so the repository replaces a ROM's rows
-- with DELETE + INSERT inside one unit of work.
--
-- Transaction-safe DDL only — the runner (adapters/sqlite_migrations.py) wraps
-- BEGIN/COMMIT and stamps PRAGMA user_version = 26.
-- -----------------------------------------------------------------------------
CREATE TABLE rom_savestate_sync_states (
    rom_id           INTEGER NOT NULL REFERENCES roms(rom_id) ON DELETE CASCADE,
    slot             TEXT    NOT NULL CHECK (slot IN ('auto', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')),
    local_name       TEXT    NOT NULL,              -- RetroArch file name the record was taken from
    content_hash     TEXT    NOT NULL CHECK (content_hash <> ''),  -- MD5 of the content last accounted for
    observed_at      TEXT    NOT NULL,              -- ISO-8601; when that content was accounted for
    uploaded_hash    TEXT,                          -- MD5 of the latest upload; NULL = never uploaded
    uploaded_at      TEXT,                          -- ISO-8601 of the latest upload
    server_state_id  INTEGER,                       -- RomM state id of the latest upload
    server_file_name TEXT,                          -- file name RomM stored the latest upload under
    emulator         TEXT,                          -- RomM emulator id the upload was filed under
    core             TEXT,                          -- libretro core id (snes9x) the savestate was written by
    core_version     TEXT,                          -- that core's display_version, when known
    PRIMARY KEY (rom_id, slot)
) STRICT;
