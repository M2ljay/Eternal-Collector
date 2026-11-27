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
| UI      | `src/utils/gamePageExtensions.ts`                 | The game page registry (Forge bridge, below)                                                           |
| UI      | `src/utils/collectorModsBridge.ts`                | The mods bridge (Forge bridge, below)                                                                  |
| UI      | `src/components/GamePageExtensions.tsx`           | Rendering registered tabs and cards, each in its own error boundary                                    |

`GameModStore` is wired only on Windows (`bootstrap/adapters.py`); with no store, or with a launcher backend other than
EmuDeck, every callable answers `{success: false, reason: "unsupported"}`.

## Resolution — exact or nothing

Every callable resolves afresh; the frontend names a target by **id**, a source by its **Downloads entry name**, and an
installed entry by the **name the backend listed**. No path ever comes from the frontend.

1. The emulator is the executable in the command the game launches with: `ActiveCoreReader.active_emulator_for_rom`
   rendered by the active backend's `LaunchCommandRenderer.resolve_invocation` — the same bake seam the Steam shortcut
   is written from. Its file name identifies Dolphin, PPSSPP, PCSX2, Azahar/Citra/Lime3DS or RetroArch.
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

PCSX2 `.pnach` patches and cheats are named `<SERIAL>_<CRC>.pnach` (atlas `mods.json`, `PCSX2`), and the ELF CRC is not
read, so they are listed as omitted rather than offered.

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

`install_mod`, `remove_mod` and `enable_mod_setting` carry `@migration_blocked` and `@prune_active_blocked` (a soft
patch sits beside a ROM the removed-game cleanup may be claiming) and share one `asyncio.Lock`. The reads
(`get_game_mods`, `list_mod_sources`, `preview_mod_install`, `open_mod_folder`) are not gated.

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
- **Tabs.** GAME INFO (the page's Overview) is always first; The Collector's own tabs have orders 20 (Achievements), 30
  (Saves) and 40 (BIOS), and an extension tab without `order` gets 100. Ties keep the built-in tab first, then
  registration order. Labels are shown upper-cased like the built-in tabs. An extension tab that unregisters or stops
  being available while open leaves the page on GAME INFO.
- **Overview cards** render at the top of GAME INFO, in `order`, and only there. A card's own control can call
  `ctx.openTab("forge.mods")` to open its tab.
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
                               gameId: string | null }) | null>,
  getTargets(appId): Promise<GameModsAnswer>,                       // get_game_mods, unchanged
  listSources(appId, targetId?): Promise<ModSourcesAnswer>,         // list_mod_sources
  preview(appId, source, targetId): Promise<ModPreviewAnswer>,      // preview_mod_install
  install(appId, source, targetId, fingerprint): Promise<ModInstallAnswer>, // install_mod
  listInstalled(appId, targetId): Promise<{ success: true; target_id; entries: ModEntry[]; truncated } | Failure>,
  remove(appId, targetId, name: string | null): Promise<ModRemoveAnswer>,   // remove_mod
  readSetting(appId, targetId): Promise<{ success: true; target_id; setting: ModSetting | null } | Failure>,
  enableSetting(appId, targetId): Promise<ModSettingAnswer>,        // enable_mod_setting
  openFolder(appId, targetId): Promise<ModOpenAnswer>,              // open_mod_folder
};
```

The shapes are the Mods panel's (`src/types/mods.ts`). The bridge adds no callable: it maps the Steam appId to the ROM
through `get_cached_game_detail` and calls the seven callables above, so every rule on this page holds unchanged —
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

### Where Forge puts a download

A source is a **Downloads entry name**, never a path, and the bridge refuses a name holding `/`, `\`, `:` or a NUL
before anything reaches the backend. `GameModFilesAdapter` lists the top of `%USERPROFILE%\Downloads` (the user's home
`Downloads` when `USERPROFILE` is unset; a relocated Downloads folder is not followed). Forge saves a downloaded archive
there, under its own file name, and passes that name. A Forge subfolder inside Downloads was not added: a folder in
Downloads is itself an installable source (a mod extracted to a folder), so a staging folder would be listed as one, and
entry names are deliberately single names with no separator.

### What Forge may and may not do

- **May:** draw a Mods tab and an Overview card on ROM pages; read targets, sources, installed entries and the setting;
  preview and install; remove an entry the backend listed (or the whole game folder with `null`); turn on the emulator's
  setting; open a mod folder.
- **Must:** show the preview before installing and pass its `fingerprint`; confirm a removal with the user, naming what
  moves, before calling `remove` (the Mods panel does the same); handle every failure answer.
- **May not:** pass a path anywhere; write into an emulator folder itself; delete anything (removal moves to
  `romm-mod-backups`); read or change any other Collector state.
