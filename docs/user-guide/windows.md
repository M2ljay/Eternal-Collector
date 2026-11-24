# Windows (EmuDeck)

This fork's `windows` branch runs RomM-Dock on a Windows PC, inside Steam Big Picture with Decky Loader for Windows
(Playhub), launching games through EmuDeck for Windows instead of RetroDECK.

## What differs from the Steam Deck build

- **Launcher.** Shortcuts run `bin\rom-launcher.exe`. It starts the emulator EmuDeck uses for the system directly (not
  through EmuDeck's PowerShell launcher scripts, which run a `git pull` and EmuDeck Cloud Sync on every launch), stops
  the emulator when you stop the game in Steam, and brings Big Picture back to the front when the emulator exits. Each
  launch is logged to `bin\rom-launcher.log`.
- **PS Vita.** A downloaded Vita game is linked into Vita3K's `ux0/app/<TITLE_ID>` and launched by title ID.
- **Game page.** On Windows the Play, Install and menu buttons use Steam's own button styles, so they follow your Steam
  theme.
- **Collections.** Platform collections use the plain platform name (`Nintendo 64`) and RomM collections use
  `[Collection name]`, instead of `RomM: Nintendo 64 (host)`. Older-style collections that hold only RomM games are
  removed once their new-style replacement exists.
- **Wording.** Setup and health messages name EmuDeck instead of RetroDECK, and BIOS deletion refers to your BIOS
  folder.
- **Logos.** A logo downloaded for a RomM game gets Steam's default bottom-left placement once, so it shows on the game
  page; a position you set later in Steam is kept.

## Save sync

Games that launch with a RetroArch core sync their saves exactly as on the Steam Deck, from EmuDeck's
`saves\retroarch\saves` folder. Games that launch with one of these standalone emulators sync that emulator's saves
instead, from the folders EmuDeck keeps under its saves folder (`C:\Emulation\saves\` by default — the plugin reads the
real location from EmuDeck's settings):

| Emulator    | Folder                                 | What syncs for a ROM named `<game>`           |
| ----------- | -------------------------------------- | --------------------------------------------- |
| melonDS     | `C:\Emulation\saves\melonds\saves`     | `<game>.sav`                                  |
| DuckStation | `C:\Emulation\saves\duckstation\saves` | `<game>_1.mcd` and `<game>_2.mcd`             |
| Vita3K      | `C:\Emulation\saves\Vita3K\saves`      | the `<TITLE_ID>` folder of the installed game |

Which emulator counts is the one the game actually launches with — your per-game or per-platform choice, else EmuDeck's
default. A PlayStation game you launch with a RetroArch core keeps syncing RetroArch's save. Each emulator's saves are
stored on RomM under that emulator's name (`melonds`, `duckstation`, `vita3k`), so saves from different emulators never
overwrite each other. Only files positively identified as the game's are read or written; save states are not synced.

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

Removing a game from your library does not touch these standalone save folders.

## Building the launcher

The launcher's source is in `native/rom-launcher-win/`. `native/rom-launcher-win/build.sh` runs its tests on the build
machine and cross-compiles it with Zig (`pip install ziglang`) into `bin/rom-launcher.exe` with a `.sha256` beside it.
