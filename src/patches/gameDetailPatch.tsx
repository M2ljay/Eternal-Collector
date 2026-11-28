/**
 * React-tree patch that swaps Steam's native app-details overview panel for
 * our RomMPlaySection + RomMGameInfoPanel pair on RomM shortcuts. Everything
 * here walks Steam's internal React tree — node shapes are dynamic and shift
 * between Steam builds, so `any` is the honest type. Per #617, narrowing
 * predicates here buy almost no safety for several lines of churn per site,
 * so the file is exempt from `@typescript-eslint/no-explicit-any`.
 */

import { routerHook } from "@decky/api";
import { afterPatch, findInReactTree, createReactTreePatcher } from "@decky/ui";
import { appDetailsClasses, missingDeckyUiLookups } from "../utils/deckyUiInternals";
import { nativeLook } from "../utils/nativeLook";
import { GAME_VIEW_CLASS } from "../utils/corePageStyles";
import { RomMPlaySection } from "../components/RomMPlaySection";
import { RomMGameInfoPanel } from "../components/RomMGameInfoPanel";
import { debugLog, logWarn } from "../api/backend";
import type { RoutePatch } from "@decky/api";
import { detach } from "../utils/detach";

// Cached set of RomM app IDs — updated by registerRomMAppId
const rommAppIds = new Set<number>();

/**
 * Locate the InnerContainer node in Steam's app-details React subtree: by its
 * class-map class, else as the node whose children hold the native overview
 * panel. Returns the matched node (with an array `children` prop) or
 * null/undefined.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
export function findInsertionPoint(ret: any): any {
  const innerContainerClass = appDetailsClasses?.InnerContainer;
  const byClass = innerContainerClass
    ? findInReactTree(
        ret,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
        (x: any) => Array.isArray(x?.props?.children) && x?.props?.className?.includes?.(innerContainerClass),
      )
    : undefined;
  if (byClass) return byClass;
  // A class map can lag a Steam build (Decky 4.0's @decky/ui 5 pins class names
  // per CLSTAMP); the overview panel's props are not renamed with the classes.
  return findInReactTree(
    ret,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
    (x: any) => Array.isArray(x?.props?.children) && findNativeOverviewIndex(x.props.children) >= 0,
  );
}

/** The class our wrapper borrows to sit in InnerContainer's layout like the native panel. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
export function overviewPanelClass(children: any[], nativeOverviewIdx: number): string {
  const mapped = appDetailsClasses?.AppDetailsOverviewPanel;
  if (mapped) return mapped;
  const native: unknown = nativeOverviewIdx >= 0 ? children[nativeOverviewIdx]?.props?.className : undefined;
  return typeof native === "string" ? native : "";
}

/**
 * Locate the native AppDetailsOverviewPanel index among the InnerContainer's
 * children. Identified by children whose props carry details + overview +
 * bFastRender. Returns -1 if not found.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
export function findNativeOverviewIndex(children: any[]): number {
  for (let i = 0; i < children.length; i++) {
    const cp = children[i]?.props?.children?.props || {};
    if (cp.details && cp.overview && cp.bFastRender !== undefined) {
      return i;
    }
  }
  return -1;
}

/**
 * The element put in place of Steam's overview panel. It carries the native
 * panel's class so it takes part in InnerContainer's flex layout and scroll
 * system the way the native panel does. Under the Windows look it is also the
 * game view (`utils/corePageStyles.ts`): screen one's play bar, then screen two,
 * the black Core page the info panel draws.
 */
export function rommPageWrapper(appId: number, panelClass: string, corePage: boolean) {
  return (
    <div
      key="romm-play-section"
      className={corePage ? `${panelClass} ${GAME_VIEW_CLASS}`.trim() : panelClass}
      data-romm="true"
    >
      <RomMPlaySection key="romm-play-section" appId={appId} />
      <RomMGameInfoPanel key="romm-info-panel" appId={appId} />
    </div>
  );
}

export function registerRomMAppId(appId: number) {
  rommAppIds.add(appId);
}

export function unregisterRomMAppId(appId: number) {
  rommAppIds.delete(appId);
}

export function isRomMAppId(appId: number): boolean {
  return rommAppIds.has(appId);
}

let gamePatch: RoutePatch | null = null;

export function registerGameDetailPatch() {
  const missing = missingDeckyUiLookups();
  if (missing.length > 0) {
    logWarn(`gameDetailPatch: class modules not found on this Steam build: ${missing.join(", ")}`);
  }
  gamePatch = routerHook.addPatch(
    "/library/app/:appid",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
    (tree: any) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
      const routeProps = findInReactTree(tree, (x: any) => x?.renderFunc);
      if (routeProps) {
        const patchHandler = createReactTreePatcher(
          [
            // Navigate to the node whose children carry the overview prop
            // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
            (node: any) =>
              findInReactTree(
                node,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
                (x: any) => x?.props?.children?.props?.overview,
              )?.props?.children,
          ],
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
          (_args: unknown[], ret?: any) => {
            const container = findInsertionPoint(ret);
            if (typeof container !== "object" || !container) {
              return ret;
            }

            // Extract appId from the overview object higher up in the tree
            const overviewNode = findInReactTree(
              ret,
              // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
              (x: any) => x?.props?.overview?.appid,
            );
            const appId: number | undefined = overviewNode?.props?.overview?.appid;

            if (!appId) {
              return ret;
            }

            // Only apply RomM modifications for RomM shortcuts
            const isRomM = rommAppIds.has(appId);
            detach(debugLog(`gameDetailPatch: appId=${appId} isRomM=${isRomM} setSize=${rommAppIds.size}`));

            // For RomM games: replace the native AppDetailsOverviewPanel
            // (which renders Play button + tabs + all native content via `se`)
            // with our RomMPlaySection and RomMGameInfoPanel.
            if (isRomM) {
              const children = container.props.children;

              // Deduplication: don't inject if already present
              const alreadyHasPlayBtn = children.some(
                // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Steam internal React tree; runtime shape is dynamic, no upstream types ship
                (c: any) => c?.key === "romm-play-section",
              );
              if (!alreadyHasPlayBtn) {
                const nativeOverviewIdx = findNativeOverviewIndex(children);

                const panelClass = overviewPanelClass(children, nativeOverviewIdx);
                const rommWrapper = rommPageWrapper(appId, panelClass, nativeLook());

                if (nativeOverviewIdx >= 0) {
                  detach(
                    debugLog(
                      `gameDetailPatch: replacing AppDetailsOverviewPanel at index ${nativeOverviewIdx} with RomM wrapper (cls=${panelClass})`,
                    ),
                  );
                  children.splice(nativeOverviewIdx, 1, rommWrapper);
                } else {
                  detach(
                    debugLog(`gameDetailPatch: AppDetailsOverviewPanel not found, inserting RomM wrapper at index 1`),
                  );
                  children.splice(1, 0, rommWrapper);
                }
              }
            }

            return ret;
          },
          "RomMGameDetail",
        );

        afterPatch(routeProps, "renderFunc", patchHandler);
      }

      return tree;
    },
  );
}

export function unregisterGameDetailPatch() {
  if (gamePatch) {
    routerHook.removePatch("/library/app/:appid", gamePatch);
    gamePatch = null;
  }
}
