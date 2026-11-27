/**
 * The ROM game page's extension registry — `window.__eternalGamePage`.
 *
 * Other Decky plugins (Forge first) add a tab or an Overview card to the game
 * page The Collector draws for its ROMs, without reaching into its internals.
 * Contract, versioning and what an extension may do:
 * `docs/architecture/game-mods.md#forge-bridge`.
 *
 * Registration is a subscribe-based store: a plugin may register before the
 * page exists or while it is on screen, and every mounted page re-renders on
 * each change. Every snapshot is a NEW array, so it can serve as a
 * `useSyncExternalStore` snapshot. Nothing here renders an extension; the
 * panel does, each one inside its own error boundary.
 */

import { useSyncExternalStore, type ReactNode } from "react";
import { logError, logWarn } from "../api/backend";

export const GAME_PAGE_GLOBAL = "__eternalGamePage";
/** Dispatched on `window` each time the registry is installed, so a plugin that loaded first can register. */
export const GAME_PAGE_READY_EVENT = "eternal_game_page_ready";
export const GAME_PAGE_VERSION = 1;

/** The extension id whose presence replaces The Collector's own Mods button. */
export const FORGE_MODS_EXTENSION_ID = "forge.mods";

/** Tab order of The Collector's own tabs. Overview (GAME INFO) is always first, whatever an extension asks for. */
export const BUILTIN_TAB_ORDER = { info: 0, achievements: 20, saves: 30, media: 34, details: 37, bios: 40 } as const;
/** Where an extension tab without an `order` goes: after every built-in tab. */
export const DEFAULT_EXTENSION_ORDER = 100;

export interface RomPageContext {
  readonly appId: number;
  readonly romId: number;
  readonly name: string;
  readonly platformSlug: string;
  readonly platformName: string;
  readonly installed: boolean;
  readonly locale: string;
  /** Switch the page to the tab a registered extension contributed (by its `id`); unknown ids are ignored. */
  readonly openTab?: (extensionId: string) => void;
}

export type GamePageExtensionKind = "tab" | "overviewCard";

export interface GamePageExtension {
  readonly id: string;
  readonly kind: GamePageExtensionKind;
  readonly label: string | ((locale: string) => string);
  readonly order?: number;
  readonly isAvailable?: (ctx: RomPageContext) => boolean;
  readonly render: (ctx: RomPageContext) => ReactNode;
  readonly subscribe?: (onChange: () => void) => () => void;
}

/** One registration as the panel sees it. `revision` moves when the extension's own `subscribe` fires. */
export interface RegisteredExtension {
  readonly extension: GamePageExtension;
  readonly seq: number;
  readonly revision: number;
}

export interface GamePageRegistryGlobal {
  readonly version: number;
  register(ext: GamePageExtension): () => void;
  list(): ReadonlyArray<{ id: string; kind: string }>;
}

interface Slot {
  readonly token: symbol;
  readonly extension: GamePageExtension;
  readonly seq: number;
  revision: number;
  teardown: (() => void) | null;
}

let slots: Slot[] = [];
let snapshot: readonly RegisteredExtension[] = [];
let seqCounter = 0;
const listeners = new Set<() => void>();

function publish(): void {
  snapshot = slots.map((s) => ({ extension: s.extension, seq: s.seq, revision: s.revision }));
  for (const fn of [...listeners]) fn();
}

function invalidReason(ext: unknown): string | null {
  if (typeof ext !== "object" || ext === null) return "not an object";
  const e = ext as Partial<GamePageExtension>;
  if (typeof e.id !== "string" || e.id.trim() === "") return "id must be a non-empty string";
  if (e.kind !== "tab" && e.kind !== "overviewCard") return `${e.id}: kind must be "tab" or "overviewCard"`;
  if (typeof e.label !== "string" && typeof e.label !== "function")
    return `${e.id}: label must be a string or function`;
  if (typeof e.render !== "function") return `${e.id}: render must be a function`;
  if (e.order !== undefined && (typeof e.order !== "number" || !Number.isFinite(e.order)))
    return `${e.id}: order must be a finite number`;
  if (e.isAvailable !== undefined && typeof e.isAvailable !== "function")
    return `${e.id}: isAvailable must be a function`;
  if (e.subscribe !== undefined && typeof e.subscribe !== "function") return `${e.id}: subscribe must be a function`;
  return null;
}

function runTeardown(slot: Slot): void {
  const teardown = slot.teardown;
  slot.teardown = null;
  if (!teardown) return;
  try {
    teardown();
  } catch (e) {
    logError(`Game page extension ${slot.extension.id}: unsubscribe threw: ${e}`);
  }
}

/**
 * Add an extension to every ROM game page. A second registration with the same
 * id replaces the first (a plugin that reloads registers again). Returns the
 * unregister function, which removes only this registration. An invalid
 * extension is refused with a warning and gets a no-op unregister.
 */
export function registerGamePageExtension(ext: GamePageExtension): () => void {
  const reason = invalidReason(ext);
  if (reason !== null) {
    logWarn(`Game page extension refused: ${reason}`);
    return () => {};
  }
  const replaced = slots.find((s) => s.extension.id === ext.id);
  if (replaced) runTeardown(replaced);
  const slot: Slot = { token: Symbol(ext.id), extension: ext, seq: ++seqCounter, revision: 0, teardown: null };
  slots = [...slots.filter((s) => s !== replaced), slot];
  if (ext.subscribe) {
    try {
      slot.teardown = ext.subscribe(() => {
        if (!slots.includes(slot)) return;
        slot.revision += 1;
        publish();
      });
    } catch (e) {
      logError(`Game page extension ${ext.id}: subscribe threw: ${e}`);
    }
  }
  publish();
  return () => {
    if (!slots.includes(slot)) return;
    runTeardown(slot);
    slots = slots.filter((s) => s.token !== slot.token);
    publish();
  };
}

export function listGamePageExtensions(): ReadonlyArray<{ id: string; kind: string }> {
  return snapshot.map((r) => ({ id: r.extension.id, kind: r.extension.kind }));
}

export function getGamePageExtensions(): readonly RegisteredExtension[] {
  return snapshot;
}

export function onGamePageExtensionsChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useGamePageExtensions(): readonly RegisteredExtension[] {
  return useSyncExternalStore(onGamePageExtensionsChange, getGamePageExtensions);
}

export function hasGamePageExtension(entries: readonly RegisteredExtension[], id: string): boolean {
  return entries.some((r) => r.extension.id === id);
}

/** The label an extension shows for *locale*, or its id when its label function throws or answers nothing. */
export function extensionLabel(ext: GamePageExtension, locale: string): string {
  if (typeof ext.label === "string") return ext.label || ext.id;
  try {
    const text = ext.label(locale);
    return typeof text === "string" && text ? text : ext.id;
  } catch (e) {
    logError(`Game page extension ${ext.id}: label threw: ${e}`);
    return ext.id;
  }
}

function available(ext: GamePageExtension, ctx: RomPageContext): boolean {
  if (!ext.isAvailable) return true;
  try {
    return ext.isAvailable(ctx) === true;
  } catch (e) {
    logError(`Game page extension ${ext.id}: isAvailable threw: ${e}`);
    return false;
  }
}

/**
 * The extensions of *kind* that answer available for *ctx*, ordered by `order`
 * (default {@link DEFAULT_EXTENSION_ORDER}) and then by registration.
 */
export function visibleExtensions(
  entries: readonly RegisteredExtension[],
  kind: GamePageExtensionKind,
  ctx: RomPageContext,
): RegisteredExtension[] {
  return entries
    .filter((r) => r.extension.kind === kind && available(r.extension, ctx))
    .sort(
      (a, b) =>
        (a.extension.order ?? DEFAULT_EXTENSION_ORDER) - (b.extension.order ?? DEFAULT_EXTENSION_ORDER) ||
        a.seq - b.seq,
    );
}

/** The `activeTab` value an extension tab is selected under; prefixed so it can never collide with a built-in tab. */
export function extensionTabKey(id: string): string {
  return `ext:${id}`;
}

/**
 * Publish the registry on `window` and announce it. Returns the uninstall
 * function: it withdraws the global (only if it is still this one) and drops
 * every registration, running each extension's unsubscribe.
 */
export function installGamePageRegistry(): () => void {
  const api: GamePageRegistryGlobal = Object.freeze({
    version: GAME_PAGE_VERSION,
    register: registerGamePageExtension,
    list: listGamePageExtensions,
  });
  const target = globalThis as unknown as Record<string, unknown>;
  target[GAME_PAGE_GLOBAL] = api;
  globalThis.dispatchEvent(new CustomEvent(GAME_PAGE_READY_EVENT, { detail: { version: GAME_PAGE_VERSION } }));
  return () => {
    if (target[GAME_PAGE_GLOBAL] === api) delete target[GAME_PAGE_GLOBAL];
    for (const slot of slots) runTeardown(slot);
    slots = [];
    publish();
  };
}

/** Test-only: forget every registration without running teardowns. */
export function _resetGamePageExtensionsForTests(): void {
  slots = [];
  seqCounter = 0;
  publish();
}
