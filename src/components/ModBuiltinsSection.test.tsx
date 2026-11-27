import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { ModBuiltinsSection } from "./ModBuiltinsSection";
import * as backend from "../api/backend";
import { showToast } from "../utils/toast";
import type { ModBuiltinsAnswer, ModTarget } from "../types";

vi.mock("../api/backend", () => ({
  listModBuiltins: vi.fn(),
  setModBuiltin: vi.fn(),
  logError: vi.fn(),
}));
vi.mock("../utils/toast", () => ({ showToast: vi.fn() }));

const TARGET: ModTarget = {
  target_id: "gecko_codes",
  label: "Gecko codes",
  scope: "toggle",
  path: "C:\\Dolphin\\User\\GameSettings",
  exists: true,
  game_folder: null,
  notes: [],
  installed: [],
  installed_truncated: false,
  setting: null,
  accepts: "none",
  kind: "builtinToggle",
  file_name: null,
};

function listing(overrides: Partial<Extract<ModBuiltinsAnswer, { success: true }>> = {}): ModBuiltinsAnswer {
  return {
    success: true,
    target_id: "gecko_codes",
    file: "C:\\Dolphin\\User\\GameSettings\\GALE01.ini",
    editable: true,
    reason: null,
    entries: [
      {
        entry_id: "Widescreen",
        name: "Widescreen",
        description: "16:9",
        notes: [],
        enabled: false,
        can_toggle: true,
        origin: "built-in",
      },
      {
        entry_id: "Locked",
        name: "Locked",
        description: "",
        notes: [],
        enabled: true,
        can_toggle: false,
        origin: "user",
      },
    ],
    setting: null,
    ...overrides,
  };
}

const flush = () =>
  act(async () => {
    for (let i = 0; i < 4; i++) await Promise.resolve();
  });

beforeEach(() => {
  vi.mocked(backend.listModBuiltins).mockReset().mockResolvedValue(listing());
  vi.mocked(backend.setModBuiltin).mockReset();
  vi.mocked(showToast).mockReset();
});

describe("ModBuiltinsSection", () => {
  it("lists entries with their state and disables the ones that cannot be switched", async () => {
    const { getByText } = render(<ModBuiltinsSection romId={7} target={TARGET} emulatorLabel="Dolphin" />);
    await flush();
    expect(getByText("Widescreen")).toBeTruthy();
    expect((getByText("Off") as HTMLButtonElement).disabled).toBe(false);
    expect((getByText("On") as HTMLButtonElement).disabled).toBe(true);
  });

  it("switches by entry id, then re-reads the list", async () => {
    vi.mocked(backend.setModBuiltin).mockResolvedValue({ success: true, file: "f", backup_path: "b", enabled: true });
    const { getByText } = render(<ModBuiltinsSection romId={7} target={TARGET} emulatorLabel="Dolphin" />);
    await flush();
    fireEvent.click(getByText("Off"));
    await flush();
    expect(backend.setModBuiltin).toHaveBeenCalledWith(7, "gecko_codes", "Widescreen", true);
    expect(backend.listModBuiltins).toHaveBeenCalledTimes(2);
  });

  it("shows the backend's refusal as a toast", async () => {
    vi.mocked(backend.setModBuiltin).mockResolvedValue({
      success: false,
      reason: "emulator_running",
      message: "Dolphin is running. Close it first, then try again.",
    });
    const { getByText } = render(<ModBuiltinsSection romId={7} target={TARGET} emulatorLabel="Dolphin" />);
    await flush();
    fireEvent.click(getByText("Off"));
    await flush();
    expect(showToast).toHaveBeenCalledWith("Dolphin is running. Close it first, then try again.");
  });

  it("shows why a list is read-only", async () => {
    vi.mocked(backend.listModBuiltins).mockResolvedValue(
      listing({ editable: false, reason: "GAL.ini also switches codes" }),
    );
    const { getByText } = render(<ModBuiltinsSection romId={7} target={TARGET} emulatorLabel="Dolphin" />);
    await flush();
    expect(getByText("GAL.ini also switches codes")).toBeTruthy();
  });

  it("says so when the list cannot be read", async () => {
    vi.mocked(backend.listModBuiltins).mockRejectedValue(new Error("socket"));
    const { getByText } = render(<ModBuiltinsSection romId={7} target={TARGET} emulatorLabel="Dolphin" />);
    await flush();
    expect(getByText("Couldn't read the list.")).toBeTruthy();
    expect(backend.logError).toHaveBeenCalledWith("listModBuiltins failed: Error: socket");
  });
});
