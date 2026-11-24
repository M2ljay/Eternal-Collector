# rom-launcher (Windows)

Source of `bin/rom-launcher.exe`, the program every RomM shortcut runs on Windows. What it does and its exit codes are
described at the top of [`rom-launcher.c`](rom-launcher.c); the command-line handling lives in
[`launch_command.h`](launch_command.h) with host-side tests in [`test_launch_command.c`](test_launch_command.c), built
from real launches in `rom-launcher.log`.

Build: `native/rom-launcher-win/build.sh` (tests, then cross-compiles with Zig; `OUT=<path>` writes elsewhere).

## Status

The original exe's source was lost; this is a rewrite from its behaviour (its log output, its imported Windows calls,
and the command lines the plugin bakes). The command-line handling is tested here; the Windows half (starting the
process, the job object, refocusing Big Picture) has **not yet been run on a PC**.

Until it has, `bin/rom-launcher.exe` is still the original build (SHA-256 in `bin/rom-launcher.exe.sha256`). To switch,
run `build.sh`, which overwrites both, and test at least one RetroArch core, one standalone emulator, a PS Vita title
(`--title-id-file`), and Steam's "Stop game".

Known differences from the original: the rebuild links Windows' own C runtime (present on Windows 10 and 11), so it is
about 64 KB instead of 12 KB.
