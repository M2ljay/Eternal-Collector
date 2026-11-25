import { describe, it, expect, vi, beforeEach } from "vitest";
import { toaster } from "@decky/api";
import type { ToastNotification } from "@decky/api";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { showToast, PLUGIN_NAME, PLUGIN_DISPLAY_NAME } from "./toast";

describe("showToast", () => {
  beforeEach(() => {
    vi.mocked(toaster.toast).mockReset();
  });

  it("titles the toast with the plugin name", () => {
    showToast("Sync complete");

    expect(toaster.toast).toHaveBeenCalledOnce();
    expect(toaster.toast).toHaveBeenCalledWith({ title: PLUGIN_DISPLAY_NAME, body: "Sync complete" });
  });

  it("passes options through alongside the body", () => {
    showToast("12 games added", { duration: 8000, subtext: "3 skipped" });

    expect(toaster.toast).toHaveBeenCalledWith({
      title: PLUGIN_DISPLAY_NAME,
      body: "12 games added",
      duration: 8000,
      subtext: "3 skipped",
    });
  });

  it("keys the plugin by the manifest's name, which Decky installs and lists it under", () => {
    const manifest = JSON.parse(readFileSync(resolve(process.cwd(), "plugin.json"), "utf-8")) as { name: string };
    expect(PLUGIN_NAME).toBe(manifest.name);
    expect(PLUGIN_NAME).toBe("RomM-Dock");
  });

  it("raises toasts under the display name", () => {
    expect(PLUGIN_DISPLAY_NAME).toBe("The Collector");
    showToast("Sync complete");
    expect(toaster.toast).toHaveBeenCalledWith({ title: "The Collector", body: "Sync complete" });
  });

  it("returns the notification so a caller can dismiss it", () => {
    const notification = { data: { title: PLUGIN_DISPLAY_NAME, body: "Downloading" }, dismiss: vi.fn() };
    vi.mocked(toaster.toast).mockReturnValue(notification as ToastNotification);

    expect(showToast("Downloading")).toBe(notification);
  });
});
