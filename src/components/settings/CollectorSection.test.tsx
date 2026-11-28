import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { showModal } from "@decky/ui";
import { CollectorSection } from "./CollectorSection";

describe("CollectorSection", () => {
  it("shows the RetroAchievements Web API row masked, with Edit and Remove", () => {
    const onClear = vi.fn();
    render(
      <CollectorSection
        raWebApi={{ username: "Jamiras", configured: true, onVerify: vi.fn(), onSave: vi.fn(), onClear }}
      />,
    );
    expect(screen.getByText("Jamiras · key ••••")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Edit"));
    expect(showModal).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Remove"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("explains what the key is for when none is stored", () => {
    render(
      <CollectorSection
        raWebApi={{ username: "", configured: false, onVerify: vi.fn(), onSave: vi.fn(), onClear: vi.fn() }}
      />,
    );
    expect(screen.getByText("Not configured. Needed for the unlock timeline and goal checks.")).toBeInTheDocument();
    expect(screen.queryByText("Remove")).not.toBeInTheDocument();
  });
});
