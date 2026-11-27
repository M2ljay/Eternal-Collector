import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { createElement, forwardRef } from "react";
import { KEEP_STORED_KEY, RaWebApiModal } from "./RaWebApiModal";

type AnyProps = Record<string, unknown> & { children?: unknown };

vi.mock("@decky/ui", () => ({
  ModalRoot: (p: AnyProps) => createElement("div", {}, p.children as never),
  Focusable: forwardRef<HTMLDivElement, AnyProps>((p, ref) => createElement("div", { ref }, p.children as never)),
  DialogButton: ({ children, onClick, disabled }: AnyProps & { onClick?: () => void; disabled?: boolean }) =>
    createElement("button", { onClick, disabled }, children as never),
  TextField: (p: { label?: string; value?: string; bIsPassword?: boolean; onChange?: (e: unknown) => void }) =>
    createElement("input", {
      "data-testid": `field-${p.label ?? ""}`,
      "data-is-password": p.bIsPassword ? "true" : "false",
      value: p.value ?? "",
      onChange: (e: unknown) => p.onChange?.(e),
    }),
}));

const KEY = "AbCdEf0123456789AbCdEf0123456789";

describe("RaWebApiModal", () => {
  it("verifies, then saves, then closes; the key field is a password field", async () => {
    const onVerify = vi.fn().mockResolvedValue({ success: true, message: "ok" });
    const onSave = vi.fn().mockResolvedValue({ success: true });
    const closeModal = vi.fn();
    render(
      <RaWebApiModal
        initialUsername=""
        hasStoredKey={false}
        onVerify={onVerify}
        onSave={onSave}
        closeModal={closeModal}
      />,
    );
    expect(screen.getByTestId("field-Web API key")).toHaveAttribute("data-is-password", "true");
    expect(screen.getByText("Save")).toBeDisabled();
    fireEvent.change(screen.getByTestId("field-Username"), { target: { value: " Jamiras " } });
    fireEvent.change(screen.getByTestId("field-Web API key"), { target: { value: KEY } });
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(onVerify).toHaveBeenCalledWith("Jamiras", KEY);
    expect(onSave).toHaveBeenCalledWith("Jamiras", KEY);
    expect(closeModal).toHaveBeenCalled();
  });

  it("an empty key keeps the stored one", async () => {
    const onVerify = vi.fn().mockResolvedValue({ success: true, message: "ok" });
    const onSave = vi.fn().mockResolvedValue({ success: true });
    render(<RaWebApiModal initialUsername="Jamiras" hasStoredKey={true} onVerify={onVerify} onSave={onSave} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(onVerify).toHaveBeenCalledWith("Jamiras", KEEP_STORED_KEY);
    expect(onSave).toHaveBeenCalledWith("Jamiras", KEEP_STORED_KEY);
  });

  it("a refused key is shown and nothing is saved", async () => {
    const onVerify = vi
      .fn()
      .mockResolvedValue({ success: false, message: "RetroAchievements refused the Web API key." });
    const onSave = vi.fn();
    const closeModal = vi.fn();
    render(
      <RaWebApiModal
        initialUsername="Jamiras"
        hasStoredKey={false}
        onVerify={onVerify}
        onSave={onSave}
        closeModal={closeModal}
      />,
    );
    fireEvent.change(screen.getByTestId("field-Web API key"), { target: { value: KEY } });
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(screen.getByTestId("ra-web-error")).toHaveTextContent("refused");
    expect(onSave).not.toHaveBeenCalled();
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("a thrown verify shows a connection message", async () => {
    const onVerify = vi.fn().mockRejectedValue(new Error("x"));
    render(<RaWebApiModal initialUsername="Jamiras" hasStoredKey={true} onVerify={onVerify} onSave={vi.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByText("Save"));
    });
    expect(screen.getByTestId("ra-web-error")).toHaveTextContent("Could not reach RetroAchievements");
  });
});
