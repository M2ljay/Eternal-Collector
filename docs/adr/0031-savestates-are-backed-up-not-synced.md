# Savestates are backed up to RomM, never synced — upload-only, opt-in, after the save sync

## Status

Accepted. Phase 1: RetroArch savestates only. Restoring a backed-up savestate (a game-page action behind a warning and
the `.romm-backup` quarantine) and standalone emulators are later phases and are not decided here beyond what this
record rules out.

## Context

The plugin syncs saves (SRAM, memory cards) and nothing else. Savestates were left out on purpose, and the reasons still
hold: a libretro savestate is the core's serialized memory, so another core — often another build of the same core —
refuses it or loads garbage; RomM's own documentation and Grout say as much. ADR-0028 named the gap from the other side:
when an adoption replaces a savestate, that savestate _"is synced nowhere at all"_.

The hazard that decides the shape is not the savestate that will not load. A RetroArch savestate contains cartridge
SRAM. Loading an older one puts the older SRAM back, the core writes it to `.srm` on exit, and the save sync then
uploads that regression as a legitimate local change — no conflict, because from the save matrix's view nothing
conflicts. EmuDeck's AutoSave option makes RetroArch load `.state.auto` at launch without asking, so an automatically
placed auto-state is exactly how that happens. RomM 5.5 snapshots pair a savestate with the save it was taken with,
which is the real fix, but 5.5 is a beta and the plugin's floor is 4.9.

What RomM offers below 5.5 is a plain per-ROM file store: `POST /api/states?rom_id=&emulator=` with a `stateFile` part
and an optional `screenshotFile` part, upserting by `(user, rom, file name)`. 4.9 has no hash, slot, device or 409 on a
savestate; 5.4 adds a content hash and a `core` column; 5.5 adds `core`, `core_version`, `emulator_version` and
`device_id` as POST parameters. FastAPI ignores query parameters a route does not declare, so a client can send the 5.5
parameters to any 5.x server.

## Decision

**Upload-only backup.** After a game exits, and after the post-exit save sync has finished, the plugin uploads each
RetroArch savestate of that game whose content hash differs from the one this device last recorded for its slot. It
never downloads a savestate, never writes, renames or removes a local one, and never routes a savestate decision through
the gavel core or the save matrix. The decision is one pure function, `domain/savestate_backup.py`.

**Opt-in, under save sync.** "Back up savestates to RomM" is off by default and sits under the save-sync master toggle;
both must be on. "Which savestates" is the auto-state alone (default) or every slot `0`–`9`.

**Only savestates written after the backup was turned on.** Turning the backup on stamps the moment
(`savestate_backup_enabled_at` in `settings.json`). A savestate whose file was last written before that moment is
recorded as a baseline instead of uploaded, and uploads the next time the game overwrites it. Turning the backup off
drops the stamp, so turning it on again opens a fresh window. A missing stamp uploads nothing. There is no "back up
everything now" action in phase 1: it would be a large upload the user has not sized, which is the thing this rule
exists to prevent.

**One server row per device and slot.** The backup is filed as `<booted stem> [<device short-id>].<slot suffix>` — the
first eight letters or digits of the server-issued device id — so a device replaces only its own previous backup of a
slot, never another device's, and never writes a name a RomM 5.5 channel holds. No history is kept: the server copy is
the latest one. The screenshot RetroArch writes beside the savestate (`<savestate>.png`) is uploaded as `<server
name>.png`, which is the name RomM pairs it by.

**RomM's emulator ids.** `emulator` is RomM's id for the core — the table RomM's RetroArch WebDAV sync uses
(`emulator_names.py`, copied verbatim into `domain/savestate_names.py`), so the web UI and other clients file the
savestate with the same core. `core` (the libretro id) and `core_version` (`display_version` from the core's `.info`
file) are kept locally for every upload, because servers before 5.5 do not store them and a later restore has to warn on
a mismatch.

**Exact-name discovery.** The stem is the file RetroArch booted — the disc the per-game disc pick resolves to, not the
ROM's name — and the folder follows the live savestate layout. Only the names for that stem's slots are probed, never a
glob of the shared states folder.

**Its own aggregate and lock.** The records live in the reserved `RomSavestateSyncState` / `rom_savestate_sync_states`
(migration `026`), one row per slot, mutated only through `record_upload` and `adopt_baseline`. Every read-mutate-write
holds `SavestateService.rom_lock(rom_id)`, a lock of its own: sharing the save sync's `rom_lock` would couple two flows
that share no state.

**After, never before.** The backup runs from `SessionLifecycleService.finalize` once the save sync has returned. It is
skipped when the save sync found the server offline or a RetroDECK migration is pending, and a failure is logged and
counted as nothing backed up — it never turns a finished session into an error. The after-exit toast gains a clause
("Saves uploaded to RomM · 2 savestates backed up").

## Consequences

- RomM's web player opens a game with any savestate on the **States** tab with no save selected, and "Save & Quit" from
  there creates a slot-less save no named-slot client sees (ADR-0026). Backing up a game's savestates makes that trap
  fire for that game. The user guide says so.
- A savestate the server refuses is left unrecorded and retried on the next exit. An unreachable server stops the run at
  the first failure instead of waiting out a timeout per slot.
- Savestates larger than RomM's default upload ceiling (512 MiB) are skipped with a log line.
- Nothing about the save sync changes: not its timing, not its inputs, not its decisions.
- `RetroArchCoreInfoAdapter` now also reads EmuDeck for Windows' `info` folder, which the core version needs. The same
  lookup answers the `corename` the save sync uses for per-core save folders, so on Windows a RetroArch configured to
  sort saves by core now resolves that folder instead of falling back to the parent directory.

## Alternatives considered

**Automatic two-way sync of the auto-state.** Rejected for now: it is the SRAM rollback above, and RomM below 5.5 has no
field to prove a savestate was taken with the save the device holds. It belongs with RomM 5.5 snapshots, which change
the save transport and reopen the gavel contract — a separate decision.

**RetroArch's own Cloud Sync against RomM's WebDAV endpoint.** Not built on: it also syncs `saves/`, a second writer
next to the plugin's save sync, and it is newest-wins per slot with the same rollback hazard. Worth knowing as a
stopgap, not as a foundation.

**Upload every existing savestate on first enable, as Ludo first did.** Rejected: one of Ludo's devices re-uploaded 44
savestates untouched since months earlier the first time it connected, and Ludo now seeds a baseline. Seeding by the
enable moment does the same without a separate first-run pass.

**A timestamp in the server name to keep history.** Rejected for phase 1: retention would need a server-side prune of
copies that may exist nowhere else, which the register's backup-or-confirm rule makes its own decision.

## See also

- [ADR-0026](0026-legacy-bucket-stays-read-only.md) — the slot-less save the web player's States tab creates
- [ADR-0028](0028-adopted-install-is-an-install.md) — the savestate backup leg of an adoption's Overwrite
- [save-file-sync-architecture.md](../architecture/save-file-sync-architecture.md#savestate-backup) — how the backup
  runs
- [CONTEXT.md](../../CONTEXT.md) — **Savestate**, **Savestate backup**
