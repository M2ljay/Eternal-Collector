import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CollectorSection } from "./CollectorSection";

describe("CollectorSection", () => {
  it("shows the toggle with its value and reports a change", () => {
    const onChange = vi.fn();
    render(<CollectorSection homeShelf={true} onHomeShelfChange={onChange} />);
    expect(screen.getByText("Show The Collector on Home")).toBeInTheDocument();
    const input = screen.getByTestId("toggle-input") as HTMLInputElement;
    expect(input.checked).toBe(true);
    fireEvent.click(input);
    expect(onChange).toHaveBeenCalledWith(false);
  });
});
