# rom-launcher (Windows)

Source of `bin/rom-launcher.exe`, the program every RomM shortcut runs on Windows. What it does and its exit codes are
described at the top of [`rom-launcher.c`](rom-launcher.c); the command-line handling lives in
[`launch_command.h`](launch_command.h) with host-side tests in [`test_launch_command.c`](test_launch_command.c), built
from real launches in `rom-launcher.log`.

Build: `native/rom-launcher-win/build.sh` (tests, then cross-compiles with Zig; `OUT=<path>` writes elsewhere).

## Status

The original exe's source was lost; this is a rewrite from its behaviour (its log output, its imported Windows calls,
and the command lines the plugin bakes). It replaced the original in 0.33.0-win.19 after testing on the user's PC
(2026-11-25): a PS2 game (PCSX2, CHD), GameCube and Wii games (Dolphin), launching and quitting, and Big Picture
regaining focus.

It adds a **launch curtain**: the Core mark on AMOLED black (`curtain-logo.bmp`, embedded by `rom-launcher.rc`), kept
topmost from launch until the emulator's fullscreen window has been frontmost for 0.8 s, so neither Dolphin's unpainted
white render window nor an emulator's menu window flashes up. It never takes focus, passes clicks through, and lifts
when the emulator exits or after 8 s.

Differences from the original: it links Windows' own C runtime (present on Windows 10 and 11) and embeds the curtain
logo, so it is about 1.1 MB instead of 12 KB.
