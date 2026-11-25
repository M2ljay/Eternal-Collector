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
`README.md` copied flat into the top folder, and `py_modules/` without bytecode caches; entries carry a fixed timestamp,
so an unchanged tree zips to the same SHA-256. With `RELEASE_CLONE` the files are copied into a local clone of the
`release` branch and `git add`ed. Publishing is committing and pushing that branch — a deliberate manual step.

## Layers

| Layer   | Module                                                                         | Owns                                                                        |
| ------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| Domain  | `domain/plugin_release.py`                                                     | Channel URLs, version order, `update.json` validation                       |
| Adapter | `adapters/plugin_release.py` (`PluginReleaseSource`)                           | HTTPS reads with the plugin's `romm-dock/<version>` User-Agent, size-capped |
| Adapter | `adapters/plugin_update_files.py` (`PluginUpdateFileStore`)                    | The staging folder: state record, download, snapshot zip, hashing           |
| Service | `services/plugin_update.py` (`PluginUpdateService`)                            | `check_plugin_update`, `prepare_plugin_update`, `get_plugin_rollback`       |
| UI      | `src/utils/pluginUpdate.ts`, `src/components/settings/PluginUpdateSection.tsx` | The toast, the hand-off to Decky's installer, the settings section          |

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

1. Re-read `update.json` (never a cached answer), and refuse with `up_to_date` unless it is newer.
2. Download `romm-dock.zip` into `<runtime>/plugin-update/download/`, reading at most `size + 1` bytes.
3. Refuse with `size_mismatch` or `hash_mismatch` — and delete the download — unless both match `update.json`.
4. Snapshot the installed plugin folder (without `__pycache__`, `.pyc` and `.log` files) to
   `<runtime>/plugin-update/previous/romm-dock-previous.zip`, recording its version and SHA-256 in `previous.json`. A
   snapshot that cannot be written refuses the update with `backup_failed`.
5. Return `{success: true, version, artifact: "file://<download>", sha256, size}`.

Only then does the frontend call the installer, with `install_type` `UPDATE` (2). Every refusal uses the canonical
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
