# Game Mods (Windows / EmuDeck)

The game page's **Mods** panel tells the user where a game's mods go for the emulator it launches with, lists what is
there, and installs, removes and switches on what the emulator needs. User-facing behaviour is in
[the Windows guide](../user-guide/windows.md#mods); this page is how it is built and the rules it holds.

## Layers

| Layer   | Module                                              | Owns                                                                                                    |
| ------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Domain  | `domain/game_mods.py`                               | Emulator identification, portable-layout rules, mod targets, ini switch read/edit, install planning     |
| Domain  | `domain/mod_targets.py`                             | Cheat-file, built-in-toggle and graphic-pack targets; Cemu's home; what other emulators do not offer    |
| Domain  | `domain/mod_toggles.py`                             | Reading and switching Dolphin codes, PCSX2 patches and cheats, Azahar cheats                            |
| Domain  | `domain/disc_ids.py`                                | Game identifiers, the 3DS title ID, and the PS2 boot ELF path and PCSX2 CRC                             |
| Domain  | `domain/console_ids.py`                             | PS3/PS4 `PARAM.SFO`, the Xbox 360 XDVDFS walk and XEX title ID, the Wii U title ID in `meta.xml`        |
| Domain  | `domain/game_content.py`                            | Updates and DLC targets: Azahar CIA install, shadPS4 overlays, RPCS3 and Xenia installed content        |
| Domain  | `domain/rpcs3_patches.py`, `xenia_patches.py`       | Reading and switching RPCS3 patches (YAML tree) and Xenia patches (`*.patch.toml`)                      |
| Domain  | `domain/cemu_packs.py`                              | Which graphic packs name a Wii U title, and switching them in Cemu's `settings.xml`                     |
| Domain  | `domain/mod_files.py`                               | The install data shapes (`SourceEntry`, `PlannedWrite`, `InstallOutcome`), re-exported by `game_mods`   |
| Adapter | `adapters/game_mod_files.py` (`GameModStore`)       | Listing, Downloads, zip/folder reading, the install itself, moves to backup, the ini rewrite, Explorer  |
| Adapter | `adapters/disc_code_reader.py` (`DiscCodeReader`)   | Reading the identifier and the PS2 boot ELF (`Ps2ElfCrcReader`) out of the game file                    |
| Adapter | `adapters/game_process_windows.py`                  | `running_executable_names()` for the "emulator is running" refusal                                      |
| Adapter | `adapters/yaml_codec.py` (`YamlCodec`)              | YAML text to plain maps and back, over the vendored pure-Python PyYAML (`_vendor/yaml`)                 |
| Service | `services/game_mods/service.py` (`GameModsService`) | The nine callables; resolution on every call; the write lock; the installer run                         |
| Service | `services/game_mods/targets.py`                     | Resolving the emulator, its folders and the game's identifier into targets                              |
| Service | `services/game_mods/toggles.py`                     | Reading a toggle target's file(s) and producing the switched text, for all seven formats                |
| UI      | `src/components/ModsButton.tsx`, `ModsModal.tsx`    | The button (native look + installed only) and the panel                                                 |
| UI      | `src/components/ModBuiltinsSection.tsx`             | A built-in-toggle target's entries with On/Off switches, in the panel                                   |
| UI      | `src/components/GameContentSection.tsx`             | The Overview's **Updates & DLC** row: installed content, and the panel opened on update and DLC targets |
| UI      | `src/utils/gamePageExtensions.ts`                   | The game page registry (Forge bridge, below)                                                            |
| UI      | `src/utils/collectorModsBridge.ts`                  | The mods bridge (Forge bridge, below)                                                                   |
| UI      | `src/components/GamePageExtensions.tsx`             | Rendering registered tabs and cards, each in its own error boundary                                     |

`GameModStore` is wired only on Windows (`bootstrap/adapters.py`); with no store, or with a launcher backend other than
EmuDeck, every callable answers `{success: false, reason: "unsupported"}`.

## Resolution — exact or nothing

Every callable resolves afresh; the frontend names a target by **id**, a source by its **Downloads entry name**, and an
installed entry by the **name the backend listed**. No path ever comes from the frontend.

1. The emulator is the executable in the command the game launches with: `ActiveCoreReader.active_emulator_for_rom`
   rendered by the active backend's `LaunchCommandRenderer.resolve_invocation` — the same bake seam the Steam shortcut
   is written from. Its file name identifies Dolphin, PPSSPP, PCSX2, Azahar/Citra/Lime3DS, RetroArch, Cemu, RPCS3, Xenia
   Canary, shadPS4 or xemu.
2. The emulator's data folder is read from its own portable markers beside the executable (`portable.txt`,
   `installed.txt`, `portable.ini`, a `user` folder) and, where the emulator lets the user move a mod root, from its own
   settings file (Dolphin `[General] LoadPath`, PCSX2 `[Folders] Textures`). A layout these rules do not cover answers
   "no known mod folder" with the reason; there is no fallback to a typical path.
3. The per-game folder is named by the identifier read from the game file and validated against the emulator's own
   format (ID6, `ULUS10041`, `SLUS-20946`, 16 upper-case hex digits). An unreadable image gives no target.

RetroArch's soft patch is the exception that needs no identifier: `<content basename>.ips|.bps|.ups` beside the ROM
(atlas `build_soft_patch_candidates`). It is offered only for a single, non-archive, non-disc file, and not when the
core's `.info` says `needs_fullpath = "true"` (RetroArch never patches such content). The vendored atlas records which
patch formats a RetroArch build attempts only for RetroDECK, so the target carries an "unverified" note.

## Target kinds

Every target carries a `kind` saying what it offers, and a `scope` saying how it is written:

| Kind            | Scope                           | Targets                                                                                                                                               |
| --------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `files`         | `game` / `patch`                | Texture packs (Dolphin, PPSSPP, PCSX2, Azahar), RetroArch's soft patch                                                                                |
| `cheatFile`     | `file`                          | One cheat file named for the game: Azahar, PCSX2, RetroArch                                                                                           |
| `builtinToggle` | `toggle`                        | Entries the emulator already has: Dolphin Gecko / Action Replay, PCSX2 patches and cheats, Azahar cheats, RPCS3 and Xenia patches, Cemu graphic packs |
| `riivolution`   | `shared`                        | Dolphin `Load\Riivolution` (Wii)                                                                                                                      |
| `graphicsMods`  | `shared`                        | Dolphin `Load\GraphicMods`, Cemu `graphicPacks`                                                                                                       |
| `layeredFs`     | `game`                          | Azahar `load\mods\<TitleID>`, shadPS4 `<game>-mods`                                                                                                   |
| `update`        | `install` / `game` / `readonly` | Azahar CIA install, shadPS4 `<game>-UPDATE`, RPCS3 and Xenia installed updates (listed only)                                                          |
| `dlc`           | `readonly`                      | Xenia's installed DLC (listed only); Azahar's DLC arrives through the same CIA install as an update                                                   |

A `file` target writes exactly one file, `file_name`, which The Collector names; the source is a single file with the
target's extension (`file_ext`) or a `.zip` holding exactly one, and it is renamed on the way in. A `toggle` target is
never installed into or removed from (`plan_install` refuses it, `removable_name` answers nothing); its entries are read
and switched through `list_mod_builtins` / `set_mod_builtin`. An `install` target takes exactly one `.cia` and hands it
to the emulator's own installer (below); a `readonly` target lists what is there and accepts nothing
(`accepts:
"none"`). Neither is removed from: `removable_name` answers nothing for both, so the panel has no Remove.

## Cheat files

Each name below comes from the emulator's own source:

- **Azahar:** `<user>\cheats\<TitleID:016X>.txt` (`CheatEngine::LoadCheatFile`).
- **PCSX2:** `<cheats>\<SERIAL>_<CRC:08X>.pnach` (`Patch::GetPnachFilename`); the cheats folder is `[Folders] Cheats` of
  `inis\PCSX2.ini`, `cheats` by default. The target carries PCSX2's `[EmuCore] EnableCheats` switch (off by default).
- **RetroArch:** `<cheat_database_path>\<core library name>\<content stem>.cht`
  (`cheat_manager_get_game_specific_filename`), loaded when the game starts. The cheat folder is read from
  `retroarch.cfg` (`:\` is RetroArch's own folder; absent means `<RetroArch>\cheats`); the core name is the core info's
  `corename`, which is what RetroArch's cores report as their library name. Offered only for one content file outside an
  archive. Whether a cheat in it is applied without opening the menu depends on _Auto-Apply Cheats During Game Load_,
  which is not checked.

### The PCSX2 CRC

PCSX2 names a game's patches, cheats and game settings by its serial and the CRC of the boot executable. That CRC is not
a CRC-32: it is the XOR of every little-endian 32-bit word of the ELF, a trailing partial word ignored
(`ElfObject::GetCRC` / `ReadAndGetCRC`, `pcsx2/Elfheader.cpp`). `DiscCodeReaderAdapter.read_ps2_elf_crc` reads
`SYSTEM.CNF`, takes the `BOOT2` path (`cdrom0:\SLUS_209.46;1`, sub-folders allowed), reads that file through the same
ISO 9660 walk the serial is read with — ISO, CSO and CHD (zlib, LZMA, zstd where the runtime has it) — checks the ELF
magic, and folds the words (`domain.disc_ids.ps2_elf_crc`). Answers are cached per file (path, size, mtime). Any other
format, a CHD codec this runtime cannot decode, or a missing or non-ELF boot file gives no PCSX2 cheat or patch target,
and the panel lists them as not offered with the reason.

## Built-in toggles

`list_mod_builtins` answers the entries with `enabled` and `can_toggle`, plus `editable` and a `reason` when no switch
may be written; `set_mod_builtin` switches one entry named by the `entry_id` the list gave. Each format is read the way
its emulator reads it and an edit changes only the lines that carry that one entry's state (`domain/mod_toggles.py`):

- **Dolphin Gecko / Action Replay.** Codes come from the shipped `Sys\GameSettings` inis beside the executable, then the
  user's `User\GameSettings` inis, in Dolphin's load order (`G.ini`, `GAL.ini`, `GALE01.ini`, `GALE01r<rev>.ini`;
  `ConfigLoaders::GetGameIniFilenames`). A code whose state differs from its shipped default is listed as `$name` in the
  user's `[Gecko_Enabled]` / `[Gecko_Disabled]` (or `ActionReplay_…`), as `SaveCodes` writes it; a switch writes only
  `User\GameSettings\<ID6>.ini`, creating it when absent. Read-only when an ini repeats a section, or when another user
  ini (`GAL.ini`, a revision ini) also switches codes — Dolphin merges them, so a switch in one could be overridden. The
  targets carry Dolphin's `[Core] EnableCheats` switch (off by default).
- **PCSX2 patches and cheats.** Patches are the labelled `[name]` groups of `<patches>\<SERIAL>_<CRC>*.pnach` and
  `<CRC>*.pnach`, then the member of the shipped `resources\patches.zip` — skipped when a file on disk has an unlabelled
  patch, as `EnumeratePnachFiles` does. Cheats are the same names in the cheats folder. A group is on when
  `Enable =
  <name>` is in `[Patches]` / `[Cheats]` of `<gamesettings>\<SERIAL>_<CRC>.ini` (a string list: the key
  repeats; `INISettingsInterface`); a switch adds or removes that one line, creating the file when absent. Unlabelled
  patches are always applied, so they are listed and cannot be switched. A settings file with any other repeated key, or
  a line that is not a section, comment or `key = value`, is read-only.
- **Azahar cheats.** The `[name]` blocks of the game's cheat file; a cheat is on when a `*citra_enabled` line follows
  its header (`GatewayCheat::LoadFile` / `ToString`). Read-only when a code line comes before the first header, a header
  has no code lines (Azahar drops it and carries its state to the next cheat) or a name repeats.
- **RPCS3 patches.** The patch lists are `patches\patch.yml`, `imported_patch.yml` and `<SERIAL>_patch.yml` under the
  config root (`<exe folder>\portable` when that folder exists, else the exe folder; `fs::get_config_dir`). Only the
  blocks that name the game's serial are parsed (`patch_list_subset`), each entry listed once per hash, description and
  title. The switch is the entry RPCS3's own patch manager writes in `config\patch_config.yml`: hash → description →
  title → serial → app version → `Enabled: true`, with the serial and `APP_VER` read from `PS3_GAME\PARAM.SFO`
  (`console_ids.ps3_game`). Turning off removes that leaf and prunes the maps it leaves empty, so no executable hash is
  computed here. YAML goes through the vendored pure-Python PyYAML with `BaseLoader` (every scalar stays text: `01.00`
  is not a float) and is dumped with `Enabled` as a bool and `Configurable Values` as numbers. A `patch_config.yml` that
  is not the hash → … tree shape is read-only.
- **Xenia patches.** The files in `<storage root>\patches` whose name matches Xenia's own pattern
  (`^[A-Fa-f0-9]{8}.*\.patch\.toml$`) and starts with the game's title ID, kept only when their `title_id` field is the
  game's. The title ID is read from `default.xex` (a loose `.xex`, or inside an XISO through the XDVDFS directory at the
  four partition offsets; XEX2 optional header `0x00040006`, execution info, title ID at +12). Each `[[patch]]` block's
  `is_enabled` (default `false`) is the switch, edited on its one line. A file with multi-line strings, a repeated patch
  name or a non-bool `is_enabled` is read-only, and so is a game whose patches are split across several files.
- **Cemu graphic packs.** The installed packs (`graphicPacks\**\rules.txt`) whose `[Definition] titleIds` name the game,
  read from `meta\meta.xml` `<title_id>` of a folder game. A pack is on when `settings.xml` has a
  `<GraphicPack><Entry filename="graphicPacks\…\rules.txt">` without `disabled="true"`, otherwise its rules.txt
  `default` applies; the switch adds, edits or removes that one `Entry` line (a self-closing `<GraphicPack/>` is
  expanded). The legacy format and a repeated `GraphicPack` element are read-only.

Every switch is refused while the emulator's executable is running (`emulator_running`), is written only if the file
still holds what was read (`changed` otherwise), and copies the existing file to
`romm-mod-backups\<stamp>\settings\<file name>` first; a file that did not exist is created only if it still does not.

## Updates and DLC

Game content — a title update or DLC for a game the user already has — is offered per emulator as `update` and `dlc`
targets (`domain/game_content.py`), on the Mods panel and from the Overview's **Updates & DLC** row
(`GameContentSection`, controller-only, installed games only), which opens the panel filtered to those kinds. A base
game is never touched, and anything an install replaces is backed up first.

| Emulator     | What is offered                                                                                                                                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Azahar       | Install one `.cia` from Downloads with `azahar -i <cia>` (id `content`, scope `install`). The game's update and DLC title folders under `user\sdmc\Nintendo 3DS\<0×32>\<0×32>\title\0004000e                      |
| shadPS4      | The `<game>-UPDATE` folder beside the game folder (id `update`, a folder source; an existing update folder is moved to the backup whole), and `<game>-mods` (id `overlay_mods`, `layeredFs`)                      |
| RPCS3        | The installed update under `dev_hdd0\game\<SERIAL>` (or where `config\vfs.yml` moves `dev_hdd0`), listed with its version from `PARAM.SFO` (id `update`, `readonly`)                                              |
| Xenia Canary | Installed title updates (`000B0000`) and DLC (`00000002`) under `<content root>\0000000000000000\<TitleID>`, listed (ids `update`, `dlc`, `readonly`); `content_root` from `xenia-canary.config.toml` is followed |

**Azahar's installer.** The run is refused while Azahar is running; with stdout piped Azahar prints instead of showing a
message box, and its exit code is the install status (3–8 map to `AZAHAR_INSTALL_ERRORS`). A non-zero exit answers
`installer_failed` with that reason and the backup folder; the output is logged, never returned whole. A CIA must be the
user's own dump, decrypted, or encrypted with the user's own AES keys set up in Azahar (exit 7 says which).

**Not offered, and why.** Downloading PS3 updates: Sony's update server presents a certificate that cannot be verified,
and the package hashes come from that same unverified answer, so nothing is fetched; RPCS3 also installs packages only
through its desktop window. Installing Xbox 360 content: Xenia reads installed content as folders it extracts itself
(File > Install Content, or Xenia Manager). Both are listed under the panel's omitted entries with these reasons.

## Emulators with no target, and what is not offered

| Emulator | Offered                                                                   | Not offered, and why                                                                                                                               |
| -------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cemu     | `graphicPacks` in the user data folder; switching packs for a folder game | Switching packs for `.wua`/`.wud`/`.wux` images: the title ID is inside the encrypted image and is not read here                                   |
| RPCS3    | Game patches; the installed update (listed)                               | Downloading or installing updates (above)                                                                                                          |
| Xenia    | Game patches; installed updates and DLC (listed)                          | Installing content (above); a game whose `default.xex` cannot be read (an image that is not XISO, a compressed XEX header) has no patch target     |
| shadPS4  | `<game>-UPDATE`, `<game>-mods`                                            | Cheats and patches: kept per download source (XML patches indexed by `files.json`, cheat files) keyed by the game's serial; neither is edited here |
| xemu     | —                                                                         | xemu has no mod, cheat or patch folder                                                                                                             |

Cemu's user data folder is `<exe folder>\portable` when that folder exists, else the exe folder when `settings.xml` sits
beside it (installs from before 2.0-89), else `%APPDATA%\Cemu`, which is not read (`CemuApp::DeterminePaths`). xemu
answers `success` with no targets, a note and the omitted entries; its data folder is not read.

## Install

- **Plan (pure).** `plan_install` refuses the whole source if any entry is a link, is not a plain relative Windows name
  (`mod_entry_name`: no absolute path, drive, colon, `..`, reserved device name, forbidden character, trailing dot or
  space), repeats case-insensitively, or is both a file and a folder. A source whose every entry sits under one top
  folder named like the game folder has that folder dropped (no `GALE01\GALE01`); PCSX2's `replacements` prefix is added
  where missing. A soft patch needs exactly one patch file, renamed to the ROM's stem.
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
copied to `<emulator data folder>\romm-mod-backups\<yyyymmdd-hhmmss>-<id>\<target>\`, on the same volume as the mods so
a texture pack's move is a rename. Removal additionally goes through a confirmation naming the path. The data folder is
the emulator's own, not a mod folder, so no emulator reads the backups as content.

## Setting switch

`read_setting` / `enable_setting` handle one key of a plain ini. A file with a section or key twice, or a line that is
not blank, comment, section or `key = value`, is "unknown" and not editable. The edit changes the value on that one line
(or adds the key at the end of its section, or the section at the end of the file), keeps the file's line endings and
BOM, and is written only if the file still holds what was read. It is refused while the emulator's executable name is in
the process list; when the process list cannot be read the edit goes ahead and the confirmation dialog has already asked
the user to close the emulator.

Defaults when a key is absent come from the emulators' sources: Dolphin `HiresTextures` off, PPSSPP `ReplaceTextures`
on, PCSX2 `LoadTextureReplacements` off.

## Gating

`install_mod`, `remove_mod`, `enable_mod_setting` and `set_mod_builtin` carry `@migration_blocked` and
`@prune_active_blocked` (a soft patch sits beside a ROM the removed-game cleanup may be claiming) and share one
`asyncio.Lock`. The reads (`get_game_mods`, `list_mod_sources`, `preview_mod_install`, `open_mod_folder`,
`list_mod_builtins`) are not gated.

## Forge bridge

Forge (a separate Decky plugin) finds and downloads mods from Nexus Mods and GameBanana. On a ROM's game page The
Collector stays the host and the installer: Forge contributes its UI through the **game page registry** and installs
through the **mods bridge**, and never learns an emulator folder. Both are frontend globals on Steam's shared page
window, each with an integer `version` (both `1`). A breaking change takes a new version number; a field may be added
within a version, and a consumer ignores fields it does not know.

| Global                          | Module                             | Ready event                    |
| ------------------------------- | ---------------------------------- | ------------------------------ |
| `window.__eternalGamePage`      | `src/utils/gamePageExtensions.ts`  | `eternal_game_page_ready`      |
| `window.__eternalCollectorMods` | `src/utils/collectorModsBridge.ts` | `eternal_collector_mods_ready` |

Both are installed when The Collector loads, announced with their ready event on `window`, and withdrawn when it unloads
(the registry also drops every registration and runs each extension's unsubscribe). A plugin that may load first checks
for the global at start and also listens for the ready event, and registers again on every ready event — a reload of The
Collector starts from an empty registry.

### Game page registry

```ts
window.__eternalGamePage = {
  version: 1,
  register(ext: {
    id: string;                                  // "forge.mods"
    kind: "tab" | "overviewCard";
    label: string | ((locale: string) => string);
    order?: number;
    isAvailable?(ctx: RomPageContext): boolean;
    render(ctx: RomPageContext): ReactNode;
    subscribe?(onChange: () => void): () => void;
  }): () => void;                                // unregister
  list(): ReadonlyArray<{ id: string; kind: string }>;
};
type RomPageContext = {
  appId: number; romId: number; name: string; platformSlug: string; platformName: string;
  installed: boolean; locale: string;
  openTab?(extensionId: string): void;           // switch the page to a registered tab
};
```

- **Store.** Registration before or after the page renders both work: the panel (`RomMGameInfoPanel`) reads the registry
  through `useSyncExternalStore` and re-renders on every change. Registering an id again replaces the earlier
  registration; an unregister removes only its own. An invalid extension is refused with a warning. `subscribe` lets an
  extension ask for a re-render (an update count changed); `isAvailable` and `label` are asked on every render.
- **Tabs.** Overview is always first; The Collector's own tabs have orders 20 (Achievements), 30 (Saves), 34 (Media), 37
  (Details) and 40 (BIOS), and an extension tab without `order` gets 100. Ties keep the built-in tab first, then
  registration order. Labels are shown as the extension gives them (Title Case, like the built-in tabs); a tab between
  Achievements and Saves, where the Core board puts Mods, takes an order from 21 to 29. An extension tab that
  unregisters or stops being available while open leaves the page on the Overview.
- **Overview cards** render on the Overview only, in one grid with The Collector's own cards, by `order`:
  RetroAchievements is 10 and Save sync 30, so a Mods card at 20 sits between them and a Club card at 40 after them.
  Each sits in a gunmetal tile with the float radius; a card's own control can call `ctx.openTab("forge.mods")` to open
  its tab.
- **Isolation.** Every extension renders inside its own error boundary, keyed by extension, registration and ROM: a
  throw from `render` (or from a component it returns) hides that extension and is written to the plugin log, and the
  page and every other extension carry on. A throwing `isAvailable` counts as unavailable; a throwing `label` shows the
  id.
- **Identity.** The context is built at render from the panel's state, so after a version switch every extension gets
  the switched-to version's `romId` and name in the same render that re-keys The Collector's own panes. An extension
  that fetches per ROM keys its own state by `romId` (a React `key` is enough); nothing it holds is reset for it.
- **React.** An extension's components come from another plugin's bundle. That works because Decky's build maps `react`
  to the one shared `window.SP_REACT` for every plugin (`@decky/rollup`); an extension must not bundle its own React, or
  its hooks fail inside The Collector's tree. Focus and gamepad navigation are the extension's to provide with
  `@decky/ui` (`Focusable`, `DialogButton`); the tab body and the card stack sit inside the panel's `Focusable`.
- **Mods button.** While an extension with id `forge.mods` is registered, The Collector's own Mods button and panel are
  hidden on every ROM page (Forge's tab replaces them); without it the page is exactly as before.

### Mods bridge

```ts
window.__eternalCollectorMods = {
  version: 1,
  isRomApp(appId): boolean,
  getRomInfo(appId): Promise<(RomPageContext & { emulator: string | null; family: string | null;
                               gameId: string | null; saveSync: boolean; saveBackup: boolean }) | null>,
  getTargets(appId): Promise<GameModsAnswer>,                       // get_game_mods, unchanged
  listSources(appId, targetId?): Promise<ModSourcesAnswer>,         // list_mod_sources
  preview(appId, source, targetId): Promise<ModPreviewAnswer>,      // preview_mod_install
  install(appId, source, targetId, fingerprint): Promise<ModInstallAnswer>, // install_mod
  listInstalled(appId, targetId): Promise<{ success: true; target_id; entries: ModEntry[]; truncated } | Failure>,
  remove(appId, targetId, name: string | null): Promise<ModRemoveAnswer>,   // remove_mod
  readSetting(appId, targetId): Promise<{ success: true; target_id; setting: ModSetting | null } | Failure>,
  enableSetting(appId, targetId): Promise<ModSettingAnswer>,        // enable_mod_setting
  openFolder(appId, targetId): Promise<ModOpenAnswer>,              // open_mod_folder
  // v1 additions (win.29):
  listBuiltins(appId, targetId): Promise<ModBuiltinsAnswer>,        // list_mod_builtins
  setBuiltin(appId, targetId, entryId, enabled: boolean): Promise<ModBuiltinSetAnswer>, // set_mod_builtin
};
```

The shapes are the Mods panel's (`src/types/mods.ts`). The bridge adds no callable: it maps the Steam appId to the ROM
through `get_cached_game_detail` and calls the nine callables above, so every rule on this page holds unchanged —
resolution on every call, the fingerprint check, the gating, the write lock and the backup folder.

- **Failures** keep `{success: false, reason, message}`, and no wrapper throws. The bridge's own reasons:
  `invalid_argument` (an appId that is not a positive integer, a missing target id or fingerprint), `invalid_source` (a
  source that is not a plain entry name), `not_a_rom` (an app that is not one of The Collector's ROMs), `no_target`
  (`listSources` without a target id for a game with no mod folder) and `bridge_error` (a callable that rejected).
  `getRomInfo` answers `null` instead.
- **`getRomInfo`.** `emulator` is the mod emulator id (`dolphin`, `ppsspp`, `pcsx2`, `azahar`, `retroarch`) and `family`
  the identifier family its per-game folders are named by (`gc-wii`, `psp`, `ps2`, `3ds`; `null` for RetroArch's soft
  patch), both `null` when mods are unsupported or the game is not installed. `gameId` is the identifier read from the
  game file (`GALE01`).
- **`listSources` without a target id** lists for the game's first target.
- **`listInstalled` and `readSetting`** are read from `get_game_mods` (each target's `installed` and `setting`).
- **v1 additions.** A target's `kind` and `file_name` are new fields of `getTargets`' answer, and `accepts` gains
  `cheat_file` and `none`. A cheat file installs through `preview` / `install` like any source: Forge passes the
  Downloads entry name and The Collector writes it as the target's `file_name`. `listBuiltins` / `setBuiltin` work on
  `builtinToggle` targets only (`unsupported` otherwise); `setBuiltin` takes the `entry_id` `listBuiltins` answered and
  is refused with `not_editable`, `emulator_running`, `changed` or `not_found` as described under
  [Built-in toggles](#built-in-toggles).
- **v1 additions (win.30).** `kind` gains `update` and `dlc`, `scope` gains `install` and `readonly`, `accepts` gains
  `cia_file`, and a source may be a `.cia`. New target ids: `content` (Azahar CIA), `update`, `dlc`, `overlay_mods`
  (shadPS4), `pack_toggles` (Cemu) and `patches` as a toggle target for RPCS3 and Xenia. `preview` answers
  `replaces_folder` (a whole folder moves to the backup) and `installer` (the emulator's installer runs); `install` may
  fail with `installer_failed`, carrying `backup_folder`. `getRomInfo` answers `emulator` `rpcs3`, `xenia`, `cemu` or
  `shadps4` (with `family` `null`) and two save facts, both `false` unless the plugin's own state says otherwise:
  `saveSync` is true when save sync is on for the ROM, has checked it at least once, and no save is in conflict or of
  unknown status; `saveBackup` is true when save sync is on and at least one save of the ROM is recorded as synced to
  RomM, so a copy The Collector could restore exists there.

### Where Forge puts a download

A source is a **Downloads entry name**, never a path, and the bridge refuses a name holding `/`, `\`, `:` or a NUL
before anything reaches the backend. `GameModFilesAdapter` lists the top of `%USERPROFILE%\Downloads` (the user's home
`Downloads` when `USERPROFILE` is unset; a relocated Downloads folder is not followed). Forge saves a downloaded archive
there, under its own file name, and passes that name. A Forge subfolder inside Downloads was not added: a folder in
Downloads is itself an installable source (a mod extracted to a folder), so a staging folder would be listed as one, and
entry names are deliberately single names with no separator.

### What Forge may and may not do

- **May:** draw a Mods tab and an Overview card on ROM pages; read targets, sources, installed entries and the setting;
  preview and install (cheat files included); remove an entry the backend listed (or the whole game folder with `null`);
  turn on the emulator's setting; list and switch a built-in-toggle target's entries; open a mod folder.
- **Must:** show the preview before installing and pass its `fingerprint`; confirm a removal with the user, naming what
  moves, before calling `remove` (the Mods panel does the same); handle every failure answer.
- **May not:** pass a path anywhere; write into an emulator folder itself; delete anything (removal moves to
  `romm-mod-backups`); read or change any other Collector state.
