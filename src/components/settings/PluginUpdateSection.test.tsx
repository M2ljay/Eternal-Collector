import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { PluginUpdateSection } from "./PluginUpdateSection";
import * as backend from "../../api/backend";

const SHA = "b".repeat(64);
const available = {
  success: true as const,
  supported: true,
  current: "0.33.0-win.16",
  update_available: true,
  version: "0.33.0-win.17",
  notes: "Self-update channel",
  size: 2 * 1024 * 1024,
};

function installRouter() {
  const call = vi.fn().mockResolvedValue(undefined);
  (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend = { call };
  return call;
}

describe("PluginUpdateSection", () => {
  beforeEach(() => {
    vi.mocked(backend.checkPluginUpdate).mockReset();
    vi.mocked(backend.preparePluginUpdate).mockReset();
    vi.mocked(backend.getPluginRollback).mockReset();
    vi.mocked(backend.prepareForPluginInstall).mockReset();
    vi.mocked(backend.prepareForPluginInstall).mockResolvedValue({ success: true, still_held: [] });
    vi.mocked(backend.getPluginRollback).mockResolvedValue({ success: true, available: false });
  });
  afterEach(() => {
    delete (globalThis as unknown as { DeckyBackend?: unknown }).DeckyBackend;
  });

  it("renders nothing on an unsupported build", async () => {
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue({ ...available, supported: false, update_available: false });
    const { container } = render(<PluginUpdateSection />);
    await waitFor(() => expect(backend.checkPluginUpdate).toHaveBeenCalledWith(false));
    expect(container.textContent).toBe("");
  });

  it("offers the newer build with its notes and size", async () => {
    installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
    render(<PluginUpdateSection />);
    expect(await screen.findByText("Install 0.33.0-win.17 (2.0 MB)")).toBeTruthy();
    expect(screen.getByText("0.33.0-win.16")).toBeTruthy();
    expect(screen.getByText("Self-update channel")).toBeTruthy();
  });

  it("Install hands off to Decky and says Decky will confirm", async () => {
    const call = installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
    vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
      success: true,
      version: "0.33.0-win.17",
      artifact: "file:///n.zip",
      sha256: SHA,
      size: 10,
      install_type: 2,
    });
    render(<PluginUpdateSection />);
    fireEvent.click(await screen.findByText("Install 0.33.0-win.17 (2.0 MB)"));
    expect(await screen.findByText("Decky will ask you to confirm, then reload the plugin.")).toBeTruthy();
    expect(call).toHaveBeenCalledOnce();
  });

  it("shows a refused download's reason and never calls Decky", async () => {
    const call = installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
    vi.mocked(backend.preparePluginUpdate).mockResolvedValue({
      success: false,
      reason: "hash_mismatch",
      message: "The download's SHA-256 does not match update.json.",
      current: "0.33.0-win.16",
    });
    render(<PluginUpdateSection />);
    fireEvent.click(await screen.findByText("Install 0.33.0-win.17 (2.0 MB)"));
    expect(await screen.findByText("The download's SHA-256 does not match update.json.")).toBeTruthy();
    expect(call).not.toHaveBeenCalled();
  });

  it("Check for Updates forces a fresh read and reports up to date", async () => {
    installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue({ ...available, update_available: false });
    render(<PluginUpdateSection />);
    fireEvent.click(await screen.findByText("Check for Updates"));
    await waitFor(() => expect(backend.checkPluginUpdate).toHaveBeenCalledWith(true));
    expect(await screen.findByText("You have the newest build.")).toBeTruthy();
    expect(screen.queryByText(/^Install /)).toBeNull();
  });

  it("shows a failed check's message", async () => {
    installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue({
      success: false,
      reason: "server_unreachable",
      message: "Could not reach the release channel: offline",
      current: "0.33.0-win.16",
    });
    render(<PluginUpdateSection />);
    expect(await screen.findByText("Could not reach the release channel: offline")).toBeTruthy();
  });

  it("shows a fallback when the check throws", async () => {
    vi.mocked(backend.checkPluginUpdate)
      .mockResolvedValueOnce({ ...available, update_available: false })
      .mockRejectedValueOnce(new Error("bridge"));
    render(<PluginUpdateSection />);
    fireEvent.click(await screen.findByText("Check for Updates"));
    expect(await screen.findByText("Could not check for updates.")).toBeTruthy();
  });

  it("offers a rollback to the kept build", async () => {
    const call = installRouter();
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue({
      ...available,
      current: "0.33.0-win.17",
      update_available: false,
    });
    vi.mocked(backend.getPluginRollback).mockResolvedValue({
      success: true,
      available: true,
      version: "0.33.0-win.16",
      artifact: "file:///kept.zip",
      sha256: SHA,
    });
    render(<PluginUpdateSection />);
    fireEvent.click(await screen.findByText("Roll Back to 0.33.0-win.16"));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith(
        "utilities/install_plugin",
        "file:///kept.zip",
        "RomM-Dock",
        "0.33.0-win.16",
        SHA,
        3,
      ),
    );
  });

  it("disables Install and explains when Decky's installer is not reachable", async () => {
    vi.mocked(backend.checkPluginUpdate).mockResolvedValue(available);
    render(<PluginUpdateSection />);
    const button = await screen.findByText("Install 0.33.0-win.17 (2.0 MB)");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("This Decky Loader cannot install plugins from here.")).toBeTruthy();
  });
});
