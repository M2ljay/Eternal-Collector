import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { createElement, forwardRef } from "react";
import { MAX_NOTES_CHARS, NotesModal } from "./NotesModal";

type AnyProps = Record<string, unknown> & { children?: unknown };

vi.mock("@decky/ui", () => ({
  ConfirmModal: (p: AnyProps & { onOK: () => void; bOKDisabled?: boolean; strOKButtonText?: string }) =>
    createElement(
      "div",
      {},
      p.children as never,
      createElement("button", { onClick: p.onOK, disabled: p.bOKDisabled }, p.strOKButtonText ?? "OK"),
    ),
  Focusable: forwardRef<HTMLDivElement, AnyProps>((p, ref) => createElement("div", { ref }, p.children as never)),
  TextField: (p: { value?: string; onChange?: (e: { target: { value: string } }) => void }) =>
    createElement("input", {
      "data-testid": "notes-field",
      value: p.value ?? "",
      onChange: (e: unknown) => p.onChange?.(e as { target: { value: string } }),
    }),
}));

describe("NotesModal", () => {
  it("saves the edited text and closes", async () => {
    const onSave = vi.fn().mockResolvedValue(null);
    const closeModal = vi.fn();
    render(<NotesModal gameTitle="Sonic" initial="old" onSave={onSave} closeModal={closeModal} />);
    fireEvent.change(screen.getByTestId("notes-field"), { target: { value: "spin dash" } });
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(onSave).toHaveBeenCalledWith("spin dash");
    expect(closeModal).toHaveBeenCalled();
  });

  it("stays open with the backend's message on a refusal", async () => {
    const onSave = vi.fn().mockResolvedValue("notes are limited");
    const closeModal = vi.fn();
    render(<NotesModal gameTitle="Sonic" initial="" onSave={onSave} closeModal={closeModal} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(screen.getByTestId("notes-error")).toHaveTextContent("notes are limited");
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("shows a generic error when saving throws", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("x"));
    render(<NotesModal gameTitle="Sonic" initial="" onSave={onSave} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(screen.getByTestId("notes-error")).toHaveTextContent("Saving the notes failed.");
  });

  it("blocks saving over the limit", () => {
    render(<NotesModal gameTitle="Sonic" initial={"n".repeat(MAX_NOTES_CHARS + 1)} onSave={vi.fn()} />);
    expect(screen.getByText("Save")).toBeDisabled();
    expect(screen.getByTestId("notes-count")).toHaveTextContent(`${MAX_NOTES_CHARS + 1} / ${MAX_NOTES_CHARS}`);
  });
});
