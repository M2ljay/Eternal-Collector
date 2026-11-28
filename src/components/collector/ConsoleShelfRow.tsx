import { CSSProperties, FC, RefObject, useLayoutEffect, useRef, useState } from "react";
import { Focusable } from "@decky/ui";
import { useConsoleShelf } from "../../utils/consoleShelfStore";
import { FALLBACK_GEOMETRY, measureRecentsRow, type RowGeometry } from "../../utils/steamRowGeometry";
import { COLLECTOR_CSS } from "./collectorStyles";
import { CartridgeIcon } from "../icons";
import { openFamily } from "../../utils/familyNavigation";
import { FamilyTile } from "./FamilyTile";

export const SHELF_TITLE = "The Collector";

/** Steam's capsules can still be loading when the row mounts; re-measure a little later too. */
const REMEASURE_DELAYS_MS = [400, 2000];
const LATER_ROWS_SEARCHED = 3;

function sameGeometry(a: RowGeometry, b: RowGeometry): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * The geometry of Steam's Recent games row, read from the element just before the
 * shelf (where the Home patch inserts it) and kept current on resize. Reads the
 * DOM only; never writes to Steam's elements and never calls the backend.
 */
function useSteamRowGeometry(ref: RefObject<HTMLElement | null>, visible: boolean): RowGeometry {
  const [geometry, setGeometry] = useState<RowGeometry>(FALLBACK_GEOMETRY);
  useLayoutEffect(() => {
    const section = ref.current;
    if (!visible || !section) return;
    const row = section.previousElementSibling;
    const view = section.ownerDocument.defaultView;
    const measure = () => {
      let next: RowGeometry | null = null;
      try {
        const later: Element[] = [];
        for (
          let el = section.nextElementSibling;
          el && later.length < LATER_ROWS_SEARCHED;
          el = el.nextElementSibling
        ) {
          later.push(el);
        }
        next = row ? measureRecentsRow(row, later) : null;
      } catch {
        next = null;
      }
      const value = next ?? FALLBACK_GEOMETRY;
      setGeometry((prev) => (sameGeometry(prev, value) ? prev : value));
    };
    measure();
    const timers = REMEASURE_DELAYS_MS.map((ms) => setTimeout(measure, ms));
    view?.addEventListener("resize", measure);
    const Observer = view?.ResizeObserver;
    const observer = row && Observer ? new Observer(measure) : null;
    if (row) observer?.observe(row);
    return () => {
      timers.forEach(clearTimeout);
      view?.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [ref, visible]);
  return geometry;
}

function geometryStyle(g: RowGeometry): CSSProperties {
  const vars: Record<string, string> = {
    "--tc-inset": `${g.inset}px`,
    "--tc-capsule-h": `${g.capsuleHeight}px`,
    "--tc-gap": `${g.gap}px`,
    "--tc-pad-top": `${g.paddingTop}px`,
    "--tc-title-gap": `${g.titleGap}px`,
    "--tc-pad-bottom": `${g.paddingBottom}px`,
  };
  if (g.title) {
    vars["--tc-title-font"] = g.title.fontFamily;
    vars["--tc-title-size"] = g.title.fontSize;
    vars["--tc-title-weight"] = g.title.fontWeight;
    vars["--tc-title-lh"] = g.title.lineHeight;
    vars["--tc-title-ls"] = g.title.letterSpacing;
    vars["--tc-title-tt"] = g.title.textTransform;
  }
  return vars as CSSProperties;
}

/**
 * The Home row: one wide tile per console family the library has games in
 * (PlayStation, Nintendo, Sega, Xbox, Retro), on the lines of Steam's own Recent
 * games row. Reads the shelf store and Steam's DOM only — nothing here calls the
 * backend — and renders nothing until the store holds at least one family with the
 * row switched on.
 */
export const ConsoleShelfRow: FC = () => {
  const { status, enabled, consoles, families, art } = useConsoleShelf();
  const ref = useRef<HTMLElement>(null);
  const visible = enabled && status === "ready" && families.length > 0;
  const geometry = useSteamRowGeometry(ref, visible);
  if (!visible) return null;
  return (
    <section
      ref={ref}
      className="tc-shelf"
      aria-label={SHELF_TITLE}
      data-collector-shelf="true"
      data-geometry={geometry.measured ? "steam" : "fallback"}
      style={geometryStyle(geometry)}
    >
      <style>{COLLECTOR_CSS}</style>
      <h2 className="tc-shelf__title">
        <CartridgeIcon size="1.1em" />
        {SHELF_TITLE}
      </h2>
      <Focusable className="tc-shelf__row" flow-children="row">
        {families.map((family) => (
          <FamilyTile key={family} family={family} art={art[family]} onOpen={() => openFamily(family, consoles)} />
        ))}
      </Focusable>
    </section>
  );
};
