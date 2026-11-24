/**
 * Steam-native look for the RomM game page on Windows.
 *
 * On Windows the play section is drawn with Steam's own class names (from the
 * `@decky/ui` class maps) instead of RomM's styling, so the Play / Install
 * buttons, menu buttons and stats pick up the Steam client's theme. Every
 * helper here falls back to the default RomM rendering when `nativeLook()` is
 * false.
 */

import type { ReactNode } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { appActionButtonClasses, findSP, playSectionClasses } from "./deckyUiInternals";

export function nativeLook(): boolean {
  return navigator.userAgent.includes("Windows");
}

export function joinCls(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const NATIVE_CLASS_FOR: Record<string, () => string | undefined> = {
  "romm-info-item": () => playSectionClasses?.GameStat,
  "romm-info-header": () => playSectionClasses?.PlayBarLabel,
  "romm-info-value": () => playSectionClasses?.PlayBarDetailLabel,
};

/** Map a RomM info-item class list to Steam's equivalent class when the native look is active. */
export function rc(base: string): string {
  if (!nativeLook()) return base;
  const [first, ...rest] = base.split(" ") as [string, ...string[]];
  const native = NATIVE_CLASS_FOR[first]?.();
  // Steam's class only: RomM's own label styling must not compete with the theme.
  return native ? joinCls(native, ...rest) : base;
}

// A click on a Steam Focusable can arrive as both onClick and onActivate; act once.
const nativeMenuKeys = new Map<string, object>();
function nativeMenuKey(title: string | undefined): object | null | undefined {
  if (!title) return null;
  if (!nativeMenuKeys.has(title)) nativeMenuKeys.set(title, {});
  return nativeMenuKeys.get(title);
}

const nativePressAt = new WeakMap<object, number>();

/** Wrap `fn` so presses sharing `key` (or `fn` itself) within 500ms run it only once. */
export function pressOnce<A extends unknown[]>(
  fn: ((...args: A) => unknown) | undefined,
  key: object | null | undefined,
): (...args: A) => unknown {
  const k: object | null | undefined = key || fn;
  return (...args: A) => {
    if (!k) return fn?.(...args);
    const now = Date.now();
    if (now - (nativePressAt.get(k) || 0) < 500) return;
    nativePressAt.set(k, now);
    return fn?.(...args);
  };
}

export function ensureNativeLookStyles(): void {
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition -- findSP() resolves through a webpack probe (see deckyUiInternals); its result's `.window` is not guaranteed at runtime either.
  const doc = findSP()?.window?.document;
  const stat = playSectionClasses?.GameStat;
  if (!doc || !stat) return;
  let style = doc.getElementById("romm-native-look-styles");
  if (!style) {
    style = doc.createElement("style");
    style.id = "romm-native-look-styles";
    doc.head.appendChild(style);
  }
  // RomM stats without Steam's GameStatRight wrapper still stack label over value.
  const container = appActionButtonClasses?.PlayButtonContainer;
  style.textContent =
    `.romm-native-look .${stat} { flex-direction: column; align-items: flex-start; justify-content: center; }` +
    (container
      ? `\n.romm-native-look .${container} { overflow: hidden; }\n.romm-native-look .${container} > button, .romm-native-look .${container} > .romm-btn-cancel { border-radius: 0 !important; }`
      : "");
}

interface NativeMenuButtonProps {
  className?: string;
  onClick?(e: MouseEvent): void;
  onFocus?: (e: { currentTarget: EventTarget | null }) => void;
  title?: string;
  children?: ReactNode;
}

/** A play-section menu button: Steam's MenuButton under the native look, a DialogButton otherwise. */
export function NativeMenuButton(props: NativeMenuButtonProps) {
  if (!nativeLook()) return <DialogButton {...props} />;
  const { onFocus, title, children } = props;
  // Focusable hands over a CustomEvent (onActivate) or React's synthetic click
  // (onClick); the menu handlers only read currentTarget/target, which both carry.
  const onClick = pressOnce(props.onClick as ((...args: unknown[]) => void) | undefined, nativeMenuKey(props.title));
  return (
    <div className={playSectionClasses?.MenuButtonContainer}>
      <Focusable
        className={joinCls(playSectionClasses?.MenuButton, "romm-native-menu-btn")}
        onActivate={onClick}
        onClick={onClick}
        onFocus={onFocus}
        title={title}
      >
        {children}
      </Focusable>
    </div>
  );
}

export const NativeInstallIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="24" height="24" fill="none">
    <path
      d="M18 4v18m0 0l-7-7m7 7l7-7M6 28h24"
      stroke="currentColor"
      strokeWidth="3.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const NativePlayIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="24" height="24" fill="none">
    <path d="M10 6.5v23a1 1 0 0 0 1.5.86l19-11.5a1 1 0 0 0 0-1.72l-19-11.5A1 1 0 0 0 10 6.5z" fill="currentColor" />
  </svg>
);
