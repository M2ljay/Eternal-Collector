import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { ModsButton } from "./ModsButton";
import { showModsModal } from "./ModsModal";
import { nativeLook } from "../utils/nativeLook";

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
});
