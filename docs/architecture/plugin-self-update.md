# Plugin Self-Update (Windows fork build)

The Windows fork build updates itself from the fork's own release channel instead of the Decky store. User-facing
behaviour is in [the Windows guide](../user-guide/windows.md#updates); this page is how it is built and the rules it
holds.

## Why a separate channel

The fork's builds are versioned `X.Y.Z-win.N` (`0.33.0-win.17`) and are published nowhere Decky looks. Every other build
of the plugin — any Linux build, any version without the `-win.N` counter — answers `supported: false` from all three
callables, renders no settings section and never toasts, so the store/manual-install flow those builds use is unchanged.

## Release channel

A `release` branch on `M2ljay/Eternal-Collector` (named `M2ljay/Eternal-Romm` before a GitHub rename) holds two files,
read over `raw.githubusercontent.com`:

| File            | Content                                                                            |
| --------------- | ---------------------------------------------------------------------------------- |
| `romm-dock.zip` | The build, in the layout Decky installs (one top folder `romm-dock/`)              |
| `update.json`   | `{"version", "sha256", "size", "notes", "url"}` — `url` is the `romm-dock.zip` URL |

`domain/plugin_release.py` owns the URLs and the validation: `version` must parse as `X.Y.Z` or `X.Y.Z-win.N`, `sha256`
must be 64 lower-case hex digits, `size` a positive integer no larger than 64 MiB, and `url` must equal the channel's
own zip URL under the repository's current or legacy name (`ACCEPTED_ARTIFACT_URLS`) — anything else is
`manifest_invalid` and nothing is fetched. Versions compare as integer tuples `(X, Y, Z,
N)` (a version without `-win.N`
has `N = 0`), so `win.10` is newer than `win.9`; equal, older or unreadable is never an update.

### The repository rename

`raw.githubusercontent.com` still serves the branch under the old name, and builds up to `0.33.0-win.17` read
`update.json` from `M2ljay/Eternal-Romm` and accept only `…/M2ljay/Eternal-Romm/release/romm-dock.zip` as its `url`.
Newer builds read `update.json` from `M2ljay/Eternal-Collector` and accept the zip URL under either name. One
`update.json` serves both, so `make_release.sh` writes `PUBLISHED_ARTIFACT_URL`, which is the legacy URL; it can move to
the new one once no build older than `0.33.0-win.18` is installed. If GitHub stops serving the old name (a new
repository created as `M2ljay/Eternal-Romm` takes it over), the old builds stop seeing updates and need one manual
install.

### Packaging

`scripts/make_release.sh OUT_DIR [NOTES] [RELEASE_CLONE]` builds both files (running `pnpm build` unless
`SKIP_BUILD=1`). The zip holds `main.py`, `plugin.json`, `package.json`, `LICENSE`, `README.md`, `dist/index.js`,
`bin/rom-launcher`, `bin/rom-launcher.exe`, `bin/rom-launcher.exe.sha256`, every file of `defaults/` except its
`README.md` copied flat into the top folder, `py_modules/` without bytecode caches, and `install-manifest.json` — the
path, size and SHA-256 of every other file in the zip (see [Half-copied installs](#half-copied-installs)); entries
carry a fixed timestamp, so an unchanged tree zips to the same SHA-256. With `RELEASE_CLONE` the files are copied into a local clone of the
`release` branch and `git add`ed. Publishing is committing and pushing that branch — a deliberate manual step.

## Layers

| Layer   | Module                                                                         | Owns                                                                                              |
| ------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Domain  | `domain/plugin_release.py`                                                     | Channel URLs, version order, `update.json` validation                                             |
| Domain  | `domain/install_manifest.py`                                                   | `install-manifest.json` format, the size and hash verdicts                                        |
| Adapter | `adapters/plugin_release.py` (`PluginReleaseSource`)                           | HTTPS reads with the plugin's `romm-dock/<version>` User-Agent, size-capped                       |
| Adapter | `adapters/plugin_update_files.py` (`PluginUpdateFileStore`)                    | The staging folder: state record, download, snapshot zip, hashing                                 |
| Adapter | `adapters/install_files.py` (`InstallFileScanner`)                             | Stat, list and hash the installed plugin folder (stdlib only)                                     |
| Adapter | `adapters/plugin_folder_handles.py` (`PluginFolderHandles`)                    | Handles the backend holds inside its own folder, released before hand-off                         |
| Service | `services/plugin_update.py` (`PluginUpdateService`)                            | `check_plugin_update`, `prepare_plugin_update`, `prepare_plugin_reinstall`, `get_plugin_rollback` |
| Service | `services/install_integrity.py` (`InstallIntegrityService`)                    | `get_install_integrity`                                                                           |
| Wiring  | `core_bootstrap.py`                                                            | Builds the two services above, before and apart from `bootstrap/`                                 |
| UI      | `src/utils/pluginUpdate.ts`, `src/components/settings/PluginUpdateSection.tsx` | The toast, the hand-off to Decky's installer, the settings section                                |
| UI      | `src/components/InstallIntegrityNotice.tsx`                                    | The QAM notice and its **Reinstall** button                                                       |

Both services are wired by `core_bootstrap.py`, not `bootstrap/`: importing anything in the `bootstrap` package imports
every adapter and service, so one missing module stops all of it, and these two must work in exactly that state.
`main.py` imports `core_bootstrap` before anything else and builds it first in `_main`.

The service is enabled only when `sys.platform == "win32"` and the running version is a `-win.N` build.

## Check

`check_plugin_update(force)` reads `update.json` at most once every 6 hours; the answer and its time are kept in
`<runtime>/plugin-update/state.json`, so a plugin restart does not re-read the channel. `force` (the **Check for
Updates** button) reads it now. The frontend asks once when the plugin loads and again every 6 hours while Steam runs,
and toasts a newer version once per session; a failed check is silent apart from the log.

## Install — Decky Loader's own installer

The plugin cannot replace its own folder safely while it runs. Decky Loader can: its websocket router exposes
`utilities/install_plugin(artifact, name, version, hash, install_type)`, the route its store uses
(`backend/decky_loader/utilities.py`). The loader shows its confirmation prompt, reads the artifact (`file://` paths are
opened directly), refuses it when its SHA-256 differs from `hash`, uninstalls the old folder, extracts the zip into the
plugins folder and reloads the plugin (`PluginBrowser._install`, `backend/decky_loader/browser.py`). `name` must be
`plugin.json`'s (`RomM-Dock`) — see [Plugin name](#plugin-name). The router is reached as `window.DeckyBackend`, which
is not part of `@decky/api`; when it is absent the install buttons are disabled and no toast is shown.

`prepare_plugin_update` runs before that hand-off:

1. Refuse with `game_running` while a game the plugin launched is running: Windows keeps `bin\rom-launcher.exe` locked
   for as long as it runs, and a locked file makes Decky's installer stop halfway (see
   [Half-copied installs](#half-copied-installs)). Checked by executable name in the process table; a table that cannot
   be read does not block.
2. Re-read `update.json` (never a cached answer), and refuse with `up_to_date` unless it is newer.
3. Download `romm-dock.zip` into `<runtime>/plugin-update/download/`, reading at most `size + 1` bytes.
4. Refuse with `size_mismatch` or `hash_mismatch` — and delete the download — unless both match `update.json`.
5. Snapshot the installed plugin folder (without `__pycache__`, `.pyc` and `.log` files) to
   `<runtime>/plugin-update/previous/romm-dock-previous.zip`, recording its version and SHA-256 in `previous.json`. A
   snapshot that cannot be written refuses the update with `backup_failed`.
6. Check for a running game again (the download can take a while), then release every handle the backend holds inside
   its own folder (`PluginFolderHandles.release_all`): today that is the gavel native core,
   `py_modules/native/gavel-x86_64-windows.dll`, which `ctypes` keeps mapped. Each holder reopens on its next use, so
   cancelling Decky's prompt leaves the plugin working.
7. Return `{success: true, version, artifact: "file://<download>", sha256, size, install_type}`.

Only then does the frontend call the installer, with the returned `install_type` (`UPDATE`, 2). Every refusal uses the canonical
`{success: false, reason, message}` shape; transport failures are `server_unreachable`.

The file the installer reads is the file that was verified, and the loader checks the same SHA-256 again before
extracting. Handing the loader the `raw.githubusercontent.com` URL instead would download a second time with no size
check, and the loader's store-install path would also post an install count to the Decky store under the upstream
plugin's name.

## Rollback

`get_plugin_rollback` offers the snapshot when it exists, its version is not the running one, and its file still has the
recorded SHA-256. **Roll Back** hands it to the same installer with `install_type` `DOWNGRADE` (3). One snapshot is
kept; each update replaces it with the build being replaced.

A rollback restores the plugin's code only. Settings, the SQLite database and the cover cache live in Decky's settings
and runtime folders and are not touched by either direction. The migration runner (`adapters/sqlite_migrations.py`) only
applies migrations newer than the database's `user_version` and never checks for a schema newer than it knows, so an
older build starts against the newer schema unchecked: rolling back across a release that added a migration is not safe.

## Half-copied installs

On Windows, installing `0.33.0-win.18` over a running `win.15` left a folder in which the top-level files and `bin\`
were new, `py_modules\` was partly old and `services\game_mods.py` was missing, so the plugin failed to import; a
second install, with the plugin no longer running, worked. Decky Loader v3.3.1's installer explains the shape
(`SteamDeckHomebrew/decky-loader`, tag `v3.3.1`, `backend/decky_loader/`):

| Step                                   | What v3.3.1 does                                                                                                                                                                                                                                                      | Where                                                                                |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Stop the plugin                        | `uninstall_plugin` calls `PluginWrapper.stop(uninstall=True)` before deleting: `terminate()` (on Windows `multiprocessing` `TerminateProcess`, so the plugin's `_unload` never runs — the SIGTERM handler is Linux-only), then polls `is_alive()` and kills after 5 s | `browser.py` 154-159; `plugin/plugin.py` 147-191; `plugin/sandboxed_plugin.py` 65-67 |
| Delete the old folder                  | `shutil.rmtree(plugin_dir)` with no error handler. Python 3.14 (the bundle's, `.github/workflows/build.yml` 56) walks bottom-up and raises on the first file it cannot delete                                                                                         | `browser.py` 163                                                                     |
| A delete fails                         | `except Exception` logs "was not uninstalled" and **continues**: whatever the walk had not reached yet stays on disk                                                                                                                                                  | `browser.py` 166-168                                                                 |
| Extract                                | `ZipFile.extractall(plugin_path)` over what is left, in zip order (`make_release.sh` writes it sorted)                                                                                                                                                                | `browser.py` 58-64, 277                                                              |
| An extract fails                       | Nothing catches it: a `PermissionError` on a locked file leaves every later entry unwritten, the plugin is not re-imported (296), the file watcher stays disabled (305) and `loader/plugin_download_finish` is never sent                                             | `browser.py` 274-307                                                                 |
| A file left behind by an older version | Stays, unless the delete reached it: a delete that finishes leaves nothing; one that fails leaves the rest                                                                                                                                                            | `browser.py` 163-168                                                                 |

So one locked file is enough: the delete stops at it, the extract stops at it, and everything sorted after it is old or
missing. In the reported case that fits a lock on `py_modules\native\gavel-x86_64-windows.dll` (`native` sorts before
`services`). Which process held it is not visible from the source: the plugin process itself is terminated and waited
for first, and the `multiprocessing` child of Decky's onefile PyInstaller bundle is the interpreter itself (PyInstaller
6.22.3 `bootloader/src/pyi_main.c`: a spawned subprocess runs Python directly, it does not fork a second child). A game
running from `bin\rom-launcher.exe` certainly holds one; an antivirus scan or a file manager window can hold others.

The plugin cannot change Decky's installer, so it does three things:

- **Before**: refuses to prepare an update while `rom-launcher.exe` runs, and releases its own handles inside the
  folder (step 6 above).
- **After**: checks its folder against `install-manifest.json` at every start. `InstallIntegrityService` runs the size
  pass in `_main` (stat calls only, before anything else) and the hash pass once, in an executor. `missing` or
  `mismatched` files make the install `incomplete`; `.py` files under `py_modules/` the manifest does not list —
  leftovers of an older build, such as `services/downloads.py` beside the `services/downloads/` package — make it
  `stale_files`, and those beside a package of the same name are listed as `shadowing`. A missing manifest (a
  development install) is `unchecked`; an unreadable one is `incomplete`.
- **Rescue mode**: `main.py` imports `core_bootstrap` first and the rest of the plugin inside a `try`. If that fails,
  `FULL_IMPORT_ERROR` holds the traceback, the `Plugin` class still defines (its gate decorators fall back to
  pass-throughs), and `_main` builds only the core: `get_install_integrity` answers `incomplete` with the import error
  attached, and `check_plugin_update` / `prepare_plugin_reinstall` work. Every other callable fails, as it would if
  `_main` had failed.

The QAM shows `InstallIntegrityNotice` above every page for `incomplete` ("The Collector's last update didn't finish
copying. Reinstall win.N") and `stale_files`. Its **Reinstall** button calls `prepare_plugin_reinstall`, which is
`prepare_plugin_update` with two differences: the published build may be the running version (Decky's `REINSTALL`, 1)
as well as a newer one (`UPDATE`), and the installed folder is **not** snapshotted — a broken copy must not replace the
rollback build. An older published build is refused with `channel_older`. Decky's reinstall deletes the folder first,
which also removes stale files, so the plugin never deletes files from its own folder itself.

The modules the core imports at module level (`core_bootstrap.py`, `domain/install_manifest.py`,
`adapters/install_files.py`, `services/install_integrity.py`) import the standard library and each other only. The
update half is imported inside `build_core` and degrades to `None` when it cannot load.
`tests/test_core_bootstrap.py` checks those imports by AST; `tests/test_plugin_rescue_mode.py` deletes `services/game_mods.py` from a copy of the plugin and checks the notice's
answer; `tests/runtime/test_frozen_runtime.py` imports all of it against Decky's frozen standard library.

## What an update does not keep

Decky deletes the installed folder before extracting the new one, so anything the plugin wrote inside its own folder is
lost: on Windows that is `bin\rom-launcher.log`. Nothing else is written there.

## Plugin name

The plugin shows itself as **The Collector** but is still `RomM-Dock` to Decky Loader. The two are separate on purpose,
read from Decky Loader v3.3.1 (`SteamDeckHomebrew/decky-loader`, tag `v3.3.1`):

| What                                                    | Keyed by                                          | Where (v3.3.1)                                                    |
| ------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| Install folder (`plugins/romm-dock`)                    | the zip's top folder                              | `browser.py` `_unzip_to_plugin_dir` → `ZipFile.extractall`        |
| Settings, runtime and log folders, `DECKY_PLUGIN_DIR`   | the install folder's name                         | `plugin/sandboxed_plugin.py` (`DECKY_PLUGIN_SETTINGS_DIR` et al.) |
| Update vs new install, which folder is uninstalled      | `plugin.json` `name`                              | `browser.py` `find_plugin_folder`, `_install`, `uninstall_plugin` |
| Callable routing, plugin order, hidden/disabled lists   | `plugin.json` `name`                              | `loader.py` `self.plugins[plugin.name]`, `browser.py`             |
| Name in the QAM plugin list and Decky's plugin settings | `plugin.json` `name`                              | `frontend/src/plugin-loader.tsx` overwrites `definePlugin`'s name |
| QAM header while the plugin is open                     | the plugin's `titleView`, else `plugin.json` name | `frontend/src/components/TitleView.tsx`                           |
| Toasts                                                  | the title the plugin passes                       | `src/utils/toast.ts` `PLUGIN_DISPLAY_NAME`                        |

The install folder must not change: every shortcut's exe is `<DECKY_PLUGIN_DIR>\bin\rom-launcher.exe`
(`domain/shortcut_data.py`), and an exe change is applied by deleting and recreating the shortcut, which assigns a new
appId ([Steam shortcuts](steam-non-steam-shortcuts.md)). The settings (RomM connection included), database and save-sync
state live in folders named after it too. So the zip's top folder stays `romm-dock/`.

`plugin.json` `name` is what the Decky plugin list shows, so the list still says `RomM-Dock`. Changing it is a rename
inside Decky, and v3.3.1's installer cannot carry one through an update: `_install(name)` looks the installed folder up
by `name` both before uninstalling and after extracting. Passed the old name, it uninstalls and extracts correctly, then
fails its `assert plugin_folder is not None` and leaves the plugin unloaded until Decky restarts. Passed the new name,
it finds nothing to uninstall, extracts over the running plugin's folder and starts a second instance beside the old one
on the same database. Neither touches the settings or data folders, and the folder stays `romm-dock` either way. The
rename is therefore left out of the self-update channel: done at all, it is a build installed while Decky is told to
restart straight after, and Decky's plugin order, hidden and disabled entries for `RomM-Dock` do not carry over.
