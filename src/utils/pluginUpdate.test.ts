import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { toaster } from "@decky/api";
import * as backend from "../api/backend";
import {
  DECKY_INSTALL_TYPE_DOWNGRADE,
  DECKY_INSTALL_TYPE_UPDATE,
  UPDATE_CHECK_INTERVAL_MS,
  canSelfUpdate,
  installPluginUpdate,
  notifyIfPluginUpdate,
  resetPluginUpdateToastMemory,
  rollbackPlugin,
  startPluginUpdateWatch,
  updateOffered,
} from "./pluginUpdate";

const SHA = "a".repeat(64);
const available = {
  success: true as const,
  supported: true,
  current: "0.33.0-win.16",
  update_available: true,
  version: "0.33.0-win.17",
  notes: "n",
  size: 10,
};

function installRouter() {
  const call = vi.fn().mockResolvedValue(undefined);
  (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend = { call };
  return call;
}

describe("pluginUpdate", () => {
  beforeEach(() => {
    vi.mocked(toaster.toast).mockReset();
    vi.mocked(backend.checkPluginUpdate).mockReset();
    vi.mocked(backend.preparePluginUpdate).mockReset();
    vi.mocked(backend.getPluginRollback).mockReset();
    resetPluginUpdateToastMemory();
  });
  afterEach(() => {
    delete (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend;
    vi.useRealTimers();
  });

  describe("canSelfUpdate", () => {
    it("is false without Decky's router and true with it", () => {
      expect(canSelfUpdate()).toBe(false);
      installRouter();
      expect(canSelfUpdate()).toBe(true);
    });
  });

  describe("updateOffered", () => {
    it("only for a supported, available, versioned answer", () => {
      expect(updateOffered(available)).toBe(true);
      expect(updateOffered({ ...available, supported: false })).toBe(false);
      expect(updateOffered({ ...available, update_available: false })).toBe(false);
      expect(updateOffered({ success: false, reason: "x", message: "m", current: "c" })).toBe(false);
      expect(updateOffered(null)).toBe(false);
    });
  });

  describe("installPluginUpdate", () => {
    it("hands the verified file to Decky as an UPDATE under the plugin.json name", async () => {
      const call = installRouter();
      vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
        success: true,
        version: "0.33.0-win.17",
        artifact: "file://C:\\x\\romm-dock-0.33.0-win.17.zip",
        sha256: SHA,
        size: 10,
      });
      expect(await installPluginUpdate()).toBe("");
      expect(call).toHaveBeenCalledWith(
        "utilities/install_plugin",
        "file://C:\\x\\romm-dock-0.33.0-win.17.zip",
        "RomM-Dock",
        "0.33.0-win.17",
        SHA,
        DECKY_INSTALL_TYPE_UPDATE,
      );
    });

    it("never calls Decky when the backend refuses the download", async () => {
      const call = installRouter();
      vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
        success: false,
        reason: "hash_mismatch",
        message: "The download's SHA-256 does not match update.json.",
        current: "0.33.0-win.16",
      });
      expect(await installPluginUpdate()).toBe("The download's SHA-256 does not match update.json.");
      expect(call).not.toHaveBeenCalled();
    });

    it("reports Decky's refusal", async () => {
      const call = installRouter();
      call.mockRejectedValue(new Error("nope"));
      vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
        success: true,
        version: "v",
        artifact: "file:///a.zip",
        sha256: SHA,
        size: 1,
      });
      expect(await installPluginUpdate()).toBe("Decky refused the install: Error: nope");
    });

    it("reports a thrown prepare call", async () => {
      installRouter();
      vi.mocked(backend.preparePluginUpdate).mockRejectedValue(new Error("bridge"));
      expect(await installPluginUpdate()).toBe("The update could not be prepared.");
    });

    it("does nothing without Decky's router", async () => {
      expect(await installPluginUpdate()).toBe("This Decky Loader cannot install plugins from here.");
      expect(backend.preparePluginUpdate).not.toHaveBeenCalled();
    });
  });

  describe("rollbackPlugin", () => {
    it("reinstalls the kept build as a DOWNGRADE", async () => {
      const call = installRouter();
      vi.mocked(backend.getPluginRollback).mockResolvedValue({
        success: true,
        available: true,
        version: "0.33.0-win.16",
        artifact: "file:///kept.zip",
        sha256: SHA,
      });
      expect(await rollbackPlugin()).toBe("");
      expect(call).toHaveBeenCalledWith(
        "utilities/install_plugin",
        "file:///kept.zip",
        "RomM-Dock",
        "0.33.0-win.16",
        SHA,
        DECKY_INSTALL_TYPE_DOWNGRADE,
      );
    });

    it("says so when nothing is kept", async () => {
      const call = installRouter();
      vi.mocked(backend.getPluginRollback).mockResolvedValue({ success: true, available: false });
      expect(await rollbackPlugin()).toBe("No earlier build is kept.");
      expect(call).not.toHaveBeenCalled();
    });
  });

  describe("notifyIfPluginUpdate", () => {
    it("toasts once per version, and a tap starts the install", async () => {
      const call = installRouter();
      vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
      vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
        success: true,
        version: "0.33.0-win.17",
        artifact: "file:///n.zip",
        sha256: SHA,
        size: 10,
      });
      await notifyIfPluginUpdate();
      await notifyIfPluginUpdate();
      expect(backend.checkPluginUpdate).toHaveBeenCalledWith(false);
      expect(toaster.toast).toHaveBeenCalledOnce();
      const toast = vi.mocked(toaster.toast).mock.calls[0]![0];
      expect(toast.body).toBe("Version 0.33.0-win.17 is available. Tap to install.");
      toast.onClick!();
      await vi.waitFor(() => expect(call).toHaveBeenCalledOnce());
    });

    it("toasts the reason when a tapped install is refused", async () => {
      installRouter();
      vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
      vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
        success: false,
        reason: "size_mismatch",
        message: "Size differs.",
        current: "0.33.0-win.16",
      });
      await notifyIfPluginUpdate();
      vi.mocked(toaster.toast).mock.calls[0]![0].onClick!();
      await vi.waitFor(() => expect(toaster.toast).toHaveBeenCalledTimes(2));
      expect(vi.mocked(toaster.toast).mock.calls[1]![0].body).toBe("Size differs.");
    });

    it("stays quiet on an unsupported build", async () => {
      installRouter();
      vi.mocked(backend.checkPluginUpdate).mockResolvedValue({ ...available, supported: false });
      await notifyIfPluginUpdate();
      expect(toaster.toast).not.toHaveBeenCalled();
    });

    it("stays quiet and never asks without Decky's router", async () => {
      await notifyIfPluginUpdate();
      expect(backend.checkPluginUpdate).not.toHaveBeenCalled();
      expect(toaster.toast).not.toHaveBeenCalled();
    });

    it("swallows a failed check without toasting", async () => {
      installRouter();
      vi.mocked(backend.checkPluginUpdate).mockRejectedValue(new Error("bridge"));
      await expect(notifyIfPluginUpdate()).resolves.toBeUndefined();
      expect(toaster.toast).not.toHaveBeenCalled();
    });
  });

  describe("startPluginUpdateWatch", () => {
    it("checks now, then every interval, until stopped", async () => {
      vi.useFakeTimers();
      installRouter();
      vi.mocked(backend.checkPluginUpdate).mockResolvedValue({ ...available, update_available: false });
      const stop = startPluginUpdateWatch();
      expect(backend.checkPluginUpdate).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS);
      expect(backend.checkPluginUpdate).toHaveBeenCalledTimes(2);
      stop();
      await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS * 2);
      expect(backend.checkPluginUpdate).toHaveBeenCalledTimes(2);
    });
  });
});
