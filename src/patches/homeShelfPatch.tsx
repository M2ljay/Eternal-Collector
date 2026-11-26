/**
 * Inserts The Collector's console shelf under Steam's own "Recent games" row on
 * Big Picture's Home.
 *
 * Technique: a `/library/home` route patch. Home's own components are wrapped so
 * their rendered output can be read, the Recent games row is recognised in that
 * output **by its props**, and the shelf is added as its next sibling. The shelf
 * is then a real child of Steam's Home tree, so gamepad focus, scrolling and Back
 * work as for a native row. The roads not taken — a DOM portal with focus-tree
 * surgery, and hijacking hooks through React internals — and the reasons are in
 * docs/architecture/home-console-shelf.md.
 *
 * Every Steam element is copied, never mutated, and every failure — an
 * unrecognised tree, an exception, a render error in the shelf — leaves Home
 * exactly as Steam rendered it. After {@link MAX_FAILURES} failures the patch
 * switches itself off until the plugin loads again.
 *
 * The Recent games recognition is not verified on every Steam build:
 * {@link RECENTS_ROW_MATCHERS} and {@link HOME_DESCENT_STEPS} are the knobs, and
 * the patch logs which matcher hit, or what it saw when none did.
 *
 * Steam's tree has no published types, so `any` is the honest type here, as in
 * gameDetailPatch.tsx.
 */
/* eslint-disable @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship */

import { routerHook } from "@decky/api";
import { Component, cloneElement, createElement, forwardRef, isValidElement, memo, type ReactNode } from "react";
import { debugLog, logInfo, logWarn } from "../api/backend";
import { ConsoleShelfRow } from "../components/collector/ConsoleShelfRow";
import { getConsoleShelfState } from "../utils/consoleShelfStore";
import { detach } from "../utils/detach";

export const HOME_ROUTE = "/library/home";
export const SHELF_KEY = "collector-console-shelf";

export interface RowMatcher {
  name: string;
  test: (props: any) => boolean;
}

/**
 * How Steam's Recent games row is recognised, most specific first. Both are props
 * contracts, never class names or positions:
 * - `recents-section`: the row's section element, which takes `showBackground`
 *   and `autoFocus`. The same contract recognises the row in the Core plugin's
 *   `storeInstallRecents.tsx` and Deck Shelves' `recentsRowPatch.ts`.
 * - `recents-carousel`: the row's tile list (`games[]`, `onItemFocus`,
 *   `showFeaturedItem`), used when the section wrapper is not in the output that
 *   was read; the shelf then lands right after the tile list.
 */
export const RECENTS_ROW_MATCHERS: RowMatcher[] = [
  {
    name: "recents-section",
    test: (p) => p != null && typeof p === "object" && "showBackground" in p && "autoFocus" in p,
  },
  {
    name: "recents-carousel",
    test: (p) =>
      p != null &&
      typeof p === "object" &&
      Array.isArray(p.games) &&
      typeof p.onItemFocus === "function" &&
      "showFeaturedItem" in p,
  },
];

/**
 * How many component layers below the route element are wrapped and searched.
 * The route renders a Home component that renders the component holding the
 * rows; the Core plugin's Home patches descend the same two layers.
 */
export const HOME_DESCENT_STEPS = 2;

export const MAX_FAILURES = 3;
const MAX_DEPTH = 32;
const NODE_BUDGET = 4000;
const MISS_REPORT_DELAY_MS = 8000;

// ── Diagnostics and the failure watchdog ────────────────────────────────────

interface PatchDiagnostics {
  active: boolean;
  failures: number;
  disabled: boolean;
  matchedBy: string | null;
  lastSeen: string[];
}

const diagnostics: PatchDiagnostics = {
  active: false,
  failures: 0,
  disabled: false,
  matchedBy: null,
  lastSeen: [],
};
let missTimer: ReturnType<typeof setTimeout> | null = null;

export function getHomeShelfDiagnostics(): Readonly<PatchDiagnostics> {
  return diagnostics;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Count one failure; the third switches the patch off for the session. */
export function recordShelfFailure(where: string, error: unknown): void {
  diagnostics.failures += 1;
  logWarn(`The Collector: Home shelf ${where} failed (${diagnostics.failures}/${MAX_FAILURES}): ${errorText(error)}`);
  if (diagnostics.failures >= MAX_FAILURES && !diagnostics.disabled) {
    diagnostics.disabled = true;
    logWarn("The Collector: Home shelf switched off until the plugin reloads; Steam's Home is shown untouched.");
  }
}

function patchLive(): boolean {
  return diagnostics.active && !diagnostics.disabled;
}

function typeName(node: any): string {
  const type = node?.type;
  if (typeof type === "string") return type;
  return type?.displayName || type?.name || type?.type?.displayName || type?.type?.name || "(anonymous)";
}

/** A compact outline of an output tree: one line per element, its type and prop names. */
export function describeTree(tree: any, maxDepth = 5, maxLines = 60): string[] {
  const lines: string[] = [];
  const visit = (node: any, depth: number) => {
    if (lines.length >= maxLines || depth > maxDepth) return;
    if (Array.isArray(node)) {
      node.forEach((child) => visit(child, depth));
      return;
    }
    if (!isValidElement(node)) return;
    const props = (node.props ?? {}) as Record<string, unknown>;
    const keys = Object.keys(props)
      .filter((k) => k !== "children")
      .slice(0, 12)
      .join(",");
    lines.push(`${"  ".repeat(depth)}${typeName(node)} key=${String(node.key)} props=[${keys}]`);
    visit(props.children, depth + 1);
  };
  visit(tree, 0);
  return lines;
}

function noteMatch(name: string): void {
  if (diagnostics.matchedBy === name) return;
  diagnostics.matchedBy = name;
  logInfo(`The Collector: Recent games row found on Home (matcher "${name}"); shelf inserted below it.`);
}

function scheduleMissReport(): void {
  if (missTimer !== null || diagnostics.matchedBy !== null) return;
  missTimer = setTimeout(() => {
    if (diagnostics.matchedBy !== null || !diagnostics.active) return;
    logWarn(
      "The Collector: Steam's Recent games row was not found on Home, so the console shelf is not shown " +
        `(matchers: ${RECENTS_ROW_MATCHERS.map((m) => m.name).join(", ")}; descent ${HOME_DESCENT_STEPS}). ` +
        "The outline of what was seen follows in the debug log.",
    );
    for (const line of diagnostics.lastSeen) detach(debugLog(`The Collector home tree: ${line}`));
  }, MISS_REPORT_DELAY_MS);
}

// ── Finding the row and inserting after it (copy-on-write) ──────────────────

interface Search {
  budget: number;
}

interface Insertion {
  value: any;
  done: boolean;
}

/**
 * Walk a `children` value (an element, an array, or anything else React renders)
 * and insert `extra` right after the first element `matcher` accepts. `done` stops
 * the walk; it is also set, with the value unchanged, when the shelf is already
 * present, so a re-render never adds a second one.
 */
function insertInChildren(
  children: any,
  matcher: RowMatcher,
  extra: ReactNode,
  search: Search,
  depth: number,
): Insertion {
  if (depth > MAX_DEPTH || search.budget <= 0) return { value: children, done: false };
  if (Array.isArray(children)) {
    if (children.some((c) => isValidElement(c) && c.key === SHELF_KEY)) return { value: children, done: true };
    for (let i = 0; i < children.length; i++) {
      const child = children[i];
      if (isValidElement<any>(child) && matcher.test(child.props)) {
        return { value: [...children.slice(0, i + 1), extra, ...children.slice(i + 1)], done: true };
      }
      const inner = insertInChildren(child, matcher, extra, search, depth + 1);
      if (inner.done) {
        if (inner.value === child) return { value: children, done: true };
        const next = [...children];
        next[i] = inner.value;
        return { value: next, done: true };
      }
    }
    return { value: children, done: false };
  }
  if (!isValidElement<any>(children)) return { value: children, done: false };
  search.budget -= 1;
  const own = children.props?.children;
  if (own === undefined || own === null) return { value: children, done: false };
  if (isValidElement<any>(own) && !Array.isArray(own)) {
    if (own.key === SHELF_KEY) return { value: children, done: true };
    if (matcher.test(own.props)) return { value: cloneElement(children, undefined, own, extra), done: true };
  }
  const inner = insertInChildren(own, matcher, extra, search, depth + 1);
  if (!inner.done || inner.value === own) return { value: children, done: inner.done };
  // Children passed as separate arguments, as JSX passes them: handing React the
  // edited array as one `children` value would make it a keyed list it is not.
  const next = Array.isArray(inner.value)
    ? cloneElement(children, undefined, ...inner.value)
    : cloneElement(children, undefined, inner.value);
  return { value: next, done: true };
}

/**
 * Return `tree` with `extra` inserted after the first element a matcher accepts,
 * trying the matchers in order, and the matcher's name. Returns the input itself
 * and `null` when nothing matched, and the input unchanged with the matcher's name
 * when the shelf is already there.
 */
export function insertAfterRecentsRow(
  tree: any,
  extra: ReactNode,
  matchers: RowMatcher[] = RECENTS_ROW_MATCHERS,
): { tree: any; matchedBy: string | null } {
  for (const matcher of matchers) {
    if (isValidElement<any>(tree) && matcher.test(tree.props)) return { tree: [tree, extra], matchedBy: matcher.name };
    const result = insertInChildren(tree, matcher, extra, { budget: NODE_BUDGET }, 0);
    if (result.done) return { tree: result.value, matchedBy: matcher.name };
  }
  return { tree, matchedBy: null };
}

// ── Reading Home's rendered output (component wrapping) ─────────────────────

type OutputHook = (output: any) => any;
const wrapperCaches: WeakMap<object, any>[] = [];

function cacheFor(stage: number): WeakMap<object, any> {
  wrapperCaches[stage] ??= new WeakMap();
  return wrapperCaches[stage];
}

function copyStatics(source: any, target: any): any {
  for (const key of ["displayName", "defaultProps", "contextType"]) {
    if (source[key] !== undefined) target[key] = source[key];
  }
  return target;
}

const MEMO = Symbol.for("react.memo");
const FORWARD_REF = Symbol.for("react.forward_ref");

/**
 * A component type that renders like `type` and passes its output through `hook`.
 * Cached per stage so React sees one stable type per original and never remounts
 * Home on a re-render. Types it cannot wrap safely (lazy, providers, strings) are
 * returned unchanged.
 */
export function wrapComponentType(type: any, stage: number, hook: OutputHook): any {
  if (!type || (typeof type !== "function" && typeof type !== "object")) return type;
  const cache = cacheFor(stage);
  const cached = cache.get(type);
  if (cached) return cached;
  let wrapped: any;
  if (typeof type === "function") {
    if (type.prototype?.isReactComponent) {
      wrapped = class extends type {
        render() {
          return hook(super.render());
        }
      };
    } else {
      wrapped = function CollectorOutput(this: any, ...args: any[]) {
        return hook(type.apply(this, args));
      };
    }
    copyStatics(type, wrapped);
  } else if (type.$$typeof === MEMO) {
    const inner = wrapComponentType(type.type, stage, hook);
    wrapped = inner === type.type ? type : memo(inner, type.compare);
  } else if (type.$$typeof === FORWARD_REF && typeof type.render === "function") {
    wrapped = forwardRef(function CollectorForwardRef(props: any, ref: any) {
      return hook(type.render(props, ref));
    });
  } else {
    return type;
  }
  cache.set(type, wrapped);
  cache.set(wrapped, wrapped);
  return wrapped;
}

function withType(node: any, type: any): any {
  if (node.type === type) return node;
  const props: any = { ...node.props };
  if (node.key !== null && node.key !== undefined) props.key = node.key;
  // React 19 keeps `ref` in props; React 18 keeps it on the element. Read the
  // element's own data property rather than its getter, which warns under 19.
  const legacyRef = Object.getOwnPropertyDescriptor(node, "ref");
  if (!("ref" in props) && legacyRef && "value" in legacyRef && legacyRef.value != null) props.ref = legacyRef.value;
  return createElement(type, props);
}

/** Replace the type of the first composite element(s) in `tree` (depth-first) with a wrapper. */
function wrapFirstComposite(tree: any, stage: number, hook: OutputHook, depth = 0): any {
  if (depth > MAX_DEPTH) return tree;
  if (Array.isArray(tree)) {
    const next = tree.map((n) => wrapFirstComposite(n, stage, hook, depth + 1));
    return next.some((n, i) => n !== tree[i]) ? next : tree;
  }
  if (!isValidElement<any>(tree)) return tree;
  if (typeof tree.type !== "string") {
    const wrapped = wrapComponentType(tree.type, stage, hook);
    return wrapped === tree.type ? tree : withType(tree, wrapped);
  }
  const children = tree.props?.children;
  if (children === undefined) return tree;
  const next = wrapFirstComposite(children, stage, hook, depth + 1);
  return next === children ? tree : cloneElement(tree, undefined, next);
}

class ShelfBoundary extends Component<{ children?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    recordShelfFailure("render", error);
  }
  render() {
    return this.state.failed || !patchLive() ? null : this.props.children;
  }
}

function shelfElement(): ReactNode {
  return createElement(ShelfBoundary, { key: SHELF_KEY }, createElement(ConsoleShelfRow));
}

function rememberSeen(output: any): void {
  if (diagnostics.matchedBy === null && diagnostics.lastSeen.length === 0) {
    diagnostics.lastSeen = describeTree(output);
  }
}

/** The output hook of one descent stage: wrap the next layer, then try to insert. */
function stageHook(stage: number): OutputHook {
  return (output) => {
    if (!patchLive()) return output;
    try {
      const descended =
        stage + 1 < HOME_DESCENT_STEPS ? wrapFirstComposite(output, stage + 1, stageHook(stage + 1)) : output;
      if (!getConsoleShelfState().enabled) return descended;
      const { tree, matchedBy } = insertAfterRecentsRow(descended, shelfElement());
      if (matchedBy) {
        noteMatch(matchedBy);
        return tree;
      }
      if (stage + 1 === HOME_DESCENT_STEPS) {
        rememberSeen(output);
        scheduleMissReport();
      }
      return descended;
    } catch (error) {
      recordShelfFailure("patch", error);
      return output;
    }
  };
}

let routePatch: ReturnType<typeof routerHook.addPatch> | null = null;

/** Patch Home. Idempotent; the matching unregister restores Steam's Home. */
export function registerHomeShelfPatch(): void {
  if (routePatch) return;
  diagnostics.active = true;
  routePatch = routerHook.addPatch(HOME_ROUTE, (props: any) => {
    if (!patchLive() || !props?.children) return props;
    try {
      const children = wrapFirstComposite(props.children, 0, stageHook(0));
      return children === props.children ? props : { ...props, children };
    } catch (error) {
      recordShelfFailure("route", error);
      return props;
    }
  });
}

export function unregisterHomeShelfPatch(): void {
  diagnostics.active = false;
  if (missTimer !== null) {
    clearTimeout(missTimer);
    missTimer = null;
  }
  if (routePatch) {
    routerHook.removePatch(HOME_ROUTE, routePatch);
    routePatch = null;
  }
}

/** Test-only: forget failures, matches and wrapper caches. */
export function resetHomeShelfPatchForTests(): void {
  unregisterHomeShelfPatch();
  diagnostics.failures = 0;
  diagnostics.disabled = false;
  diagnostics.matchedBy = null;
  diagnostics.lastSeen = [];
  wrapperCaches.length = 0;
}
