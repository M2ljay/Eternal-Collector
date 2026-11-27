import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { InstallIntegrityNotice, integrityNotice, shortVersion } from "./InstallIntegrityNotice";
import * as backend from "../api/backend";

const SHA = "c".repeat(64);
const base = {
  success: true as const,
  expected_version: "0.33.0-win.19",
  current_version: "0.33.0-win.19",
  missing: [],
  mismatched: [],
  extra: [],
  shadowing: [],
  hashes_checked: true,
  detail: null,
};

function installRouter() {
  const call = vi.fn().mockResolvedValue(undefined);
  (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend = { call };
  return call;
}

describe("shortVersion / integrityNotice", () => {
  it("shortens fork versions only", () => {
    expect(shortVersion("0.33.0-win.19")).toBe("win.19");
    expect(shortVersion("0.33.0")).toBe("0.33.0");
    expect(shortVersion(null)).toBe("");
  });

  it("words each status", () => {
    expect(integrityNotice({ ...base, status: "ok" })).toBeNull();
    expect(integrityNotice({ ...base, status: "unchecked" })).toBeNull();
    expect(integrityNotice({ success: false, reason: "check_unavailable", message: "m" })).toBeNull();
    expect(integrityNotice(null)).toBeNull();
    expect(integrityNotice({ ...base, status: "incomplete" })).toEqual({
      title: "Install cut short",
      body: "Reinstall The Collector — the last install was cut short.",
      action: "reinstall",
    });
    expect(integrityNotice({ ...base, status: "stale_files" })?.body).toContain("Reinstall win.19 to clean them up");
  });

  it("falls back to the running version when the manifest gave none", () => {
    const notice = integrityNotice({ ...base, status: "stale_files", expected_version: null });
    expect(notice?.body).toContain("Reinstall win.19");
  });

  it("asks for a restart only after files were restored into a running plugin", () => {
    const repaired = ["py_modules/services/now_playing.py", "py_modules/services/console_shelf.py"];
    expect(integrityNotice({ ...base, status: "ok", repaired, restart_needed: true })).toEqual({
      title: "Files restored",
      body: "The Collector restored 2 files the last install didn't copy. Restart it to load them.",
      action: "restart",
    });
    expect(integrityNotice({ ...base, status: "ok", repaired: [repaired[0]!], restart_needed: true })?.body).toContain(
      "restored 1 file the",
    );
    expect(integrityNotice({ ...base, status: "ok", repaired, restart_needed: false })).toBeNull();
    expect(integrityNotice({ ...base, status: "incomplete", repaired, restart_needed: true })?.action).toBe(
      "reinstall",
    );
  });
});

describe("InstallIntegrityNotice", () => {
  beforeEach(() => {
    vi.mocked(backend.getInstallIntegrity).mockReset();
    vi.mocked(backend.preparePluginReinstall).mockReset();
    vi.mocked(backend.prepareForPluginInstall).mockReset();
    vi.mocked(backend.prepareForPluginInstall).mockResolvedValue({ success: true, still_held: [] });
  });
  afterEach(() => {
    delete (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend;
  });

  it("renders nothing for a clean install", async () => {
    vi.mocked(backend.getInstallIntegrity).mockResolvedValue({ ...base, status: "ok" });
    const { container } = render(<InstallIntegrityNotice />);
    await waitFor(() => expect(backend.getInstallIntegrity).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the check itself fails", async () => {
    const log = vi.spyOn(backend, "logError");
    vi.mocked(backend.getInstallIntegrity).mockRejectedValue(new Error("bridge"));
    const { container } = render(<InstallIntegrityNotice />);
    await waitFor(() => expect(log).toHaveBeenCalledWith(expect.stringContaining("bridge")));
    expect(container).toBeEmptyDOMElement();
    log.mockRestore();
  });

  it("offers the reinstall and hands it to Decky", async () => {
    const call = installRouter();
    vi.mocked(backend.getInstallIntegrity).mockResolvedValue({
      ...base,
      status: "incomplete",
      missing: ["py_modules/services/game_mods.py"],
    });
    vi.mocked(backend.preparePluginReinstall).mockResolvedValue({
      success: true,
      version: "0.33.0-win.19",
      artifact: "file:///r.zip",
      sha256: SHA,
      size: 5,
      install_type: 1,
    });
    render(<InstallIntegrityNotice />);
    expect(await screen.findByText("Reinstall The Collector — the last install was cut short.")).toBeTruthy();
    fireEvent.click(screen.getByText("Reinstall win.19"));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith(
        "utilities/install_plugin",
        "file:///r.zip",
        "RomM-Dock",
        "0.33.0-win.19",
        SHA,
        1,
      ),
    );
    expect(await screen.findByText("Decky will ask you to confirm, then reload the plugin.")).toBeTruthy();
  });

  it("restarts the plugin through Decky after an in-place repair", async () => {
    const call = installRouter();
    vi.mocked(backend.getInstallIntegrity).mockResolvedValue({
      ...base,
      status: "ok",
      repaired: ["py_modules/main_helper.py"],
      repair_source: "romm-dock-0.33.0-win.19.zip",
      restart_needed: true,
    });
    render(<InstallIntegrityNotice />);
    fireEvent.click(await screen.findByText("Restart The Collector"));
    await waitFor(() => expect(call).toHaveBeenCalledWith("loader/reload_plugin", "RomM-Dock"));
    expect(backend.preparePluginReinstall).not.toHaveBeenCalled();
    expect(await screen.findByText("Decky is restarting the plugin.")).toBeTruthy();
  });

  it("shows the refusal when a game is running", async () => {
    installRouter();
    vi.mocked(backend.getInstallIntegrity).mockResolvedValue({ ...base, status: "incomplete" });
    vi.mocked(backend.preparePluginReinstall).mockResolvedValue({
      success: false,
      reason: "game_running",
      message: "A game started from The Collector is still running. Close it first.",
      current: "0.33.0-win.19",
    });
    render(<InstallIntegrityNotice />);
    fireEvent.click(await screen.findByText("Reinstall win.19"));
    expect(await screen.findByText("A game started from The Collector is still running. Close it first.")).toBeTruthy();
  });

  it("disables the button without Decky's router", async () => {
    vi.mocked(backend.getInstallIntegrity).mockResolvedValue({ ...base, status: "stale_files" });
    render(<InstallIntegrityNotice />);
    expect(await screen.findByText("This Decky Loader cannot install plugins from here.")).toBeTruthy();
  });
});
