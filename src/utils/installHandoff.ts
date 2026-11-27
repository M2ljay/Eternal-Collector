/**
 * The one hand-off to Decky Loader's installer, shared by the update, reinstall and rollback paths.
 *
 * Decky v3.3.1 on Windows stops the backend with TerminateProcess (its `_unload`
 * never runs), deletes the plugin folder and extracts the zip over it; a file
 * still held open inside the folder stops either step half-way. So the backend
 * is asked first (`prepare_for_plugin_install`) to refuse while a game it
 * launched is running and to release its own handles there.
 * See docs/architecture/plugin-self-update.md#install-hand-off.
 */

import { logError, prepareForPluginInstall } from "../api/backend";
import { PLUGIN_NAME } from "./toast";

interface DeckyRouter {
  call<T = unknown>(route: string, ...args: unknown[]): Promise<T>;
}

/**
 * The loader's websocket router, as the loader's own store UI uses it. Not part of
 * `@decky/api`, so it may be absent on a loader build that renamed it.
 */
export function deckyRouter(): DeckyRouter | undefined {
  const be = (globalThis as unknown as { DeckyBackend?: DeckyRouter }).DeckyBackend;
  return typeof be?.call === "function" ? be : undefined;
}

export function canSelfUpdate(): boolean {
  return deckyRouter() !== undefined;
}

const NO_ROUTER = "This Decky Loader cannot install plugins from here.";

/** Hand a verified local build to Decky's installer. Returns "" once Decky has it, else why not. */
export async function requestDeckyInstall(
  artifact: string,
  version: string,
  sha256: string,
  installType: number,
): Promise<string> {
  const router = deckyRouter();
  if (!router) return NO_ROUTER;
  try {
    const ready = await prepareForPluginInstall();
    if (!ready.success) return ready.message;
  } catch (e) {
    logError(`prepareForPluginInstall failed: ${e}`);
    return "The plugin could not get ready for the install.";
  }
  try {
    // The name must be plugin.json's, or Decky installs a second copy beside this one.
    await router.call("utilities/install_plugin", artifact, PLUGIN_NAME, version, sha256, installType);
    return "";
  } catch (e) {
    return `Decky refused the install: ${String(e)}`;
  }
}

/**
 * Restart this plugin's backend and frontend through Decky's `loader/reload_plugin`
 * (the route behind "Reload" in Decky's plugin list, v3.3.1 `loader.py`), so files
 * the install check restored are loaded. Returns "" once Decky has the request, else why not.
 */
export async function reloadPlugin(): Promise<string> {
  const router = deckyRouter();
  if (!router) return "This Decky Loader cannot restart plugins from here.";
  try {
    await router.call("loader/reload_plugin", PLUGIN_NAME);
    return "";
  } catch (e) {
    return `Decky could not restart the plugin: ${String(e)}`;
  }
}
