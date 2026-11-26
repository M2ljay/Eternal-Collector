/**
 * Shared `@decky/ui` stand-in for The Collector's component tests. The global stub
 * drops `onActivate`, `onClick`, `className` and `preferredFocus`, which are exactly
 * what these components are about, so this one forwards them: `onActivate` fires on
 * click (A on a controller), `preferredFocus` lands in `data-preferred-focus`.
 */

import { createElement, type ReactNode } from "react";
import { vi } from "vitest";

type FocusableProps = {
  children?: ReactNode;
  className?: string;
  onActivate?: () => void;
  onClick?: () => void;
  preferredFocus?: boolean;
  "flow-children"?: string;
  "aria-label"?: string;
  [key: `data-${string}`]: unknown;
};

export const navigate = vi.fn();
export const params: { value: Record<string, string> } = { value: {} };

export function collectorUiMock() {
  return {
    Focusable: (p: FocusableProps) => {
      const data = Object.fromEntries(Object.entries(p).filter(([k]) => k.startsWith("data-")));
      return createElement(
        "div",
        {
          ...data,
          className: p.className,
          role: p.onActivate ? "button" : undefined,
          "aria-label": p["aria-label"],
          "data-flow": p["flow-children"],
          "data-preferred-focus": p.preferredFocus ? "true" : undefined,
          onClick: p.onActivate ?? p.onClick,
        },
        p.children,
      );
    },
    DialogButton: (p: { children?: ReactNode; onClick?: () => void }) =>
      createElement("button", { onClick: p.onClick }, p.children),
    Navigation: { Navigate: navigate },
    useParams: () => params.value,
  };
}
