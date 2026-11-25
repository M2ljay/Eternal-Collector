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
    expect(integrityNotice({ ...base, status: "incomplete" })?.body).toBe(
      "The Collector's last update didn't finish copying. Reinstall win.19.",
    );
    expect(integrityNotice({ ...base, status: "stale_files" })?.body).toContain("Reinstall win.19 to clean them up");
  });

  it("falls back to the running version when the manifest gave none", () => {
    const notice = integrityNotice({ ...base, status: "incomplete", expected_version: null });
    expect(notice?.body).toContain("Reinstall win.19");
  });
});

describe("InstallIntegrityNotice", () => {
  beforeEach(() => {
    vi.mocked(backend.getInstallIntegrity).mockReset();
    vi.mocked(backend.preparePluginReinstall).mockReset();
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
    expect(
      await screen.findByText("The Collector's last update didn't finish copying. Reinstall win.19."),
    ).toBeTruthy();
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
