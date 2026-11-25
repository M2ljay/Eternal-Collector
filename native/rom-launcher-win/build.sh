#!/usr/bin/env bash
# Tests the launcher's text handling on this host, then cross-compiles
# rom-launcher.exe for 64-bit Windows with Zig (`pip install ziglang`, or a
# `zig` on PATH) and writes bin/rom-launcher.exe(.sha256).
#
#   native/rom-launcher-win/build.sh            # test + build into bin/
#   OUT=/tmp/x.exe native/rom-launcher-win/build.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
out="${OUT:-$root/bin/rom-launcher.exe}"
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac

if command -v zig >/dev/null 2>&1; then zig=(zig); else zig=(python3 -m ziglang); fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cc="${CC:-cc}"
"$cc" -std=c11 -Wall -Wextra -Werror -o "$tmp/test" "$here/test_launch_command.c"
"$tmp/test"

"${zig[@]}" cc -target x86_64-windows-gnu -Os -s -std=c11 -Wall -Wextra -Werror \
    -Wl,--subsystem,windows \
    -o "$tmp/rom-launcher.exe" "$here/rom-launcher.c" "$here/rom-launcher.rc" -lkernel32 -luser32 -lgdi32

mkdir -p "$(dirname "$out")"
cp "$tmp/rom-launcher.exe" "$out"
(cd "$(dirname "$out")" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")
echo "built $out ($(wc -c < "$out") bytes)"
