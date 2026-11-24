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

## Building the launcher

The launcher's source is in `native/rom-launcher-win/`. `native/rom-launcher-win/build.sh` runs its tests on the build
machine and cross-compiles it with Zig (`pip install ziglang`) into `bin/rom-launcher.exe` with a `.sha256` beside it.
