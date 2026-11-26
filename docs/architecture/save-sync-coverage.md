# Save Sync Coverage

Why some saves sync and others don't. The mechanics live in
[Save File Sync Architecture](save-file-sync-architecture.md); this page explains the **coverage envelope** — which save
files the per-game model can and cannot reach — and the strategy for the gaps. The user-facing result is the
[Save sync support matrix](../user-guide/save-sync-support-matrix.md).

## The per-game discovery model

Save discovery is **exact-name probing**, not a directory scan. For an installed ROM whose file stem is `rom_name`, the
sync looks for exactly `<saves_dir>/<rom_name><ext>` for each extension in a fixed list, and uploads the ones that
exist. There is no glob, no `listdir`, no pattern match.

This is a deliberate bijection: **one ROM → one set of `<rom_name>.<ext>` files in the save folder.** It maps perfectly
onto libretro's own SRAM convention, where the save file mirrors the ROM name. Everything that doesn't fit that shape is
invisible to the sync.

Two hard properties follow, and they define the entire coverage envelope:

1. **The filename must be the ROM stem.** A file named anything else — a fixed card name (`pcsx-card2.mcd`,
   `vmu_save_A1.bin`), or a name with a slot/unit infix (`game.1.mcr`) — is never probed.
2. **The file must live in the save folder.** A save in RetroArch's _system_ directory (Flycast VMUs), in a per-emulator
   subdirectory (`mame/nvram/`), or next to the ROM (`savefiles_in_content_dir`) is never seen.

The explicit removed-game cleanup starts with this exact-path projection and adds path-safe filenames already persisted
for that ROM in `RomSaveSyncState.files`. This is an identity-backed exception to the filename rule, not directory
discovery: cleanup never scans for new names. Class (c), unknown fixed/shared names, unresolved uninstalled layouts, and
save states are left physically untouched and recorded as warnings where applicable. If two installed local rows project
the same canonical current-save path, that path is shared ownership; purging one owner may copy it into recovery but
cannot remove it while another owner remains.

The extension list is a small static map keyed by the **RetroDECK system** (the normalized value from `resolve_system` /
`platform_map`, not the raw RomM platform slug — keying by system keeps the lookup aligned with the save directory,
cores, and gamelists, which are all system-keyed): a default of `.srm` / `.rtc` / `.sav`, plus per-system overrides
(`nds` → `.dsv`, `segacd` → `.brm`, `saturn` → `.bkr`/`.bcr`/`.smpc`, `ngp`/`ngpc` → `.flash`/`.ngf`, `pokemini` →
`.eep`, and `amiga`/`amigacd32` → `.nvr`).

## How RomM stores saves

RomM treats a save as a file blob keyed by `(rom_id, slot)`, with an `emulator` tag (which becomes a storage
subdirectory) and an MD5 `content_hash`. It stores the bytes the client sends and leaves their meaning to the client —
there is no `save_type` or memory-card concept, and each save belongs to a single ROM. This format-agnostic design keeps
the server simple and works for any client; RomM's own in-browser player (EmulatorJS) uses the same path, uploading one
save blob per `(game, core)`.

Because both the server and our discovery are organised **per game**, two things follow. Supporting a new _per-game_
save format is a client-side change — the server already accepts the file as-is. And a _shared_ card has no per-game
identity to map onto a `(rom_id, slot)` record, so any shared-card handling is a client-side modelling decision (see
below), not something the server provides or prevents.

## The three coverage classes

Every core's save behavior falls into one of these (plus "no save"):

| Class   | Shape                                                                                  | What it needs                                                                                                                 |
| ------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **(a)** | Per-game, single-token `<rom>.<ext>`, save folder                                      | Just add `<ext>` to the override map. No architecture change.                                                                 |
| **(b)** | Per-game, but a **slot/unit infix** (`<rom>.1.mcr`, `<rom>.A1.bin`)                    | Infix-aware discovery **and** download-target derivation (the current code drops the infix), plus multi-file-per-ROM support. |
| **(c)** | **Shared** card (one file, many games), **fixed** name, or **outside** the save folder | Breaks the per-game model. Not solvable by an extension — see strategy below.                                                 |

Class (a) is pure upside. Class (b) is bounded engineering that stays inside the per-game model. Class (c) is the
genuinely hard one.

## Strategy for class (c)

The emulation ecosystem has already converged on the answer, and it aligns with this project's "no assumptions, the user
decides on ambiguity" stance:

- **No tool merges binary card images.** Block-level merge of a shared `.mcr`/`.ps2`/`.raw` is a confirmed dead end. The
  only options are _isolate_ (per-game) or _pick-one_ (whole-file).
- **Prefer per-game mode.** Modern emulators default to it (DuckStation per-game cards; Beetle PSX / PCSX ReARMed slot
  0; PCSX2 Folder Memory Cards; Dolphin GCI folders). Where the launch core supports per-game cards, that path collapses
  class (c) into class (a)/(b) and maps cleanly onto per-game sync.
- **For an unavoidable shared card, treat it as one device-global blob:** whole-file, last-writer-wins, with conflict
  **detection that warns instead of clobbering** (the Ludusavi model), and rely on the existing version history as the
  recovery net. Never present it as per-game; never merge.
- **Sync SRAM, not savestates.** Savestates are core- and version-coupled and not portable across devices; in-game
  saves are. RetroArch savestates are **backed up** to RomM after a game exits, upload-only and opt-in, and nothing
  restores one automatically
  ([ADR-0031](../adr/0031-savestates-are-backed-up-not-synced.md),
  [Savestate backup](save-file-sync-architecture.md#savestate-backup)).
- **The per-game card format is emulator-specific.** A per-game card written by the RetroArch PCSX2 core is not
  byte-compatible with standalone PCSX2. The sync key/format must match the core the user actually launches with — which
  is exactly what RomM's `emulator` subdirectory captures.

## Roadmap mapping

- **(a)** — extension-map additions, candidate for incremental delivery; research/verification tracked in
  [#237](https://github.com/danielcopper/decky-romm-sync/issues/237).
- **(b)** — infix-aware per-game discovery (PS1 multi-card, Flycast per-game VMU, 3DO NVRAM); research in
  [#237](https://github.com/danielcopper/decky-romm-sync/issues/237), implementation under the save-format epic
  [#255](https://github.com/danielcopper/decky-romm-sync/issues/255).
- **(c)** — shared/system-dir handling under [#255](https://github.com/danielcopper/decky-romm-sync/issues/255) (save
  formats), [#151](https://github.com/danielcopper/decky-romm-sync/issues/151) (Dreamcast VMU), and
  [#129](https://github.com/danielcopper/decky-romm-sync/issues/129) (standalone emulators) — all v2.0.

## Standalone emulators (EmuDeck for Windows)

On the `windows` branch, a ROM whose launch emulator (the per-game pick, else the per-platform pick, else EmuDeck's
default — the same `ActiveCoreResolver` answer the shortcut is baked from) is a supported standalone emulator syncs that
emulator's saves instead of RetroArch's. Each was chosen because its save can be tied to one game **exactly**. For these
three the ROM file name alone is enough; Dolphin, PPSSPP and PCSX2, which need the disc's own identifier, follow
[below](#disc-code-emulators-dolphin-ppsspp-pcsx2):

| Emulator    | Systems  | Save set for a ROM whose file stem is `<stem>`                       | RomM `emulator` tag |
| ----------- | -------- | -------------------------------------------------------------------- | ------------------- |
| melonDS     | `nds`    | `<stem>.sav`                                                         | `melonds`           |
| DuckStation | `psx`    | `<stem>_1.mcd`, `<stem>_2.mcd` (per-game memory cards)               | `duckstation`       |
| Vita3K      | `psvita` | the `<TITLE_ID>` save folder, bundled as one `<TITLE_ID>.vita3k.zip` | `vita3k`            |

The model is unchanged — still exact-name probing, still one per-file decision from the gavel core per name — only
**where** the names live and **which** names they are come from the emulator. The seam is the ROM's _save set_:
`RomInfoService.get_rom_save_info` adds a `save_set` (`domain/standalone_saves.py`) and points `saves_dir` at the
emulator's folder; discovery probes only the set's names, and every flow that maps a server save back to a local file
goes through one helper, `services/saves/_helpers.save_target`.

**Gating.** A save set is used only when all of these hold, so RetroDECK and Linux EmuDeck behave exactly as before:

- the active launcher backend answers a folder from `LauncherPaths.standalone_saves_path(emulator)` — only the EmuDeck
  for Windows backend does, as `$savesPath\<melonds|duckstation|Vita3K>\saves` from EmuDeck's `settings.ps1` (the
  folders EmuDeck links to each emulator's own save directory; they are read through the link), or
  `$savesPath\<dolphin|ppsspp|pcsx2>` for the disc-code emulators. Every other backend answers `""`, and the emulator
  is then not even resolved;
- the launch emulator is a **standalone** one, recognised by the executable in its baked command (`melonDS.exe`,
  `duckstation-*.exe`, `Vita3K.exe`, `Dolphin.exe`, `PPSSPP*.exe`, `pcsx2*.exe`). A psx game launched with a
  RetroArch core keeps the RetroArch behaviour;
- the ROM yields a save set. For Vita3K that means the launch file is `<TITLE_ID>.psvita` (what the Vita install step
  writes), so the stem is a valid title ID; for Dolphin, PPSSPP and PCSX2 that the installed image is read exactly.

**Emulators never cross.** Uploads carry the emulator's own tag (`RomInfoService.upload_emulator_tag`, the single place
`MatrixExecutor.do_upload_save` takes it from). A standalone save set claims a server save only when its tag is its own
**and** its name is one of the set's exact names: RomM's `[YYYY-MM-DD_HH-MM-SS]` slot tag is stripped from `file_name`
(or `file_name_no_tags` + `file_extension` is used), and a save this device uploaded itself also stays mapped through its
tracked id. Conversely the RetroArch mapping never claims a save tagged with any standalone emulator's id, so a
standalone save can never be downloaded into the RetroArch folder of a device that launches the same game with a core.
Upstream never writes those tags, so on RetroDECK this changes nothing.

**DuckStation's names.** DuckStation names a per-game card after the game's title in its own game database, which is
usually — not always — the ROM stem (`R4 - Ridge Racer Type 4 (USA)_1.mcd` matches a ROM named
`R4 - Ridge Racer Type 4 (USA).chd`; a card named after a different title does not). Only the exact `<stem>_1.mcd` /
`<stem>_2.mcd` are synced; a card under any other name is left alone and does not sync. There is no fuzzy matching by
design: a wrong match would upload or overwrite another game's card.

**Folder saves travel as one file.** A Vita3K save is a folder (`SlotParam_0.bin`, `system.bin`, `game_dir/…`). Each
time saves are discovered, `SaveFileStore.pack_save_folder` writes it as `<TITLE_ID>.vita3k.zip` beside the folder: the
folder's files (and empty directories) as relative `/` paths, sorted, stored uncompressed, with one fixed timestamp and
fixed attributes — so an unchanged folder always gives byte-identical bytes, and the file is only rewritten (and then
stamped with the folder's newest mtime) when its content changes. That keeps both the RomM per-entry `content_hash` and
the size/mtime baselines stable, so an untouched save never looks changed. The zip is a derived artifact; the folder is
the save. On download the archive is unpacked into a staging folder first (`.<TITLE_ID>.romm-unpack`): every entry name
is server-supplied, so absolute paths, drive letters, backslashes, `..` and duplicates are refused and each path is
confined with `safe_join` before anything is written. Only after a clean unpack is the live folder moved into
`.romm-backup/<TITLE_ID>_<ts>` (the same quarantine funnel and retention as file saves —
`MatrixExecutor.quarantine_local_file` backs up the whole folder for a bundle name) and the staged folder moved into place. A corrupt
or unsafe archive fails that one file's sync with the existing save untouched.

**Not covered.** Savestates: a standalone emulator's savestates are neither synced nor backed up (only RetroArch's
are backed up, see [Savestate backup](save-file-sync-architecture.md#savestate-backup)). The removed-game cleanup still
projects only the RetroArch paths, so it never touches a standalone emulator's folder (those saves are left in place,
not backed up into the recovery bundle). The setup wizard's
legacy (`slot:null`) migration skips bundles — a bundle is only ever uploaded into a named slot. A conflict shows the
bundle as one file.

### Disc-code emulators: Dolphin, PPSSPP, PCSX2

Three more emulators file a game's save under an identifier the **disc** carries, not under the ROM's name. For these the
save set is derived from that identifier, read out of the installed image (`DiscCodeReader`, implemented by
`adapters/disc_code_reader.py`; parsing in `domain/disc_ids.py`). Gating, emulator identification (`Dolphin.exe`,
`PPSSPP*.exe`, `pcsx2*.exe`) and the RetroArch/Linux fallback are exactly as above. Their save sets are rooted at
EmuDeck's per-emulator saves folder itself (`$savesPath\<dolphin|ppsspp|pcsx2>`), whose linked sub-folders are what the
emulators read; the bundle zip and `.romm-backup` sit in that root, which none of them reads.

| Emulator | Systems | Identifier read from the image                                    | Save set                                                                                    | Bundle                  | Tag       |
| -------- | ------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------- | --------- |
| Dolphin  | `gc`    | ID6 from the disc header (`GALE01`)                               | every `.gci` in `GC\<region>\Card A` and `Card B` whose header carries the 4-char game code | `<ID6>.dolphin-gc.zip`  | `dolphin` |
| Dolphin  | `wii`   | ID6 from the disc header (`SMOXE8`)                               | the `Wii\title\00010000\<ID4 as hex>\data` folder                                           | `<ID4>.dolphin-wii.zip` | `dolphin` |
| PPSSPP   | `psp`   | `PSP_GAME/PARAM.SFO` `DISC_ID`, else `UMD_DATA.BIN` (`ULUS10234`) | every `saves\<GAME ID>*` save-data folder                                                   | `<GAME ID>.ppsspp.zip`  | `ppsspp`  |
| PCSX2    | `ps2`   | `SYSTEM.CNF` `BOOT2` (`cdrom0:\SLUS_200.62;1` → `SLUS-20062`)     | every `saves\<folder card>\B?<SERIAL>*` folder                                              | `<SERIAL>.pcsx2.zip`    | `pcsx2`   |

**Image formats read.** Only the bytes that identify the game are read — never the whole image:

- GameCube/Wii: `.rvz` / `.wia` (the WIA file header stores the disc's first 0x80 bytes uncompressed — Dolphin
  `docs/WiaAndRvz.md`; both header SHA-1s are verified and the disc-type field must agree with the header's magic word),
  and plain `.iso` / `.gcm` (header at offset 0). The console comes from the header's magic word (Wii `0x5D1C9EA3` at
  0x18, GameCube `0xC2339F3D` at 0x1C), never from the ID's first letter.
- PSP: plain `.iso`, CSO v1 `.cso` (block index, raw-deflate blocks; CSO v2 refused) and `.chd`. An ISO 9660 walk
  reaches `PARAM.SFO` / `UMD_DATA.BIN`.
- PS2: plain `.iso` and `.chd` — a DVD image (2048-byte units) or a CD image (the first data track of
  `MODE1`/`MODE1_RAW`/`MODE2`/`MODE2_FORM1`/`MODE2_RAW`, a stored pregap honoured, raw sectors checked for their sync
  header). An ISO 9660 walk reaches `SYSTEM.CNF`.
- CHD (`domain/chd_format.py` + `adapters/disc_images.py`, following libchdr): v5 only; both the raw map of an
  uncompressed CHD and the Huffman/RLE-coded map `chdman` writes by default (map CRC verified); hunk codecs `zlib`,
  `lzma` (raw LZMA, properties derived from the hunk size as MAME does), `huff`, `zstd`, and the CD codecs `cdzl`,
  `cdlz`, `cdzs` (sector data and subcode decoded separately, stripped sync/ECC regenerated); uncompressed and
  self-referencing hunks; every hunk's CRC-16 verified. `zstd`/`cdzs` go through the vendored `backports_zstd`, whose
  compiled module loads only on the one CPython ABI/platform it was built for — elsewhere (including Windows) those hunks
  are unreadable and the game does not sync. FLAC codecs, parent (delta) CHDs and CHD v1–v4 are refused.

Anything else (`.wbfs`, `.gcz`, `.ciso`, `.pbp`, `.zso`, `.dax`, `.cue`/`.bin`, …), or an image that does not decode
exactly, yields no identifier, and the game keeps the pre-existing RetroArch handling — no standalone save syncs for it,
and the game reports a [save-sync blocker](#save-sync-blockers) naming the cause.
Results are cached per file (path, size, mtime), in memory only.

**Dolphin GameCube region and cards.** The region folder (`USA`/`EUR`/`JAP`) follows Dolphin's `CountryCodeToRegion`
for the country byte (`ID6[3]`); an `E` disc with revision ≥ 0x30 is NTSC-J, as in Dolphin. Dolphin itself decides a
GameCube disc's region from `bi2.bin` (offset 0x458), which a compressed image's header does not carry, so the ambiguous
codes `X`/`Y`/`Z` are left unidentified. Dolphin's config is not read: both `Card A` and `Card B` GCI folders are
included whichever device each slot uses (a GCI file with this game's code is this game's save either way), and a
custom `GCIFolderAPath` is not followed. Only `.gci` files whose own first four bytes are the game code are members —
`SRAM.raw`, `MemoryCard*.raw` and other games' GCI files are never selected, uploaded or replaced, and a downloaded
bundle carrying any of them is refused.

**PCSX2 folder card.** PCSX2 must use a **folder** memory card in slot 1. The card is read from
`<pcsx2 folder>\inis\PCSX2.ini` beside the executable in the baked command (PCSX2's portable layout, which EmuDeck
installs): `[MemoryCards] Slot1_Enable = true`, `Slot1_Filename` a plain name, `[Folders] MemoryCards` the default
`memcards` (linked by EmuDeck to `$savesPath\pcsx2\saves`), and that name must be a folder holding
`_pcsx2_superblock`. If any of that fails — ini unreadable, slot 1 off, a file card such as `Mcd001.ps2`, a relocated
memcards folder — the game does not sync. Per-game memory-card overrides in `gamesettings\*.ini` are not read. The
card's `_pcsx2_superblock` / `_pcsx2_index`, the file cards and other games' folders are never touched; PCSX2 rebuilds
its folder-card index from the save folders on load.

### Save-sync blockers

Every path above on which a ROM launches with a standalone emulator but its exact save set cannot be derived used to
fall back to RetroArch's layout and upload nothing, silently. `RomInfoService.get_rom_save_info` now returns a
`save_sync_blocker` (`domain/save_sync_blockers.py`) for each of them, with a stable `reason` and the sentence the UI
shows:

| `reason`                    | When                                                                                                                   |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `unknown_emulator`          | The baked command's executable is no standalone emulator this plugin knows                                             |
| `emulator_folder_unknown`   | The backend locates no save folder for that emulator                                                                   |
| `vita_no_title_id`          | Vita3K, and the launch file's stem is not a title ID                                                                   |
| `disc_unreadable`           | The image could not be opened                                                                                          |
| `disc_format_unsupported`   | No reader for the image's extension (`.pbp`, `.wbfs`, …)                                                               |
| `disc_image_unsupported`    | The image did not decode (an unsupported CHD version or codec, a parent CHD, a bad CRC); the reader's detail is quoted |
| `disc_id_missing`           | The image decoded but carries no identifier (or a Wii title folder cannot be formed)                                   |
| `disc_region_unknown`       | A GameCube disc whose region Dolphin decides from `bi2.bin` (`X`/`Y`/`Z`, unknown codes)                               |
| `pcsx2_settings_unreadable` | `inis\PCSX2.ini` missing or unreadable                                                                                 |
| `pcsx2_slot_empty`          | Slot 1 disabled, or its file name is not one plain name                                                                |
| `pcsx2_cards_elsewhere`     | `[Folders] MemoryCards` is not the default `memcards`                                                                  |
| `pcsx2_file_card`           | Slot 1 holds a single-file card (`Mcd001.ps2`)                                                                         |
| `pcsx2_card_missing`        | The slot-1 name is neither a file nor a folder card with `_pcsx2_superblock`                                           |

The disc causes come from `DiscCodeReader.disc_code_problem`, which the adapter records beside its per-file cache. A
backend with no standalone save folder at all (RetroDECK, EmuDeck on Linux) is not a blocker: it is checked first so
those backends never pay for the emulator resolution, and their standalone emulators keep the RetroArch handling.

Where it shows: `get_save_status` carries `save_sync_blocked: {reason, message} | null` (additive, like
`savefiles_in_content_dir`) and, with no local files, the display `Not syncing`; the game page renders a _Saves not
syncing_ warning card above the play row; a sync that moved nothing carries `save_sync_blocked` too — the manual sync's
`message` becomes the sentence, and the post-exit result's `blocked_toast` is shown when no other sync toast fires. A
blocker is never a conflict and never gates a launch.

**Member bundles.** A Vita3K or Wii save is one folder — a _folder bundle_, packed and restored as above. The GameCube,
PPSSPP and PCSX2 sets are a game's share of directories other games use too — a _member bundle_ (`domain/save_bundles.py`):
the layout names each source directory, the zip prefix its members are filed under (`Card A/…`), and the rule a member
must meet (a folder name pattern, or a GCI header). Packing (`SaveFileStore.pack_member_bundle`) uses the same
deterministic zip rules as a folder bundle; with no member present there is no local save. On download every entry must
pass the name rules **and** belong to a member the layout owns (`unpack_member_bundle`), or the whole bundle is refused
before anything is written. Only then are the game's current members moved into one `.romm-backup/<label>_<ts>` folder
under their zip paths (the same funnel and retention) and the staged members moved into their directories, one by one;
moves fall back to copy-and-delete when a linked folder is on another drive. The layout reaches the download and
quarantine paths through the ROM's save set (`save_set=` on `do_download_save` / `quarantine_local_file`); a member
bundle name without its save set raises rather than being treated as a plain file.

## Evidence level, and where the audit has since disagreed

The classification below was a desk audit: libretro documentation plus core source reading, one pass, no per-core
observation. [emu-atlas](https://github.com/danielcopper/emu-atlas) is auditing the same ground with an explicit
evidence grade per core (source / binary / live), and as of its 2026-07-24 snapshot has reached **17 of RetroDECK's 159
libretro cores and none of the 22 standalone emulators**. Treat an unrevised row here as a documented expectation, not a
verified fact.

Every core the atlas audit has reached and disagreed with, corrected here:

| Core      | Was           | Audit finding                                                                                                                                                                                                                                        |
| --------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `opera`   | ✅ `.srm`     | Wrong. `RETRO_MEMORY_SAVE_RAM` returns NULL — there is no RetroArch-side `.srm` at all. NVRAM goes to `<save_dir>/opera/per_game/<rom_stem>.<version>.srm`, the version coming from `opera_nvram_version`. Per-game, but subdir + infix → class (b). |
| `flycast` | 🔴 (c) shared | Shared is the shipped default (`reicast_per_content_vmus=disabled` → `<system_dir>/dc/vmu_save_A1.bin` …). The core is **per-game capable**: the `VMU A1` / `All VMUs` modes root at `savefile_directory`; their filename scheme is unestablished.   |
| `pcsx2`   | 🔴 (c) shared | Shared is the shipped default (`pcsx2_shared_memory_cards=enabled` → `<system_dir>/pcsx2/memcards/Mcd00{1,2}.ps2`). Disabled, slot 1 is `<save_dir>/<rom_stem>.ps2` — **class (a)**, reachable by an extension-map entry alone.                      |
| `neocd`   | 🔴 (c) shared | Per-game capable: `path.cpp:137-168` proves a per-content mode alongside the frontend save RAM path. Load precedence between the two is unobserved.                                                                                                  |
| `ppsspp`  | 🔴 (c) shared | Not established. The shipped sort override is known; the save subtree and its granularity are not.                                                                                                                                                   |
| `dolphin` | 🔴 (c) `.gci` | Not established. RetroDECK's prepared `dolphin-emu` subtree suggests a different root, but no core-written save has been observed.                                                                                                                   |
| `azahar`  | absent        | RetroDECK now ships Azahar for `n3ds` where this table still listed Citra. Verdict suspect — prepared save subtree suggests a deviation, nothing observed.                                                                                           |

Two of these are strategically relevant. `pcsx2` and `flycast` are not class (c) by nature — they are class (c) _as
configured_, which is exactly the "prefer per-game mode" path below, and it makes PS2 the cheapest of the shared-card
systems to support. The `opera` correction runs the other way: 3DO was published as syncing and does not.

The row set below is also a 2026-06-04 snapshot of RetroDECK's core list and has drifted (Azahar is one instance).

## Full core reference

Per-core classification from the audit of every RetroArch core RetroDECK can launch. `✅` syncs today · `🟡 (a)`
per-game, extension not listed yet · `🟠 (b)` per-game with a slot/unit infix · `🔴 (c)` shared / out-of-folder · `⚪`
no battery save · `❓` unverified. Non-`.srm` rows are libretro-documented and await on-device confirmation. Snapshot:
2026-06-04, with the rows above revised 2026-08-02.

??? note "All 156 cores, classified"

    | Core | Status | Save file(s) | Naming / dir | Used by (slugs) |
    | --- | --- | --- | --- | --- |
    | `boom3_libretro` | 🔴 (c) | `.save` | system_dir / content | doom |
    | `boom3_xp_libretro` | 🔴 (c) | `.save` | system_dir / content | doom |
    | `cannonball_libretro` | 🔴 (c) | `.xml` | shared_fixed_name / system | ports |
    | `cap32_libretro` | 🔴 (c) | `.sna` | single_token_nonstandard / content | amstradcpc, gx4000 |
    | `dosbox_svn_libretro` | 🔴 (c) | — | system_dir / saves | dos, pc |
    | `easyrpg_libretro` | 🔴 (c) | `.lsd`, `.lyn`, `.dyn`, `.lgs` | single_token_nonstandard / content | easyrpg |
    | `flycast_libretro` | 🔴 (c) | `.bin` | shared_fixed_name / system | arcade, atomiswave, consolearcade, dreamcast, mame +3 |
    | `mame2000_libretro` | 🔴 (c) | `.nv` | shared_fixed_name / system | arcade, cps, cps1, cps2, cps3 +1 |
    | `mame2003_libretro` | 🔴 (c) | `.nv` | shared_fixed_name / saves | arcade, cps, cps1, cps2, cps3 +1 |
    | `mame2003_plus_libretro` | 🔴 (c) | — | single_token_nonstandard / saves | arcade, cps, cps1, cps2, cps3 +1 |
    | `mame2010_libretro` | 🔴 (c) | `.nv` | system_dir / saves | arcade, cps, cps1, cps2, cps3 +1 |
    | `mame_libretro` | 🔴 (c) | `.nv` | system_dir / saves | apple2, apple2gs, arcade, arcadia, astrocde +29 |
    | `mess2015_libretro` | 🔴 (c) | — | system_dir / system | mess |
    | `neocd_libretro` | 🔴 (c) | `.srm` | shared_fixed_name / saves | neogeocd, neogeocdjp |
    | `openlara_libretro` | 🔴 (c) | `.dat` | shared_fixed_name / saves | ports |
    | `pcsx2_libretro` | 🔴 (c) | `.ps2` | shared_fixed_name / system | ps2 |
    | `prboom_libretro` | 🔴 (c) | `.dsg` | shared_fixed_name / saves | doom |
    | `px68k_libretro` | 🔴 (c) | — | system_dir / system | x68000 |
    | `scummvm_libretro` | 🔴 (c) | — | system_dir / system | scummvm |
    | `vitaquake2-rogue_libretro` | 🔴 (c) | — | shared_fixed_name / content | quake |
    | `vitaquake2-xatrix_libretro` | 🔴 (c) | — | shared_fixed_name / content | quake |
    | `vitaquake2-zaero_libretro` | 🔴 (c) | — | shared_fixed_name / content | quake |
    | `vitaquake2_libretro` | 🔴 (c) | — | shared_fixed_name / content | quake |
    | `mednafen_psx_hw_libretro` | 🟠 (b) | `.srm`, `.mcr` | infix / saves | psx |
    | `mednafen_psx_libretro` | 🟠 (b) | `.srm`, `.mcr` | infix / saves | psx |
    | `opera_libretro` | 🟠 (b) | `.srm` | version infix / saves subdir `opera/per_game` | 3do |
    | `pcsx_rearmed_libretro` | 🟠 (b) | `.srm`, `.mcd` | infix / saves | psx |
    | `swanstation_libretro` | 🟠 (b) | `.mcd`, `.mcr` | infix / saves | psx |
    | `tyrquake_libretro` | 🟠 (b) | `.sav` | infix / saves | quake |
    | `virtualjaguar_libretro` | 🟠 (b) | `.srm`, `.cdrom.srm` | infix / saves | atarijaguar |
    | `dosbox_pure_libretro` | 🟡 (a) | `.pure.zip`, `.save.zip` | single_token_nonstandard / saves | dos, pc, windows3x, windows9x |
    | `kronos_libretro` | 🟡 (a) | `.ram` | single_token_nonstandard / saves | arcade, consolearcade, mame, saturn, saturnjp +1 |
    | `nxengine_libretro` | 🟡 (a) | `.dat` | single_token_nonstandard / saves | ports |
    | `retro8_libretro` | 🟡 (a) | `.p8d.txt` | single_token_nonstandard / saves | pico8 |
    | `ardens_libretro` | ❓ | — | unknown / unknown | arduboy |
    | `azahar_libretro` | ❓ | — | unknown / unknown | n3ds |
    | `citra2018_libretro` | ❓ | — | unknown / unknown | n3ds |
    | `citra_libretro` | ❓ | — | unknown / unknown | n3ds |
    | `dolphin_libretro` | ❓ | `.gci`, `.gcs` | unknown / unknown | gc, wii |
    | `panda3ds_libretro` | ❓ | — | unknown / unknown | n3ds |
    | `ppsspp_libretro` | ❓ | — | unknown / unknown | psp |
    | `same_cdi_libretro` | ❓ | — | unknown / unknown | cdimono1 |
    | `wasm4_libretro` | ❓ | — | unknown / unknown | wasm4 |
    | `DoubleCherryGB_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | gb, gbc |
    | `blastem_libretro` | ✅ | `.srm` | single_token_default / saves | genesis, megadrive, megadrivejp |
    | `bsnes-jg_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `bsnes_hd_beta_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `bsnes_libretro` | ✅ | `.srm` | single_token_default / saves | gb, gbc, satellaview, sfc, snes +2 |
    | `bsnes_mercury_accuracy_libretro` | ✅ | `.srm` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `desmume2015_libretro` | ✅ | `.dsv` | single_token_default / saves | nds |
    | `desmume_libretro` | ✅ | `.dsv` | single_token_default / saves | nds |
    | `fbneo_libretro` | ✅ | `.nv`, `.fs` | single_token_default / saves | arcade, cps, cps1, cps2, cps3 +5 |
    | `fceumm_libretro` | ✅ | `.srm` | single_token_default / saves | famicom, fds, nes |
    | `gambatte_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | gb, gbc |
    | `gearboy_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | gb, gbc |
    | `gearcoleco_libretro` | ✅ | `.srm` | single_token_default / saves | colecovision |
    | `geargrafx_libretro` | ✅ | `.srm` | single_token_default / saves | supergrafx |
    | `gearsystem_libretro` | ✅ | `.srm` | single_token_default / saves | gamegear, mark3, mastersystem, multivision, sg-1000 |
    | `genesis-plus-gx-expanded-rom-size-paprium_libretro` | ✅ | `.srm` | single_token_default / saves | megadrive, megadrivejp |
    | `genesis_plus_gx_libretro` | ✅ | `.srm`, `.brm` | single_token_default / saves | gamegear, genesis, mark3, mastersystem, megacd +5 |
    | `genesis_plus_gx_wide_libretro` | ✅ | `.srm`, `.brm` | single_token_default / saves | gamegear, genesis, mark3, mastersystem, megacd +5 |
    | `geolith_libretro` | ✅ | `.srm`, `.nv`, `.mcr` | single_token_default / saves | arcade, mame, neogeo |
    | `gpsp_libretro` | ✅ | `.srm` | single_token_default / saves | gba |
    | `mednafen_ngp_libretro` | ✅ | `.flash` | single_token_default / saves | ngp, ngpc |
    | `mednafen_pce_fast_libretro` | ✅ | `.srm` | single_token_default / saves | pcengine, pcenginecd, tg16, tg-cd |
    | `mednafen_pce_libretro` | ✅ | `.srm` | single_token_default / saves | pcengine, pcenginecd, supergrafx, tg16, tg-cd |
    | `mednafen_pcfx_libretro` | ✅ | `.srm` | single_token_default / saves | pcfx |
    | `mednafen_saturn_libretro` | ✅ | `.bkr`, `.bcr`, `.smpc` | single_token_default / saves | saturn, saturnjp |
    | `mednafen_supafaust_libretro` | ✅ | `.srm` | single_token_default / saves | sfc, snes, snesna |
    | `mednafen_supergrafx_libretro` | ✅ | `.srm` | single_token_default / saves | supergrafx, tg16 |
    | `mednafen_vb_libretro` | ✅ | `.srm` | single_token_default / saves | virtualboy |
    | `mednafen_wswan_libretro` | ✅ | `.srm` | single_token_default / saves | wonderswan, wonderswancolor |
    | `melonds_libretro` | ✅ | `.sav` | single_token_default / content | nds |
    | `melondsds_libretro` | ✅ | `.srm` | single_token_default / saves | nds |
    | `mesen-s_libretro` | ✅ | `.srm` | single_token_default / saves | gb, gbc, satellaview, sfc, sgb +2 |
    | `mesen_libretro` | ✅ | `.srm` | single_token_default / saves | famicom, fds, nes |
    | `mgba_libretro` | ✅ | `.srm` | single_token_default / saves | gb, gba, gbc, sgb |
    | `mupen64plus_next_libretro` | ✅ | `.srm` | single_token_default / saves | n64, n64dd |
    | `nestopia_libretro` | ✅ | `.srm` | single_token_default / saves | famicom, fds, nes |
    | `noods_libretro` | ✅ | `.srm` | single_token_default / saves | gba |
    | `parallel_n64_libretro` | ✅ | `.srm` | single_token_default / saves | n64, n64dd |
    | `picodrive_libretro` | ✅ | `.srm` | single_token_default / saves | gamegear, genesis, mark3, mastersystem, megacd +7 |
    | `pokemini_libretro` | ✅ | `.eep` | single_token_default / saves | pokemini |
    | `potator_libretro` | ✅ | `.srm` | single_token_default / saves | supervision |
    | `puae2021_libretro` | ✅ | `.nvr` | single_token_default / saves | amiga, amiga1200, amiga600, amigacd32, cdtv |
    | `puae_libretro` | ✅ | `.nvr` | single_token_default / saves | amiga, amiga1200, amiga600, amigacd32, cdtv |
    | `quasi88_libretro` | ✅ | `.srm` | single_token_default / saves | pc88 |
    | `quicknes_libretro` | ✅ | `.srm` | single_token_default / saves | famicom, nes |
    | `race_libretro` | ✅ | `.ngf` | single_token_default / saves | ngp, ngpc |
    | `sameboy_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | gb, gbc, sgb |
    | `sameduck_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | megaduck |
    | `smsplus_libretro` | ✅ | `.srm` | single_token_default / saves | gamegear, mark3, mastersystem |
    | `snes9x2005_plus_libretro` | ✅ | `.srm` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `snes9x2010_libretro` | ✅ | `.srm` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `snes9x_libretro` | ✅ | `.srm` | single_token_default / saves | satellaview, sfc, snes, snesna, sufami |
    | `stella2014_libretro` | ✅ | `.srm` | single_token_default / saves | atari2600 |
    | `stella2023_libretro` | ✅ | `.srm` | single_token_default / saves | atari2600 |
    | `stella_libretro` | ✅ | `.srm` | single_token_default / saves | atari2600 |
    | `tgbdual_libretro` | ✅ | `.srm`, `.rtc` | single_token_default / saves | gb, gbc |
    | `tic80_libretro` | ✅ | `.srm` | single_token_default / saves | tic80 |
    | `vba_next_libretro` | ✅ | `.srm` | single_token_default / saves | gba |
    | `vbam_libretro` | ✅ | `.srm` | single_token_default / saves | gb, gba, gbc |
    | `vice_x128_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | c64 |
    | `vice_x64_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | c64 |
    | `vice_x64sc_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | c64 |
    | `vice_xplus4_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | plus4 |
    | `vice_xscpu64_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | c64 |
    | `vice_xvic_libretro` | ✅ | `.nvr`, `.d64`, `.d71`, `.d81` | single_token_default / saves | vic20 |
    | `yabasanshiro_libretro` | ✅ | `.bkr`, `.bcr`, `.smpc` | single_token_default / saves | saturn, saturnjp |
    | `yabause_libretro` | ✅ | `.srm` | single_token_default / saves | saturn, saturnjp |
    | `81_libretro` | ⚪ | — | none / none | zx81 |
    | `a5200_libretro` | ⚪ | — | none / none | atari5200 |
    | `arduous_libretro` | ⚪ | — | none / none | arduboy |
    | `atari800_libretro` | ⚪ | — | none / none | atari5200, atari800, atarixe |
    | `b2_libretro` | ⚪ | — | none / none | bbcmicro |
    | `bluemsx_libretro` | ⚪ | — | none / none | colecovision, msx, msx1, msx2, msxturbor +2 |
    | `cdi2015_libretro` | ⚪ | — | none / none | cdimono1 |
    | `chailove_libretro` | ⚪ | — | none / none | chailove |
    | `crocods_libretro` | ⚪ | — | none / none | amstradcpc, gx4000 |
    | `dice_libretro` | ⚪ | — | none / none | arcade, mame |
    | `dirksimple_libretro` | ⚪ | — | none / none | daphne, laserdisc |
    | `dosbox_core_libretro` | ⚪ | — | none / none | dos, pc |
    | `ecwolf_libretro` | ⚪ | — | none / none | ports |
    | `fbalpha2012_cps1_libretro` | ⚪ | — | none / none | cps, cps1, fba |
    | `fbalpha2012_cps2_libretro` | ⚪ | — | none / none | cps, cps2, fba |
    | `fbalpha2012_cps3_libretro` | ⚪ | — | none / none | cps, cps3, fba |
    | `fbalpha2012_libretro` | ⚪ | — | none / none | arcade, cps, cps1, cps2, cps3 +2 |
    | `fbalpha2012_neogeo_libretro` | ⚪ | — | none / none | fba |
    | `fmsx_libretro` | ⚪ | — | none / none | msx, msx1, msx2 |
    | `freechaf_libretro` | ⚪ | — | none / none | channelf |
    | `freeintv_libretro` | ⚪ | — | none / none | intellivision |
    | `frodo_libretro` | ⚪ | — | none / none | c64 |
    | `fuse_libretro` | ⚪ | — | none / none | zxspectrum |
    | `gw_libretro` | ⚪ | — | none / none | gameandwatch, lcdgames |
    | `handy_libretro` | ⚪ | — | none / none | atarilynx |
    | `hatari_libretro` | ⚪ | — | none / none | atarist |
    | `holani_libretro` | ⚪ | — | none / none | atarilynx |
    | `lowresnx_libretro` | ⚪ | — | none / none | lowresnx |
    | `lutro_libretro` | ⚪ | — | none / none | lutro |
    | `mednafen_lynx_libretro` | ⚪ | — | none / none | atarilynx |
    | `mojozork_libretro` | ⚪ | — | none / none | zmachine |
    | `mrboom_libretro` | ⚪ | — | none / none | ports |
    | `mu_libretro` | ⚪ | — | none / none | palm |
    | `nekop2_libretro` | ⚪ | — | none / none | pc98 |
    | `np2kai_libretro` | ⚪ | — | none / none | pc98 |
    | `o2em_libretro` | ⚪ | — | none / none | odyssey2, videopac |
    | `prosystem_libretro` | ⚪ | — | none / none | atari7800 |
    | `squirreljme_libretro` | ⚪ | — | none / none | j2me |
    | `superbroswar_libretro` | ⚪ | — | none / none | ports |
    | `theodore_libretro` | ⚪ | — | none / none | moto, to8 |
    | `uzem_libretro` | ⚪ | — | none / none | uzebox |
    | `vecx_libretro` | ⚪ | — | none / none | vectrex |
    | `vircon32_libretro` | ⚪ | — | none / none | vircon32 |
    | `virtualxt_libretro` | ⚪ | — | none / none | dos, pc |
    | `vitaquake3_libretro` | ⚪ | — | none / none | quake |
    | `x1_libretro` | ⚪ | — | none / none | x1 |
