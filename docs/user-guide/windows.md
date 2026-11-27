# Windows (EmuDeck)

This fork's `windows` branch runs RomM-Dock on a Windows PC as **The Collector**, inside Steam Big Picture with Decky
Loader for Windows (Playhub), launching games through EmuDeck for Windows instead of RetroDECK.

## What differs from the Steam Deck build

- **Launcher.** Shortcuts run `bin\rom-launcher.exe`. It starts the emulator EmuDeck uses for the system directly (not
  through EmuDeck's PowerShell launcher scripts, which run a `git pull` and EmuDeck Cloud Sync on every launch), stops
  the emulator when you stop the game in Steam, and brings Big Picture back to the front when the emulator exits. Each
  launch is logged to `bin\rom-launcher.log`.
- **Launch curtain.** While the emulator starts and while it shuts down, the screen shows the Core logo on black, so its
  menu window or a blank white window never flashes up; it lifts as soon as the game is fullscreen, so console boot
  screens still play. PS2 games start PCSX2 with `-nogui -fullscreen`, which skips its menu window entirely (a library
  sync applies this to existing shortcuts).
- **PS Vita.** A downloaded Vita game is linked into Vita3K's `ux0/app/<TITLE_ID>` and launched by title ID.
- **Game page.** On Windows the Play, Install and menu buttons use Steam's own button styles, so they follow your Steam
  theme.
- **Collections.** With the default **Classic** [collection names](configuration.md#collection-names), platform
  collections use the plain platform name (`Nintendo 64`) and RomM collections use `[Collection name]`, instead of
  `RomM: Nintendo 64 (host)`; **Clean** drops the brackets too. The Collector only renames, refills or deletes the
  collections it made itself. After updating, the first sync takes over the collections an earlier version made — one
  that carries the `RomM:` prefix, or a plain-named one holding nothing but RomM games; a plain-named collection holding
  any other game stays yours. An old `RomM: …` collection left beside its plain-named replacement is no longer deleted
  automatically; delete it yourself if you no longer want it.
- **Wording.** Setup and health messages name EmuDeck instead of RetroDECK, and BIOS deletion refers to your BIOS
  folder.
- **Logos.** A logo downloaded for a RomM game gets Steam's default bottom-left placement once, so it shows on the game
  page; a position you set later in Steam is kept.

## Save sync

Games that launch with a RetroArch core sync their saves exactly as on the Steam Deck, from EmuDeck's
`saves\retroarch\saves` folder. Games that launch with one of these standalone emulators sync that emulator's saves
instead, from the folders EmuDeck keeps under its saves folder (`C:\Emulation\saves\` by default — the plugin reads the
real location from EmuDeck's settings):

| Emulator    | Folder                                 | What syncs for a ROM named `<game>`                                                                              |
| ----------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| melonDS     | `C:\Emulation\saves\melonds\saves`     | `<game>.sav`                                                                                                     |
| DuckStation | `C:\Emulation\saves\duckstation\saves` | `<game>_1.mcd` and `<game>_2.mcd`                                                                                |
| Vita3K      | `C:\Emulation\saves\Vita3K\saves`      | the `<TITLE_ID>` folder of the installed game                                                                    |
| Dolphin     | `C:\Emulation\saves\dolphin`           | GameCube: the game's `.gci` files in `GC\<USA/EUR/JAP>\Card A` and `Card B`; Wii: `Wii\title\00010000\<id>\data` |
| PPSSPP      | `C:\Emulation\saves\ppsspp\saves`      | every save-data folder starting with the game's ID (`ULUS10234…`)                                                |
| PCSX2       | `C:\Emulation\saves\pcsx2\saves`       | the game's save folders (`BASLUS-20062…`) on the folder memory card in slot 1                                    |

Which emulator counts is the one the game actually launches with — your per-game or per-platform choice, else EmuDeck's
default. A PlayStation game you launch with a RetroArch core keeps syncing RetroArch's save. Each emulator's saves are
stored on RomM under that emulator's name (`melonds`, `duckstation`, `vita3k`, `dolphin`, `ppsspp`, `pcsx2`), so saves
from different emulators never overwrite each other. Only files positively identified as the game's are read or written.
Savestates are not synced; RetroArch savestates can be backed up to RomM (see
[Savestate backup](save-sync.md#savestate-backup)), standalone emulators' cannot yet.

!!! note "DuckStation: the card must be named after your ROM"

    DuckStation names a per-game memory card after the game's title in its own database. That is usually the same as
    your ROM's file name (`R4 - Ridge Racer Type 4 (USA).chd` → `R4 - Ridge Racer Type 4 (USA)_1.mcd`), but not
    always. Only a card named **exactly** `<ROM file name without extension>_1.mcd` (or `_2.mcd`) syncs; a card with a
    different name stays on this PC and is not uploaded. Renaming the ROM, or the card, so the two match makes it sync.
    DuckStation's per-game memory card mode must be on (it is DuckStation's default).

!!! note "PS Vita: the save folder travels as one file"

    A Vita save is a folder (for example `PCSE01274\SlotParam_0.bin`, `system.bin`). The plugin packs it into
    `PCSE01274.vita3k.zip` next to the folder and syncs that one file; the zip is rebuilt from the folder whenever it
    changes, so you never need to touch it. When a newer save comes down from RomM, your current folder is first moved
    to `.romm-backup\PCSE01274_<date>_<time>` in the same saves folder (the last 10 are kept), then replaced. This works
    for games installed by the plugin, whose launch file is `<TITLE_ID>.psvita`.

!!! note "Dolphin, PPSSPP, PCSX2: the game is identified from its disc image"

    These emulators file a save under the code printed in the game itself (`GALE01`, `ULUS10234`, `SLUS-20062`), so the
    plugin reads that code from the installed image — only the few bytes that hold it, never the whole file. These
    formats are read:

    | System   | Formats                        |
    | -------- | ------------------------------ |
    | GameCube | `.rvz`, `.wia`, `.iso`, `.gcm` |
    | Wii      | `.rvz`, `.wia`, `.iso`         |
    | PSP      | `.iso`, `.cso`, `.chd`         |
    | PS2      | `.iso`, `.chd` (DVD or CD)     |

    A game in any other format (`.wbfs`, `.gcz`, `.ciso`, `.pbp`, `.zso`, `.cue`/`.bin`, …), or an image that cannot be
    read exactly, does not sync its emulator saves. CHD images compressed with zstd cannot be read on Windows either
    (`chdman`'s defaults do not use zstd). Several saves of one game — all its GameCube `.gci` files, all its PSP or PS2
    save folders — travel together as one file (`GALE01.dolphin-gc.zip`, `ULUS10234.ppsspp.zip`,
    `SLUS-20062.pcsx2.zip`, `SMOX.dolphin-wii.zip`) kept in the emulator's saves folder. Other games' saves, Dolphin's
    `SRAM.raw` and `MemoryCard*.raw`, and PCSX2's own card files are never read or changed. When a newer save comes down,
    this game's current saves are first moved to `.romm-backup` in that folder.

!!! note "PCSX2: use a folder memory card in slot 1"

    PCSX2 must use a **folder** memory card (Settings → Memory Cards → create a card of type *Folder*) in slot 1, in its
    normal `memcards` folder. The plugin reads PCSX2's `inis\PCSX2.ini` to find which card is in slot 1; if slot 1 holds
    a regular file card such as `Mcd001.ps2` (EmuDeck's default), is disabled, or the ini cannot be read, PS2 saves do
    not sync. Per-game memory-card overrides are not followed. The game's page then shows _Saves not syncing_ with the
    reason (for example _PS2 saves aren't syncing: PCSX2 is using a single-file memory card. Switch slot 1 to a folder
    card._), and the same sentence appears as a notification when you quit the game. The game still launches.

!!! note "Dolphin GameCube: GCI folders"

    Dolphin must store GameCube saves in GCI folders (memory card slot set to *GCI Folder*). The region folder is chosen
    from the disc's ID as Dolphin does; a few special releases whose region Dolphin works out differently are not
    identified and do not sync. Saves in a raw memory card file (`MemoryCardA.USA.raw`) are not synced.

Removing a game from your library does not touch these standalone save folders.

## RetroAchievements check

When a game starts, The Collector looks at the settings of the emulator that runs it and shows **one** notice if
RetroAchievements will not work there, for example _RetroAchievements isn't working in PCSX2: not signed in._ It never
stops or delays the game.

- **Checked:** PCSX2, DuckStation, Dolphin (GameCube only; RetroAchievements has no Wii games), PPSSPP and RetroArch.
  Emulators without RetroAchievements (Azahar, RPCS3, melonDS, Cemu, xemu, Vita3K, Eden) and systems RetroAchievements
  does not cover are never checked.
- **What counts as not working:** achievements turned off in the emulator, or no login stored. The check only looks at
  whether a username and token are present; it never reads them out, copies them or writes them to a log.
- **PCSX2 only:** if the settings look fine, PCSX2's own log (`logs\emulog.txt`) is checked once after the game closes,
  and a failed login during that session gets the notice instead. The other emulators do not keep a log file by default.
- **Silent cases:** if the emulator's settings file cannot be found (for example an emulator never opened), nothing is
  shown. A game that already got a notice at start gets no second one when it closes.
- **Turning it off:** _Settings → Library → Warn when RetroAchievements isn't working_.

PPSSPP can turn achievements on per game; the check reads only the global setting. In RetroArch, a core without
achievement support is not detected.

## Mods

An installed game's page has a **Mods** button (the puzzle piece, next to the RomM and Steam menus). It opens a panel
for that game that shows where its mods go for the emulator it launches with, what is already there, and lets you
install from your Downloads folder, remove, open the folder in Explorer, and turn on the emulator's texture setting.

Every folder is worked out from your machine — the emulator the game actually launches with, that emulator's portable
folder, its own settings file, and the ID read from the game file itself. When any of that can't be read exactly, the
panel says **No known mod folder for this emulator** and why, rather than guessing a folder.

| Emulator                       | What the panel offers                                                                                                                                    | Setting it checks                                          |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Dolphin (GameCube, Wii)        | Texture pack in `User\Load\Textures\<ID6>`; graphics mods in `User\Load\GraphicMods` (shared); Wii only: Riivolution in `User\Load\Riivolution` (shared) | `[Settings] HiresTextures` in `User\Config\GFX.ini`        |
| PPSSPP (PSP)                   | Texture pack in `memstick\PSP\TEXTURES\<GAME ID>`                                                                                                        | `[Graphics] ReplaceTextures` in `PSP\SYSTEM\ppsspp.ini`    |
| PCSX2 (PS2)                    | Texture replacements in `textures\<SERIAL>\replacements`                                                                                                 | `[EmuCore/GS] LoadTextureReplacements` in `inis\PCSX2.ini` |
| Azahar / Citra / Lime3DS (3DS) | Mods (`romfs` / `exefs`) in `user\load\mods\<TITLE ID>`; custom textures in `user\load\textures\<TITLE ID>`                                              | —                                                          |
| RetroArch (cartridge games)    | A soft patch beside the ROM: `<ROM name>.ips`, `.bps` or `.ups`                                                                                          | —                                                          |

- **Which emulator folder.** Only portable installs are read, which is how EmuDeck installs them: Dolphin with
  `portable.txt` beside `Dolphin.exe`; PPSSPP with its `memstick` folder and no `installed.txt`; PCSX2 with
  `portable.ini` (or an empty `portable.txt`); Azahar/Citra with a `user` folder beside the exe. Dolphin's custom _Load_
  path and PCSX2's custom _Textures_ folder are followed.
- **Game IDs.** GameCube/Wii, PSP and PS2 IDs come from the disc image (the same reader save sync uses: ISO, GCM, RVZ,
  WIA, CSO, CHD). 3DS title IDs come from `.3ds`, `.cci`, `.cxi`, `.app` and `.cia` files; `.3dsx` homebrew has none, so
  it gets no mod folder.
- **Not offered.** PCSX2 patches and cheats (`.pnach`) are named by the game's executable CRC, which the plugin does not
  read. Dolphin's _Enable Graphics Mods_ and Azahar's _Use Custom Textures_ settings are not checked. Other emulators
  (Cemu, xemu, RPCS3, …) show no folder.
- **Soft patches.** RetroArch applies the patch in memory each launch; the ROM file is never changed. It only works for
  a single cartridge file loaded into memory, so zipped ROMs, disc images and cores that read the game from disk (their
  core info says `needs_fullpath`) get no soft-patch option. Which patch formats EmuDeck's RetroArch build tries is
  unverified.

### Installing

**Install from Downloads** lists the top of `%USERPROFILE%\Downloads`, newest first: `.zip` archives and folders (or,
for a soft patch, `.ips` / `.bps` / `.ups` files and `.zip` files holding exactly one). `.7z` and `.rar` are listed but
must be extracted first — the plugin only reads `.zip`. A relocated Downloads folder is not followed.

Before anything is written you see a preview: how many files, how big, where they go, and which existing files would be
replaced. Every name in the archive is checked first; an archive with an entry that would land outside the folder (an
absolute path, a drive letter, `..`, a link) is refused as a whole. If the archive's single top folder is the game's ID
folder (`GALE01\...`), its contents go straight into the game folder instead of a second `GALE01` inside it. PCSX2 packs
without a `replacements` folder are put in one.

Files that would be overwritten are moved to a backup folder first. If the file, the archive or the mod folder changes
between the preview and **Install**, the install is refused and you are shown the new preview.

### Removing

**Remove** (one entry) and **Remove All** (the game's whole folder) ask first, naming exactly what moves. Nothing is
deleted: it is moved to the backup folder, whose location the result message shows.

### Backups

Backups go to `romm-mod-backups\<date-time>\` inside the emulator's own folder — Dolphin's `User`, PPSSPP's `memstick`,
the PCSX2 folder, Azahar's `user`, or the RetroArch folder for soft patches. Delete them yourself when you no longer
need them.

### Turning texture packs on

When the setting above is off, the panel says _Texture packs are off in &lt;emulator&gt;_ with a **Turn On** button.
Close the emulator first: the plugin refuses while it is running. It copies the ini to the backup folder, then changes
that one line. If the ini has anything unusual in it (a section or key twice, a line it doesn't understand) the button
is not offered — change the setting in the emulator instead.

## Updates

This build updates itself from the fork's own releases; it is not on the Decky store. When a newer build is published
you get a toast when Steam starts, or within 6 hours while it runs: _Version 0.33.0-win.19 is available. Tap to
install._ The plugin looks for a new build at most once every 6 hours.

**Settings → Plugin Updates** shows the installed version, an **Install &lt;version&gt;** button with the release notes
when a newer build is out, and **Check for Updates** to look right now.

Installing (from the toast or the button):

1. Close any game you started from The Collector first. While one runs, the install is refused with a message saying so:
   Windows keeps the game launcher locked, and Decky cannot replace a locked file.
2. The plugin downloads the new build and checks it against the published size and SHA-256. If either differs, nothing
   is installed and you are told why — usually it means the build was published moments ago; try again in a few minutes.
3. It saves a copy of the version you have now.
4. Decky shows its own _update_ prompt. Confirm it and Decky replaces the plugin and reloads it. Cancel and nothing
   changes.

Your settings, library, saves and covers are not part of the plugin folder and are kept. The launcher's log,
`bin\rom-launcher.log`, starts again empty after an update.

**Roll Back to &lt;version&gt;** appears in the same section after an update and reinstalls the copy saved in step 3,
again through Decky's prompt. Only the most recent replaced version is kept. Rolling back across a release that changed
the plugin's database is not safe.

### If an update didn't finish

Decky can stop part-way through replacing the plugin's files — for example when one of them is locked by another program
— and leave a mix of old and new files behind. When that happens Decky's screen stays on _Installing_; restart Decky (or
the PC) to get out of it. The Collector checks its own files every time it starts:

- If the update was installed from the toast or **Settings → Plugin Updates**, the plugin still has the downloaded copy
  of that version and puts the missing files back by itself the next time it starts. Nothing needs doing. If it only
  notices once it is already running, the panel says _The Collector restored N files the last install didn't copy.
  Restart it to load them._ with a **Restart The Collector** button.
- Otherwise the top of its QAM panel says _Reinstall The Collector — the last install was cut short._, with a
  **Reinstall win.N** button. The button downloads that version again, checks it, and hands it to Decky's prompt; it
  works even when the rest of the plugin cannot start. If that version is not on the update channel (a test build you
  installed from a zip), the button says so: install the same zip again from Decky's Developer menu.

If files from an older version were left behind instead, the panel says so and offers the same button. The copy saved
for **Roll Back** is not replaced by a reinstall, and repairing never deletes anything.

### Installing from a zip

Decky's **Settings → Developer → Install plugin from ZIP** works for this build, with one difference from the update
button: Decky does not stop the running plugin first, it copies the new files over it (the plugin cannot see or delay
that install). From `0.33.0-win.25` the plugin keeps no file of its own folder open, so that copy goes through. Close
any game you started from The Collector first, because Windows keeps the game launcher locked while it runs. Installing
`win.25` or later over `win.24` or earlier can still stop at the very end — the older build holds one file open — and
leave Decky on _Installing_: restart Decky and the new build starts normally.

If your Decky Loader does not offer installing from plugins, the buttons are greyed out with a note, and no toast
appears; install the zip from the fork's `release` branch by hand (Decky settings → Developer → Install Plugin from
ZIP).

### The name

The plugin calls itself **The Collector**: its QAM header and its notifications use that name. Decky's own plugin list
and plugin settings still show **RomM-Dock**, the name Decky installed it under. Keeping that name is what keeps the
plugin's folder, so your shortcuts (and their playtime, collections and artwork), settings, RomM sign-in and save-sync
state all carry over untouched. Builds from `0.33.0-win.18` look for updates at `M2ljay/Eternal-Collector`; older builds
still find them at the repository's old name.

## Building the launcher

The launcher's source is in `native/rom-launcher-win/`. `native/rom-launcher-win/build.sh` runs its tests on the build
machine and cross-compiles it with Zig (`pip install ziglang`) into `bin/rom-launcher.exe` with a `.sha256` beside it.
