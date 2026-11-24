# Game Mods (Windows / EmuDeck)

The game page's **Mods** panel tells the user where a game's mods go for the emulator it launches with, lists what is
there, and installs, removes and switches on what the emulator needs. User-facing behaviour is in
[the Windows guide](../user-guide/windows.md#mods); this page is how it is built and the rules it holds.

## Layers

| Layer   | Module                                            | Owns                                                                                                   |
| ------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Domain  | `domain/game_mods.py`                             | Emulator identification, portable-layout rules, mod targets, ini switch read/edit, install planning    |
| Domain  | `domain/disc_ids.py`                              | Game identifiers, now including the 3DS title ID (NCSD → NCCH program ID, NCCH, CIA → TMD title ID)    |
| Adapter | `adapters/game_mod_files.py` (`GameModStore`)     | Listing, Downloads, zip/folder reading, the install itself, moves to backup, the ini rewrite, Explorer |
| Adapter | `adapters/disc_code_reader.py` (`DiscCodeReader`) | Reading the identifier out of the game file (shared with standalone save sync)                         |
| Adapter | `adapters/game_process_windows.py`                | `running_executable_names()` for the "emulator is running" refusal                                     |
| Service | `services/game_mods.py` (`GameModsService`)       | The seven callables; resolution on every call; the write lock                                          |
| UI      | `src/components/ModsButton.tsx`, `ModsModal.tsx`  | The button (native look + installed only) and the panel                                                |

`GameModStore` is wired only on Windows (`bootstrap/adapters.py`); with no store, or with a launcher backend other than
EmuDeck, every callable answers `{success: false, reason: "unsupported"}`.

## Resolution — exact or nothing

Every callable resolves afresh; the frontend names a target by **id**, a source by its **Downloads entry name**, and an
installed entry by the **name the backend listed**. No path ever comes from the frontend.

1. The emulator is the executable in the command the game launches with: `ActiveCoreReader.active_emulator_for_rom`
   rendered by the active backend's `LaunchCommandRenderer.resolve_invocation` — the same bake seam the Steam shortcut
   is written from. Its file name identifies Dolphin, PPSSPP, PCSX2, Azahar/Citra/Lime3DS or RetroArch.
2. The emulator's data folder is read from its own portable markers beside the executable (`portable.txt`,
   `installed.txt`, `portable.ini`, a `user` folder) and, where the emulator lets the user move a mod root, from its
   own settings file (Dolphin `[General] LoadPath`, PCSX2 `[Folders] Textures`). A layout these rules do not cover
   answers "no known mod folder" with the reason; there is no fallback to a typical path.
3. The per-game folder is named by the identifier read from the game file and validated against the emulator's own
   format (ID6, `ULUS10041`, `SLUS-20946`, 16 upper-case hex digits). An unreadable image gives no target.

RetroArch's soft patch is the exception that needs no identifier: `<content basename>.ips|.bps|.ups` beside the ROM
(atlas `build_soft_patch_candidates`). It is offered only for a single, non-archive, non-disc file, and not when the
core's `.info` says `needs_fullpath = "true"` (RetroArch never patches such content). The vendored atlas records
which patch formats a RetroArch build attempts only for RetroDECK, so the target carries an "unverified" note.

PCSX2 `.pnach` patches and cheats are named `<SERIAL>_<CRC>.pnach` (atlas `mods.json`, `PCSX2`), and the ELF CRC is not
read, so they are listed as omitted rather than offered.

## Install

- **Plan (pure).** `plan_install` refuses the whole source if any entry is a link, is not a plain relative Windows
  name (`mod_entry_name`: no absolute path, drive, colon, `..`, reserved device name, forbidden character, trailing dot
  or space), repeats case-insensitively, or is both a file and a folder. A source whose every entry sits under one top
  folder named like the game folder has that folder dropped (no `GALE01\GALE01`); PCSX2's `replacements` prefix is
  added where missing. A soft patch needs exactly one patch file, renamed to the ROM's stem.
- **Check.** The adapter reports each destination as file / folder / other / missing; a file is replaced (backed up),
  anything else in the way blocks the install.
- **Fingerprint.** The preview returns a digest of the source's stamp (size and mtime, or a folder's totals), every
  planned write and every replacement. `install_mod` plans again and refuses with `changed` when the digest differs, so
  what is installed is what was shown.
- **Execute.** The adapter moves every replaced file to the backup folder, then writes each file through a part file and
  `os.replace`, joining every destination with `safe_join` (a second confinement, independent of the plan) and refusing
  to write over a file that was not planned as replaced. It reads at most the declared size of each entry and fails on a
  short or long one. A failure part-way reports how many files were written and where the backups are
  (`reason: "partial"`); nothing is rolled back silently.

## Backup-or-confirm

Nothing in this feature deletes user data. Replaced files, removed entries and the ini before an edit are moved or
copied to `<emulator data folder>\romm-mod-backups\<yyyymmdd-hhmmss>-<id>\<target>\`, on the same volume as the
mods so a texture pack's move is a rename. Removal additionally goes through a confirmation naming the path. The
data folder is the emulator's own, not a mod folder, so no emulator reads the backups as content.

## Setting switch

`read_setting` / `enable_setting` handle one key of a plain ini. A file with a section or key twice, or a line that is
not blank, comment, section or `key = value`, is "unknown" and not editable. The edit changes the value on that one line
(or adds the key at the end of its section, or the section at the end of the file), keeps the file's line endings and
BOM, and is written only if the file still holds what was read. It is refused while the emulator's executable name is
in the process list; when the process list cannot be read the edit goes ahead and the confirmation dialog has already
asked the user to close the emulator.

Defaults when a key is absent come from the emulators' sources: Dolphin `HiresTextures` off, PPSSPP `ReplaceTextures`
on, PCSX2 `LoadTextureReplacements` off.

## Gating

`install_mod`, `remove_mod` and `enable_mod_setting` carry `@migration_blocked` and `@prune_active_blocked` (a soft
patch sits beside a ROM the removed-game cleanup may be claiming) and share one `asyncio.Lock`. The reads
(`get_game_mods`, `list_mod_sources`, `preview_mod_install`, `open_mod_folder`) are not gated.
