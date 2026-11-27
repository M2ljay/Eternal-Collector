import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, fireEvent, waitFor, act } from "@testing-library/react";
import type { ReactElement } from "react";
import { showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import * as backend from "../api/backend";
import { ModsModal, entrySummary, showModsModal } from "./ModsModal";
import type { GameModsInfo, ModInstallPreview, ModTarget } from "../types";

interface ConfirmProps {
  strTitle?: string;
  strDescription?: string;
  onOK?: () => void;
  onCancel?: () => void;
}

function lastConfirm(): ConfirmProps {
  const calls = vi.mocked(showModal).mock.calls;
  const el = calls[calls.length - 1]?.[0] as ReactElement<ConfirmProps> | undefined;
  if (!el) throw new Error("showModal was not called");
  return el.props;
}

function lastToast(): unknown {
  const calls = vi.mocked(toaster.toast).mock.calls;
  return (calls[calls.length - 1]?.[0] as { body?: unknown } | undefined)?.body;
}

function button(container: HTMLElement, text: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll("button")).filter((b) => b.textContent === text);
  if (!found.length) throw new Error(`button "${text}" not found`);
  return found[0] as HTMLButtonElement;
}

const GAME = "C:\\Dolphin\\User\\Load\\Textures\\GALE01";

function textures(overrides: Partial<ModTarget> = {}): ModTarget {
  return {
    target_id: "textures",
    label: "Texture pack",
    scope: "game",
    path: GAME,
    exists: true,
    game_folder: "GALE01",
    notes: [],
    installed: [{ name: "tex", is_dir: true, size: 2048, files: 3, modified: 1_700_000_000, partial: false }],
    installed_truncated: false,
    setting: {
      label: "Load Custom Textures",
      file: "C:\\Dolphin\\User\\Config\\GFX.ini",
      section: "Settings",
      key: "HiresTextures",
      state: "off",
      can_enable: true,
    },
    accepts: "archive_or_folder",
    kind: "files",
    file_name: null,
    ...overrides,
  };
}

function info(overrides: Partial<GameModsInfo> = {}): GameModsInfo {
  return {
    success: true,
    emulator: { id: "dolphin", label: "Dolphin", exe: "C:\\Dolphin\\Dolphin.exe" },
    game_id: "GALE01",
    targets: [textures()],
    omitted: [],
    note: null,
    ...overrides,
  };
}

const PREVIEW: ModInstallPreview = {
  success: true,
  destination: GAME,
  source: "pack.zip",
  writes: [
    { path: "a.png", size: 10, replaces: true },
    { path: "b.png", size: 10, replaces: false },
  ],
  write_count: 2,
  total_bytes: 20,
  replace_count: 1,
  stripped_folder: "GALE01",
  backup_root: "C:\\Dolphin\\User\\romm-mod-backups",
  fingerprint: "fp1",
};

async function renderLoaded(answer = info()) {
  vi.mocked(backend.getGameMods).mockResolvedValue(answer);
  const rendered = render(<ModsModal romId={7} gameName="Melee" />);
  await waitFor(() => {
    expect(rendered.container.textContent).toContain("Mods — Melee");
    expect(rendered.container.textContent).not.toContain("Reading this game");
  });
  return rendered;
}

beforeEach(() => {
  vi.mocked(showModal).mockClear();
  vi.mocked(toaster.toast).mockClear();
  vi.mocked(backend.getGameMods).mockReset();
  vi.mocked(backend.removeMod).mockReset();
  vi.mocked(backend.enableModSetting).mockReset();
  vi.mocked(backend.listModSources).mockReset();
  vi.mocked(backend.previewModInstall).mockReset();
  vi.mocked(backend.installMod).mockReset();
  vi.mocked(backend.openModFolder).mockReset();
});

describe("ModsModal — what it shows", () => {
  it("names the emulator, the folder, what is installed and the setting hint", async () => {
    const { container } = await renderLoaded(
      info({ omitted: [{ label: "Patches and cheats (.pnach)", reason: "needs the CRC" }] }),
    );
    const text = container.textContent;
    expect(text).toContain("Dolphin · Game ID GALE01");
    expect(text).toContain(GAME);
    expect(text).toContain("tex\\");
    expect(text).toContain("3 files");
    expect(text).toContain("Texture packs are off in Dolphin (Load Custom Textures).");
    expect(text).toContain("Not offered: Patches and cheats (.pnach) — needs the CRC");
    expect(button(container, "Turn On")).toBeTruthy();
    expect(backend.getGameMods).toHaveBeenCalledWith(7);
  });

  it("hides the hint once the setting is on, and the button when it cannot be edited", async () => {
    const setting = { ...textures().setting!, state: "unknown" as const, can_enable: false };
    const { container } = await renderLoaded(
      info({ targets: [textures({ setting }), textures({ target_id: "b", setting: null })] }),
    );
    expect(container.textContent).toContain("Couldn't read whether Load Custom Textures is on");
    expect(Array.from(container.querySelectorAll("button")).some((b) => b.textContent === "Turn On")).toBe(false);
  });

  it("shows the note when there is no known mod folder", async () => {
    const { container } = await renderLoaded(
      info({ targets: [], note: "No known mod folder for this emulator.", game_id: null }),
    );
    expect(container.textContent).toContain("No known mod folder for this emulator.");
  });

  it("shows the backend's failure message", async () => {
    vi.mocked(backend.getGameMods).mockResolvedValue({
      success: false,
      reason: "unsupported",
      message: "Mods are available for EmuDeck games on Windows.",
    });
    const { container } = render(<ModsModal romId={7} gameName="Melee" />);
    await waitFor(() => expect(container.textContent).toContain("Mods are available for EmuDeck games on Windows."));
  });

  it("reports a rejected read instead of spinning forever", async () => {
    vi.mocked(backend.getGameMods).mockRejectedValue(new Error("boom"));
    const { container } = render(<ModsModal romId={7} gameName="Melee" />);
    await waitFor(() => expect(container.textContent).toContain("Couldn't read this game's mod folders."));
  });

  it("summarises entries", () => {
    expect(entrySummary({ name: "x", is_dir: true, size: 1024, files: 50000, modified: 0, partial: true })).toBe(
      "50000+ files · 1.0 KB",
    );
  });

  it("showModsModal hands the panel to showModal", () => {
    showModsModal(3, "Zelda");
    const el = vi.mocked(showModal).mock.calls[0]?.[0] as ReactElement<{ romId: number; gameName: string }>;
    expect(el.props).toMatchObject({ romId: 3, gameName: "Zelda" });
  });
});

describe("ModsModal — remove", () => {
  it("confirms exactly what moves, then removes and names the backup", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.removeMod).mockResolvedValue({
      success: true,
      removed: `${GAME}\\tex`,
      backup_folder: "C:\\bk\\tex",
    });
    fireEvent.click(button(container, "Remove"));
    const confirm = lastConfirm();
    expect(confirm.strDescription).toContain(`${GAME}\\tex`);
    expect(confirm.strDescription).toContain("not deleted");
    await act(async () => confirm.onOK?.());
    expect(backend.removeMod).toHaveBeenCalledWith(7, "textures", "tex");
    await waitFor(() => expect(lastToast()).toBe("Removed. Backup: C:\\bk\\tex"));
    expect(backend.getGameMods).toHaveBeenCalledTimes(2);
  });

  it("removes the whole game folder with a null name", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.removeMod).mockResolvedValue({ success: false, reason: "io_error", message: "locked" });
    fireEvent.click(button(container, "Remove All"));
    await act(async () => lastConfirm().onOK?.());
    expect(backend.removeMod).toHaveBeenCalledWith(7, "textures", null);
    await waitFor(() => expect(lastToast()).toBe("locked"));
  });

  it("does nothing when cancelled", async () => {
    const { container } = await renderLoaded();
    fireEvent.click(button(container, "Remove"));
    await act(async () => lastConfirm().onCancel?.());
    expect(backend.removeMod).not.toHaveBeenCalled();
  });

  it("toasts when the call itself rejects", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.removeMod).mockRejectedValue(new Error("bridge down"));
    fireEvent.click(button(container, "Remove"));
    await act(async () => lastConfirm().onOK?.());
    await waitFor(() => expect(String(lastToast())).toContain("Something went wrong"));
  });
});

describe("ModsModal — setting", () => {
  it("asks to close the emulator, then turns the setting on", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.enableModSetting).mockResolvedValue({ success: true, file: "f", backup_path: "b" });
    fireEvent.click(button(container, "Turn On"));
    const confirm = lastConfirm();
    expect(confirm.strDescription).toContain("Close Dolphin first");
    expect(confirm.strDescription).toContain("[Settings] HiresTextures");
    await act(async () => confirm.onOK?.());
    expect(backend.enableModSetting).toHaveBeenCalledWith(7, "textures");
    await waitFor(() => expect(lastToast()).toBe("Load Custom Textures is on."));
  });

  it("reports a refusal", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.enableModSetting).mockResolvedValue({
      success: false,
      reason: "emulator_running",
      message: "Dolphin is running. Close it first, then try again.",
    });
    fireEvent.click(button(container, "Turn On"));
    await act(async () => lastConfirm().onOK?.());
    await waitFor(() => expect(lastToast()).toBe("Dolphin is running. Close it first, then try again."));
  });
});

describe("ModsModal — install", () => {
  async function openSources() {
    const rendered = await renderLoaded();
    vi.mocked(backend.listModSources).mockResolvedValue({
      success: true,
      folder: "C:\\Users\\me\\Downloads",
      truncated: false,
      entries: [
        {
          name: "pack.zip",
          is_dir: false,
          size: 20,
          files: 1,
          modified: 1,
          partial: false,
          kind: "zip",
          supported: true,
        },
        {
          name: "pack.7z",
          is_dir: false,
          size: 20,
          files: 1,
          modified: 1,
          partial: false,
          kind: "unsupported_archive",
          supported: false,
        },
      ],
    });
    fireEvent.click(button(rendered.container, "Install from Downloads"));
    await waitFor(() => expect(rendered.container.textContent).toContain("C:\\Users\\me\\Downloads"));
    return rendered;
  }

  it("lists Downloads, previews, installs with the preview's fingerprint", async () => {
    const { container } = await openSources();
    expect(backend.listModSources).toHaveBeenCalledWith(7, "textures");
    expect(container.textContent).toContain("Extract this archive first");
    const zip = Array.from(container.querySelectorAll("button")).find((b) => b.textContent.startsWith("pack.zip"));
    const sevenZip = Array.from(container.querySelectorAll("button")).find((b) => b.textContent.startsWith("pack.7z"));
    expect(sevenZip?.disabled).toBe(true);
    vi.mocked(backend.previewModInstall).mockResolvedValue(PREVIEW);
    fireEvent.click(zip!);
    await waitFor(() => expect(container.textContent).toContain("2 files"));
    expect(backend.previewModInstall).toHaveBeenCalledWith(7, "textures", "pack.zip");
    expect(container.textContent).toContain("1 existing files will be replaced");
    expect(container.textContent).toContain("C:\\Dolphin\\User\\romm-mod-backups");
    expect(container.textContent).toContain("replace  a.png");

    vi.mocked(backend.installMod).mockResolvedValue({
      success: true,
      destination: GAME,
      written: 2,
      backed_up: 1,
      backup_folder: "C:\\bk",
    });
    fireEvent.click(button(container, "Install"));
    await waitFor(() => expect(lastToast()).toBe("Installed 2 files. Replaced files: C:\\bk"));
    expect(backend.installMod).toHaveBeenCalledWith(7, "textures", "pack.zip", "fp1");
    await waitFor(() => expect(container.textContent).toContain("Installed here:"));
  });

  it("previews again when the backend says something changed", async () => {
    const { container } = await openSources();
    vi.mocked(backend.previewModInstall).mockResolvedValue(PREVIEW);
    const zip = Array.from(container.querySelectorAll("button")).find((b) => b.textContent.startsWith("pack.zip"));
    fireEvent.click(zip!);
    await waitFor(() => expect(container.textContent).toContain("replace  a.png"));
    vi.mocked(backend.installMod).mockResolvedValue({ success: false, reason: "changed", message: "review it again" });
    fireEvent.click(button(container, "Install"));
    await waitFor(() => expect(backend.previewModInstall).toHaveBeenCalledTimes(2));
    expect(lastToast()).toBe("review it again");
  });

  it("toasts a refused preview and stays on the list", async () => {
    const { container } = await openSources();
    vi.mocked(backend.previewModInstall).mockResolvedValue({
      success: false,
      reason: "unsafe_source",
      message: "'../x' is not a safe relative path.",
    });
    const zip = Array.from(container.querySelectorAll("button")).find((b) => b.textContent.startsWith("pack.zip"));
    fireEvent.click(zip!);
    await waitFor(() => expect(lastToast()).toBe("'../x' is not a safe relative path."));
    expect(container.textContent).toContain("Pick what to install");
  });

  it("shows a Downloads listing failure and goes back", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.listModSources).mockResolvedValue({
      success: false,
      reason: "not_found",
      message: "no Downloads",
    });
    fireEvent.click(button(container, "Install from Downloads"));
    await waitFor(() => expect(container.textContent).toContain("no Downloads"));
    fireEvent.click(button(container, "Back"));
    expect(container.textContent).toContain("Installed here:");
  });
});

describe("ModsModal — open folder", () => {
  it("toasts when the folder cannot be opened", async () => {
    const { container } = await renderLoaded();
    vi.mocked(backend.openModFolder).mockResolvedValue({ success: false, reason: "not_found", message: "not yet" });
    fireEvent.click(button(container, "Open Folder"));
    await waitFor(() => expect(lastToast()).toBe("not yet"));
    expect(backend.openModFolder).toHaveBeenCalledWith(7, "textures");
  });
});

describe("ModsModal — cheat files and built-in entries", () => {
  it("offers a cheat file target with the name it is saved as, and its setting as a generic hint", async () => {
    vi.mocked(backend.listModSources).mockResolvedValue({ success: true, folder: "D", entries: [], truncated: false });
    const cheats = textures({
      target_id: "cheats",
      label: "Cheat file (.pnach)",
      scope: "file",
      path: "C:\\PCSX2\\cheats",
      game_folder: null,
      installed: [],
      accepts: "cheat_file",
      kind: "cheatFile",
      file_name: "SLUS-20946_3E2A1B0C.pnach",
      setting: {
        label: "Enable Cheats",
        file: "C:\\PCSX2\\inis\\PCSX2.ini",
        section: "EmuCore",
        key: "EnableCheats",
        state: "off",
        can_enable: true,
      },
    });
    const { container } = await renderLoaded(info({ targets: [cheats] }));
    expect(container.textContent).toContain("as SLUS-20946_3E2A1B0C.pnach");
    expect(container.textContent).toContain("Enable Cheats is off in Dolphin");
    fireEvent.click(button(container, "Install from Downloads"));
    await waitFor(() => expect(container.textContent).toContain("a .pnach file, or a .zip holding exactly one"));
  });

  it("shows a built-in toggle target's entries and offers no install or remove", async () => {
    vi.mocked(backend.listModBuiltins)
      .mockReset()
      .mockResolvedValue({
        success: true,
        target_id: "gecko_codes",
        file: "f",
        editable: true,
        reason: null,
        entries: [
          {
            entry_id: "WS",
            name: "Widescreen",
            description: "",
            notes: [],
            enabled: true,
            can_toggle: true,
            origin: "built-in",
          },
        ],
        setting: null,
      });
    const gecko = textures({
      target_id: "gecko_codes",
      label: "Gecko codes",
      scope: "toggle",
      game_folder: null,
      installed: [],
      accepts: "none",
      kind: "builtinToggle",
    });
    const { container } = await renderLoaded(info({ targets: [gecko] }));
    await waitFor(() => expect(container.textContent).toContain("Widescreen"));
    expect(container.textContent).not.toContain("Install from Downloads");
    expect(container.textContent).not.toContain("Nothing installed here yet.");
    expect(backend.listModBuiltins).toHaveBeenCalledWith(7, "gecko_codes");
  });
});

describe("ModsModal — updates and DLC (win.30)", () => {
  it("shows only the asked kinds and offers no Remove for installer or read-only targets", async () => {
    const content = textures({
      target_id: "content",
      label: "Updates & DLC (.cia)",
      scope: "install",
      game_folder: null,
      accepts: "cia_file",
      kind: "update",
      installed: [{ name: "Update", is_dir: true, size: 10, files: 1, modified: 1, partial: false }],
    });
    const { container } = await renderLoaded(info({ targets: [textures(), content] }));
    expect(container.textContent).toContain("Texture pack");
    const narrowed = render(<ModsModal romId={7} gameName="Melee" kinds={["update", "dlc"]} />);
    await waitFor(() => expect(narrowed.container.textContent).toContain("Updates & DLC (.cia)"));
    expect(narrowed.container.textContent).not.toContain("Texture pack");
    expect(Array.from(narrowed.container.querySelectorAll("button")).map((b) => b.textContent)).not.toContain("Remove");
  });

  it("describes an installer preview and a replaced update folder", async () => {
    vi.mocked(backend.listModSources).mockResolvedValue({
      success: true,
      folder: "D",
      entries: [
        {
          name: "MK7.cia",
          is_dir: false,
          size: 5,
          files: 1,
          modified: 1,
          partial: false,
          kind: "cia",
          supported: true,
        },
      ],
      truncated: false,
    });
    vi.mocked(backend.previewModInstall).mockResolvedValue({
      ...PREVIEW,
      source: "MK7.cia",
      installer: "azahar_cia",
      replaces_folder: true,
    });
    const content = textures({ target_id: "content", scope: "install", accepts: "cia_file", kind: "update" });
    const { container } = await renderLoaded(info({ targets: [content] }));
    fireEvent.click(button(container, "Install from Downloads"));
    await waitFor(() => expect(container.textContent).toContain("a .cia file; the emulator installs it"));
    const pick = Array.from(container.querySelectorAll("button")).find((b) => b.textContent.startsWith("MK7.cia"));
    fireEvent.click(pick!);
    await waitFor(() => expect(container.textContent).toContain("Azahar will install MK7.cia"));
    expect(container.textContent).toContain("The update already there is moved to");
  });
});
