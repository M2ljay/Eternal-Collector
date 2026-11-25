#!/usr/bin/env bash
# Package a Windows fork build for the plugin's self-update channel.
#
# Usage:
#   scripts/make_release.sh OUT_DIR [NOTES] [RELEASE_CLONE]
#
# Writes OUT_DIR/romm-dock-<version>.zip and OUT_DIR/update.json. With
# RELEASE_CLONE (a local clone of the `release` branch) it also copies them in
# as romm-dock.zip + update.json and `git add`s both. Committing and pushing the
# release branch stays a separate, manual step: that push is the publish.
#
# The zip is the layout Decky installs — one top folder `romm-dock/` holding
# main.py, plugin.json, package.json, LICENSE, README.md, dist/index.js, bin/'s
# launcher files, every file of defaults/ except README.md copied flat into the
# top folder (as the Decky CLI does), py_modules/ without bytecode caches, and
# install-manifest.json listing the path, size and SHA-256 of every other file.
# Entries carry a fixed timestamp so an unchanged tree zips byte-identically.
#
# SKIP_BUILD=1 reuses an existing dist/index.js instead of running `pnpm build`.
# See docs/architecture/plugin-self-update.md for the channel this feeds.
set -euo pipefail

OUT=${1:?usage: make_release.sh OUT_DIR [NOTES] [RELEASE_CLONE]}
NOTES=${2:-}
CLONE=${3:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)

VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$HERE/package.json")
MANIFEST_VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$HERE/plugin.json")
if [[ ! $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+-win\.[0-9]+$ ]]; then
  echo "package.json version '$VERSION' is not a fork build (X.Y.Z-win.N)" >&2
  exit 1
fi
if [[ $VERSION != "$MANIFEST_VERSION" ]]; then
  echo "package.json ($VERSION) and plugin.json ($MANIFEST_VERSION) disagree" >&2
  exit 1
fi

if [[ ${SKIP_BUILD:-} != 1 ]]; then
  (cd "$HERE" && pnpm build)
fi
[[ -f $HERE/dist/index.js ]] || { echo "dist/index.js is missing; run pnpm build" >&2; exit 1; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
ZIP="$OUT/romm-dock-$VERSION.zip"

python3 - "$HERE" "$ZIP" <<'PY'
import hashlib
import json
import os
import sys
import zipfile

here, dest = sys.argv[1:3]
top = "romm-dock"
stamp = (2026, 1, 1, 0, 0, 0)
entries = []  # (archive name, source path)

for name in ("main.py", "plugin.json", "package.json", "LICENSE", "README.md"):
    entries.append((name, os.path.join(here, name)))
entries.append(("dist/index.js", os.path.join(here, "dist", "index.js")))
for name in ("rom-launcher", "rom-launcher.exe", "rom-launcher.exe.sha256"):
    entries.append((f"bin/{name}", os.path.join(here, "bin", name)))
defaults = os.path.join(here, "defaults")
for name in sorted(os.listdir(defaults)):
    path = os.path.join(defaults, name)
    if name != "README.md" and os.path.isfile(path):
        entries.append((name, path))
py_modules = os.path.join(here, "py_modules")
for root, dirs, files in os.walk(py_modules):
    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
    for name in sorted(files):
        if name.endswith((".pyc", ".pyo")):
            continue
        path = os.path.join(root, name)
        rel = os.path.relpath(path, here).replace(os.sep, "/")
        entries.append((rel, path))

names = [n for n, _ in entries]
dupes = {n for n in names if names.count(n) > 1}
if dupes:
    sys.exit(f"duplicate entries in the release zip: {sorted(dupes)}")
missing = [p for _, p in entries if not os.path.isfile(p)]
if missing:
    sys.exit(f"missing release files: {missing}")

# install-manifest.json: path, size and SHA-256 of every other file, checked by
# the plugin at start (domain/install_manifest.py) to catch a half-copied install.
sys.path.insert(0, os.path.join(here, "py_modules"))
from domain.install_manifest import MANIFEST_FORMAT, MANIFEST_NAME  # noqa: E402 - the format the plugin reads

if MANIFEST_NAME in names:
    sys.exit(f"{MANIFEST_NAME} must not be a source file")
version = json.load(open(os.path.join(here, "package.json"), encoding="utf-8"))["version"]
files = []
for name, path in sorted(entries):
    with open(path, "rb") as f:
        data = f.read()
    files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
manifest = json.dumps({"format": MANIFEST_FORMAT, "version": version, "files": files}, indent=1).encode() + b"\n"

tmp = dest + ".part"
with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    blobs = [(name, path, None) for name, path in entries] + [(MANIFEST_NAME, None, manifest)]
    for name, path, blob in sorted(blobs, key=lambda e: e[0]):
        info = zipfile.ZipInfo(f"{top}/{name}", date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        mode = 0o755 if path is not None and os.access(path, os.X_OK) else 0o644
        info.external_attr = mode << 16
        if blob is None:
            with open(path, "rb") as f:
                blob = f.read()
        zf.writestr(info, blob)
os.replace(tmp, dest)
print(f"{len(entries)} files + {MANIFEST_NAME}")
PY

SHA=$(sha256sum "$ZIP" | cut -d' ' -f1)
SIZE=$(stat -c %s "$ZIP" 2>/dev/null || stat -f %z "$ZIP")
python3 - "$HERE" "$OUT/update.json" "$VERSION" "$SHA" "$SIZE" "$NOTES" <<'PY'
import json
import os
import sys

here, path, version, sha, size, notes = sys.argv[1:7]
sys.path.insert(0, os.path.join(here, "py_modules"))
from domain.plugin_release import PUBLISHED_ARTIFACT_URL  # noqa: E402 - the URL every installed build accepts
with open(path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "version": version,
            "sha256": sha,
            "size": int(size),
            "notes": notes,
            "url": PUBLISHED_ARTIFACT_URL,
        },
        f,
        indent=1,
    )
    f.write("\n")
PY

echo "$VERSION $SHA $SIZE"
echo "  $ZIP"
echo "  $OUT/update.json"

if [[ -n $CLONE ]]; then
  [[ -d $CLONE/.git ]] || { echo "$CLONE is not a git clone" >&2; exit 1; }
  cp "$ZIP" "$CLONE/romm-dock.zip"
  cp "$OUT/update.json" "$CLONE/update.json"
  git -C "$CLONE" add romm-dock.zip update.json
  echo "Staged in $CLONE. To publish: git -C \"$CLONE\" commit -m \"$VERSION\" && git -C \"$CLONE\" push origin release"
fi
