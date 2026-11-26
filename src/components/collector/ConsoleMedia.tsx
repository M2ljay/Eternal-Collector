import { FC } from "react";
import { mediaKindFor, stackSize } from "../../utils/consoleMedia";

/** A console's media drawn as a CSS stack: plain shapes, no logos or artwork. */
export const ConsoleMedia: FC<{ platformSlug: string; gameCount: number }> = ({ platformSlug, gameCount }) => {
  const kind = mediaKindFor(platformSlug);
  const items = Array.from({ length: stackSize(kind, gameCount) }, (_, i) => i);
  return (
    <div className={`tc-media tc-media--${kind}`} data-media-kind={kind} aria-hidden="true">
      {items.map((i) => (
        <div key={i} className="tc-media__item" />
      ))}
    </div>
  );
};
