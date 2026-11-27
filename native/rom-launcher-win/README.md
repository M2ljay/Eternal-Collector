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
white render window nor an emulator's menu window flashes up. It comes back when the game's fullscreen window closes
while the emulator is still shutting down, and stays until Big Picture is in front again. It never takes focus, passes
clicks through, and lifts after 8 s at launch or 4 s after the game left fullscreen without quitting.

It is the process Steam starts and tracks, and it lives exactly as long as anything in its job object does: an emulator
that hands off to another process keeps the game running in Steam, and nothing outlives the launcher (the job is
kill-on-close). A close request — Steam's Exit Game reaching it as `WM_CLOSE` on its hidden host window or the curtain,
or the session ending — is passed on as `WM_CLOSE` to the emulator's windows; whatever is still running after
`LP_CLOSE_GRACE_MS` (10 s) is ended with the job. The decision is in [`launch_policy.h`](launch_policy.h), tested on the
build host with the command-line handling.

Differences from the original: it links Windows' own C runtime (present on Windows 10 and 11) and embeds the curtain
logo, so it is about 1.1 MB instead of 12 KB.
