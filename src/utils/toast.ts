import { toaster } from "@decky/api";
import type { ToastData, ToastNotification } from "@decky/api";
import type { ReactNode } from "react";

// Decky Loader's key for this plugin: must equal `plugin.json`'s `name`, which
// `utilities/install_plugin` looks the installed folder up by and the plugin list
// shows (decky-loader v3.3.1 browser.py `find_plugin_folder`, plugin-loader.tsx
// overwrites `definePlugin`'s `name` with it). Changing it is a rename in Decky,
// not a label change: docs/architecture/plugin-self-update.md#plugin-name.
export const PLUGIN_NAME = "RomM-Dock";

/** The name the plugin shows for itself: the QAM header (`titleView`) and every toast. */
export const PLUGIN_DISPLAY_NAME = "The Collector";

/**
 * Raise a toast under the plugin's display name.
 *
 * *options* passes through to `toaster.toast` and may override the title, which
 * no call site currently needs: every notice comes from the same plugin, so a
 * second sender would only make the user work out that they are the same thing.
 */
export function showToast(body: ReactNode, options?: Partial<Omit<ToastData, "body">>): ToastNotification {
  return toaster.toast({ title: PLUGIN_DISPLAY_NAME, body, ...options });
}
