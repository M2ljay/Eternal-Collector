/**
 * Plugin self-update for the Windows fork build.
 *
 * The backend reads the fork's release channel, downloads a newer build into the
 * plugin's runtime folder and refuses it unless its size and SHA-256 match the
 * published `update.json`. The install itself is Decky Loader's own: the verified
 * file is handed to the loader's `utilities/install_plugin` route, which shows its
 * confirmation prompt, checks the SHA-256 again, replaces the plugin folder and
 * reloads the plugin. The same route reinstalls the build kept from before the
 * last update. See docs/architecture/plugin-self-update.md.
 */

import {
  checkPluginUpdate,
  getPluginRollback,
  logError,
  preparePluginUpdate,
  type PluginUpdateCheck,
} from "../api/backend";
import { detach } from "./detach";
import { PLUGIN_NAME, showToast } from "./toast";

/** Decky Loader's `PluginInstallType` (backend/decky_loader/browser.py); the prompt words itself from it. */
export const DECKY_INSTALL_TYPE_UPDATE = 2;
export const DECKY_INSTALL_TYPE_DOWNGRADE = 3;

/** How often a running Steam session re-asks the backend; the backend itself reads the channel at most this often. */
export const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

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

/** Hand a verified local build to Decky's installer. Returns "" once Decky has it, else why not. */
export async function requestDeckyInstall(
  artifact: string,
  version: string,
  sha256: string,
  installType: number,
): Promise<string> {
  const router = deckyRouter();
  if (!router) return "This Decky Loader cannot install plugins from here.";
  try {
    // The name must be plugin.json's, or Decky installs a second copy beside this one.
    await router.call("utilities/install_plugin", artifact, PLUGIN_NAME, version, sha256, installType);
    return "";
  } catch (e) {
    return `Decky refused the install: ${String(e)}`;
  }
}

/** Download, verify and hand the newest build to Decky. Returns "" on hand-off, else the reason. */
export async function installPluginUpdate(): Promise<string> {
  if (!canSelfUpdate()) return "This Decky Loader cannot install plugins from here.";
  try {
    const prepared = await preparePluginUpdate();
    if (!prepared.success) return prepared.message;
    return await requestDeckyInstall(prepared.artifact, prepared.version, prepared.sha256, DECKY_INSTALL_TYPE_UPDATE);
  } catch (e) {
    logError(`installPluginUpdate failed: ${e}`);
    return "The update could not be prepared.";
  }
}

/** Reinstall the build kept from before the last update. Returns "" on hand-off, else the reason. */
export async function rollbackPlugin(): Promise<string> {
  if (!canSelfUpdate()) return "This Decky Loader cannot install plugins from here.";
  try {
    const kept = await getPluginRollback();
    if (!kept.available) return "No earlier build is kept.";
    return await requestDeckyInstall(kept.artifact, kept.version, kept.sha256, DECKY_INSTALL_TYPE_DOWNGRADE);
  } catch (e) {
    logError(`rollbackPlugin failed: ${e}`);
    return "The earlier build could not be read.";
  }
}

export function updateOffered(check: PluginUpdateCheck | null | undefined): check is PluginUpdateCheck & {
  success: true;
  version: string;
} {
  return !!check?.success && check.supported && check.update_available && !!check.version;
}

let lastToastedVersion: string | null = null;

/** Test seam: forget which version was already announced this session. */
export function resetPluginUpdateToastMemory(): void {
  lastToastedVersion = null;
}

/**
 * Ask the backend (which answers from its throttled cache unless forced) and toast
 * once per version per session. Tapping the toast starts the install; Decky's own
 * prompt still asks before anything changes.
 */
export async function notifyIfPluginUpdate(): Promise<void> {
  if (!canSelfUpdate()) return;
  let check: PluginUpdateCheck;
  try {
    check = await checkPluginUpdate(false);
  } catch (e) {
    logError(`checkPluginUpdate failed: ${e}`);
    return;
  }
  if (!updateOffered(check) || check.version === lastToastedVersion) return;
  lastToastedVersion = check.version;
  showToast(`Version ${check.version} is available. Tap to install.`, {
    duration: 10_000,
    onClick: () => {
      detach(
        installPluginUpdate().then((err) => {
          if (err) showToast(err);
        }),
      );
    },
  });
}

/** Check now and every UPDATE_CHECK_INTERVAL_MS; returns the stop function for onDismount. */
export function startPluginUpdateWatch(): () => void {
  detach(notifyIfPluginUpdate());
  const timer = setInterval(() => detach(notifyIfPluginUpdate()), UPDATE_CHECK_INTERVAL_MS);
  return () => clearInterval(timer);
}
