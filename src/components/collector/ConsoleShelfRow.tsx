import { FC } from "react";
import { Focusable } from "@decky/ui";
import { useConsoleShelf } from "../../utils/consoleShelfStore";
import { COLLECTOR_CSS } from "./collectorStyles";
import { ConsoleTile } from "./ConsoleTile";

export const SHELF_TITLE = "The Collector";

/**
 * The Home row: one tile per console that has games in Steam, most played first.
 * Reads the shelf store only — nothing here calls the backend — and renders
 * nothing until the store holds at least one console with the row switched on.
 */
export const ConsoleShelfRow: FC = () => {
  const { status, enabled, consoles } = useConsoleShelf();
  if (!enabled || status !== "ready" || consoles.length === 0) return null;
  return (
    <section className="tc-shelf" aria-label={SHELF_TITLE} data-collector-shelf="true">
      <style>{COLLECTOR_CSS}</style>
      <h2 className="tc-shelf__title">{SHELF_TITLE}</h2>
      <Focusable className="tc-shelf__row" flow-children="row">
        {consoles.map((c) => (
          <ConsoleTile key={c.platform_slug} console={c} />
        ))}
      </Focusable>
    </section>
  );
};
