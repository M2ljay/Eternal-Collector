import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as backend from "../api/backend";
import { canSelfUpdate, reloadPlugin, requestDeckyInstall } from "./installHandoff";

const SHA = "d".repeat(64);

function installRouter(call = vi.fn().mockResolvedValue(undefined)) {
  (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend = { call };
  return call;
}

describe("installHandoff", () => {
  beforeEach(() => {
    vi.mocked(backend.prepareForPluginInstall).mockReset();
    vi.mocked(backend.prepareForPluginInstall).mockResolvedValue({ success: true, still_held: [] });
  });
  afterEach(() => {
    delete (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend;
  });

  describe("requestDeckyInstall", () => {
    it("readies the backend, then hands the build to Decky under plugin.json's name", async () => {
      const call = installRouter();
      expect(await requestDeckyInstall("file:///b.zip", "0.33.0-win.25", SHA, 1)).toBe("");
      expect(backend.prepareForPluginInstall).toHaveBeenCalledTimes(1);
      expect(call).toHaveBeenCalledWith(
        "utilities/install_plugin",
        "file:///b.zip",
        "RomM-Dock",
        "0.33.0-win.25",
        SHA,
        1,
      );
    });

    it("hands off even when a holder could not be released (the backend logged it)", async () => {
      const call = installRouter();
      vi.mocked(backend.prepareForPluginInstall).mockResolvedValue({
        success: true,
        still_held: ["gavel native core"],
      });
      expect(await requestDeckyInstall("file:///b.zip", "0.33.0-win.25", SHA, 2)).toBe("");
      expect(call).toHaveBeenCalled();
    });

    it("reports Decky's refusal", async () => {
      installRouter(vi.fn().mockRejectedValue(new Error("busy")));
      expect(await requestDeckyInstall("file:///b.zip", "0.33.0-win.25", SHA, 2)).toBe(
        "Decky refused the install: Error: busy",
      );
    });

    it("does nothing without Decky's router", async () => {
      expect(canSelfUpdate()).toBe(false);
      expect(await requestDeckyInstall("file:///b.zip", "0.33.0-win.25", SHA, 2)).toBe(
        "This Decky Loader cannot install plugins from here.",
      );
      expect(backend.prepareForPluginInstall).not.toHaveBeenCalled();
    });
  });

  describe("reloadPlugin", () => {
    it("asks Decky to reload this plugin", async () => {
      const call = installRouter();
      expect(await reloadPlugin()).toBe("");
      expect(call).toHaveBeenCalledWith("loader/reload_plugin", "RomM-Dock");
    });

    it("reports a failed reload", async () => {
      installRouter(vi.fn().mockRejectedValue(new Error("no such plugin")));
      expect(await reloadPlugin()).toBe("Decky could not restart the plugin: Error: no such plugin");
    });

    it("says so without Decky's router", async () => {
      expect(await reloadPlugin()).toBe("This Decky Loader cannot restart plugins from here.");
    });
  });
});
