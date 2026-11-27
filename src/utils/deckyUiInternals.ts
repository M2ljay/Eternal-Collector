/**
 * Honest-typed re-exports of @decky/ui internal lookups whose runtime presence
 * isn't guaranteed.
 *
 * @decky/ui populates its class-map consts and `findSP` via `findClassModule` /
 * webpack module probes that can return `undefined` at runtime — its own code
 * even writes `findSP() || window`. Upstream still types them as always-present
 * (`declare const x: T`, `findSP(): Window`), so direct consumers get a lying
 * non-null type and their defensive `?.` guards read as dead code. TS cannot
 * re-type a `const`/function via `declare module` augmentation, so this thin
 * runtime re-export module re-declares each as `T | undefined`, making the
 * guards legitimate.
 *
 * Any future @decky/ui value sourced from a findClassModule-style probe belongs
 * here, typed honestly.
 *
 * @decky/ui is supplied by the loader at runtime: 4.x under Decky 3.3.1 (webpack
 * Steam), 5.x under Decky 4.0 (ES-module Steam, renamed classes). A class module
 * the named export misses is looked up again by key, so either loader works and
 * a miss only turns the dependent feature off.
 */

import * as DeckyUi from "@decky/ui";
import {
  appActionButtonClasses as _appActionButtonClasses,
  basicAppDetailsSectionStylerClasses as _basicAppDetailsSectionStylerClasses,
  appDetailsClasses as _appDetailsClasses,
  playSectionClasses as _playSectionClasses,
  findSP as _findSP,
} from "@decky/ui";

type ModuleFilter = (value: unknown) => boolean;
type ModuleFinder = (filter: ModuleFilter) => unknown;

const missingLookups: string[] = [];

/** A finder the loader's @decky/ui offers, or undefined: `findVar` exists only in 5.x (Decky 4.0). */
function deckyUiFinder(name: "findClassModule" | "findVar"): ModuleFinder | undefined {
  try {
    const value: unknown = (DeckyUi as Record<string, unknown>)[name];
    return typeof value === "function" ? (value as ModuleFinder) : undefined;
  } catch {
    // A vitest factory mock throws on an export it does not define.
    return undefined;
  }
}

/**
 * The named @decky/ui class module, else the first class module carrying every
 * key — by `findClassModule`, then by module-scope `findVar`. Undefined, and
 * recorded in {@link missingDeckyUiLookups}, when no lookup finds one.
 */
export function resolveClassModule<T extends object>(
  name: string,
  named: T | undefined,
  keys: readonly string[],
): T | undefined {
  if (named) return named;
  const filter: ModuleFilter = (value) =>
    typeof value === "object" &&
    value !== null &&
    keys.every((key) => typeof (value as Record<string, unknown>)[key] === "string");
  for (const finderName of ["findClassModule", "findVar"] as const) {
    const find = deckyUiFinder(finderName);
    if (!find) continue;
    try {
      const found = find(filter);
      if (filter(found)) return found as T;
    } catch {
      // A probe can throw on a module with hostile getters; the next finder may still answer.
    }
  }
  missingLookups.push(name);
  return undefined;
}

/** Names of the class modules no lookup could find on this Steam build. */
export function missingDeckyUiLookups(): readonly string[] {
  return missingLookups;
}

// Keys are the ones @decky/ui 4's own findClassModule filters use.
export const appActionButtonClasses: typeof _appActionButtonClasses | undefined = resolveClassModule(
  "appActionButtonClasses",
  _appActionButtonClasses,
  ["PlayButtonContainer"],
);
export const basicAppDetailsSectionStylerClasses: typeof _basicAppDetailsSectionStylerClasses | undefined =
  resolveClassModule("basicAppDetailsSectionStylerClasses", _basicAppDetailsSectionStylerClasses, ["AppDetailsRoot"]);
export const appDetailsClasses: typeof _appDetailsClasses | undefined = resolveClassModule(
  "appDetailsClasses",
  _appDetailsClasses,
  ["HeaderLoaded"],
);
export const playSectionClasses: typeof _playSectionClasses | undefined = resolveClassModule(
  "playSectionClasses",
  _playSectionClasses,
  ["PlayBarDetailLabel"],
);

export const findSP = (): Window | undefined => {
  try {
    return _findSP();
  } catch {
    return undefined;
  }
};
