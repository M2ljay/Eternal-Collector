/**
 * Rendering of other plugins' game page extensions (`utils/gamePageExtensions.ts`):
 * the Overview cards and the body of an extension tab.
 *
 * Each extension renders inside its own error boundary, keyed by the extension,
 * its registration and the ROM, so a throwing extension is hidden and logged
 * without touching the page or its neighbours, and gets a fresh try on the next
 * ROM or the next registration. An extension's components come from another
 * plugin's bundle; they work here only because every Decky plugin takes React
 * from the one shared `window.SP_REACT` (see the Forge bridge doc).
 */

import { Component, type FC, type ReactNode } from "react";
import { Focusable } from "@decky/ui";
import { logError } from "../api/backend";
import {
  extensionLabel,
  visibleExtensions,
  type RegisteredExtension,
  type RomPageContext,
} from "../utils/gamePageExtensions";

interface BoundaryProps {
  readonly extensionId: string;
  readonly children?: ReactNode;
}

export class ExtensionBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    logError(`Game page extension ${this.props.extensionId} failed to render and is hidden: ${error}`);
  }

  render() {
    return this.state.failed ? null : (this.props.children ?? null);
  }
}

/** Calls the extension's `render` inside the boundary, so a throw from `render` itself is caught too. */
const ExtensionBody: FC<{ entry: RegisteredExtension; ctx: RomPageContext }> = ({ entry, ctx }) => (
  <>{entry.extension.render(ctx)}</>
);

function boundaryKey(entry: RegisteredExtension, ctx: RomPageContext): string {
  return `${entry.extension.id}:${entry.seq}:${ctx.romId}`;
}

/** The Overview card grid: The Collector's own cards (`children`) first, then the registered ones. */
export const ExtensionOverviewCards: FC<{
  entries: readonly RegisteredExtension[];
  ctx: RomPageContext;
  children?: ReactNode;
}> = ({ entries, ctx, children }) => {
  const cards = visibleExtensions(entries, "overviewCard", ctx);
  if (cards.length === 0 && !children) return null;
  return (
    <Focusable className="romm-ext-cards romm-core-cards" flow-children="row" data-romm="true">
      {children}
      {cards.map((entry) => (
        <div
          key={boundaryKey(entry, ctx)}
          className="romm-ext-card"
          data-extension-id={entry.extension.id}
          aria-label={extensionLabel(entry.extension, ctx.locale)}
        >
          <ExtensionBoundary extensionId={entry.extension.id}>
            <ExtensionBody entry={entry} ctx={ctx} />
          </ExtensionBoundary>
        </div>
      ))}
    </Focusable>
  );
};

export const ExtensionTabPane: FC<{ entry: RegisteredExtension; ctx: RomPageContext }> = ({ entry, ctx }) => (
  <div className="romm-ext-tab" data-extension-id={entry.extension.id}>
    <ExtensionBoundary key={boundaryKey(entry, ctx)} extensionId={entry.extension.id}>
      <ExtensionBody entry={entry} ctx={ctx} />
    </ExtensionBoundary>
  </div>
);
