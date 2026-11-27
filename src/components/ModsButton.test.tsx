import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { ModsButton } from "./ModsButton";
import { showModsModal } from "./ModsModal";
import { nativeLook } from "../utils/nativeLook";
import { _resetGamePageExtensionsForTests, registerGamePageExtension } from "../utils/gamePageExtensions";

vi.mock("./ModsModal", () => ({ showModsModal: vi.fn() }));
vi.mock("../utils/nativeLook", () => ({
  nativeLook: vi.fn(() => true),
  NativeMenuButton: ({ onClick, title, children }: { onClick: () => void; title: string; children: unknown }) => (
    <button onClick={onClick} title={title}>
      {children as never}
    </button>
  ),
}));

beforeEach(() => {
  _resetGamePageExtensionsForTests();
  vi.mocked(showModsModal).mockClear();
  vi.mocked(nativeLook).mockReturnValue(true);
});

describe("ModsButton", () => {
  it("opens the panel for the installed game", () => {
    const { getByTitle } = render(<ModsButton romId={5} romName="Melee" installed onFocus={() => {}} />);
    fireEvent.click(getByTitle("Mods"));
    expect(showModsModal).toHaveBeenCalledWith(5, "Melee");
  });

  it.each([
    ["not installed", { romId: 5, installed: false }],
    ["no rom id yet", { romId: null, installed: true }],
  ])("renders nothing when %s", (_label, props) => {
    const { queryByTitle } = render(<ModsButton romName="x" onFocus={() => {}} {...props} />);
    expect(queryByTitle("Mods")).toBeNull();
  });

  it("renders nothing outside the Windows native look", () => {
    vi.mocked(nativeLook).mockReturnValue(false);
    const { queryByTitle } = render(<ModsButton romId={5} romName="x" installed onFocus={() => {}} />);
    expect(queryByTitle("Mods")).toBeNull();
  });

  it("hides while Forge's Mods tab is registered and comes back when it unregisters", () => {
    const { queryByTitle } = render(<ModsButton romId={5} romName="x" installed onFocus={() => {}} />);
    expect(queryByTitle("Mods")).not.toBeNull();
    let unregister: () => void = () => {};
    act(() => {
      unregister = registerGamePageExtension({ id: "forge.mods", kind: "tab", label: "Mods", render: () => null });
    });
    expect(queryByTitle("Mods")).toBeNull();
    act(() => unregister());
    expect(queryByTitle("Mods")).not.toBeNull();
  });

  it("stays when only another plugin's extension is registered", () => {
    registerGamePageExtension({ id: "other.tab", kind: "tab", label: "Other", render: () => null });
    const { queryByTitle } = render(<ModsButton romId={5} romName="x" installed onFocus={() => {}} />);
    expect(queryByTitle("Mods")).not.toBeNull();
  });
});
