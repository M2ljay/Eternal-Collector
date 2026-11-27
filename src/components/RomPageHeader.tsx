/**
 * The top of a ROM game page in the Core design: the game's name, a platform
 * chip in its console family's tone, The Collector chip, and the last-played /
 * playtime line. It sits over the bottom of Steam's hero art, above the play
 * bar, exactly where a Steam game page shows the same three things.
 *
 * Render only, from props: the play section owns the playtime it shows (it
 * reconciles it with RomM) and hands it down.
 *
 * Classes prefixed with `romm-core-` are styled by `utils/corePageStyles.ts`.
 */

import type { FC } from "react";
import { consoleFamily, core, familyTones } from "../theme/coreTokens";
import { CartridgeIcon, GamepadIcon } from "./icons";

interface RomPageHeaderProps {
  name: string;
  platformName: string;
  platformSlug: string;
  /** Already formatted ("3 days ago"); empty when never played. */
  lastPlayed: string;
  /** Already formatted ("12 hours"); empty when none recorded. */
  playtime: string;
}

/** "Last played 3 days ago · 12 hours played", or whichever half is known. */
export function playLine(lastPlayed: string, playtime: string): string {
  const parts: string[] = [];
  if (lastPlayed) parts.push(`Last played ${lastPlayed}`);
  if (playtime) parts.push(`${playtime} played`);
  return parts.join(" · ");
}

export const RomPageHeader: FC<RomPageHeaderProps> = ({ name, platformName, platformSlug, lastPlayed, playtime }) => {
  const line = playLine(lastPlayed, playtime);
  const family = consoleFamily(platformSlug);
  return (
    <div className="romm-core-header" data-romm="true">
      {name ? <div className="romm-core-title">{name}</div> : null}
      <div className="romm-core-chips">
        {platformName ? (
          <span
            className="romm-core-chip romm-core-chip-tone"
            data-core-family={family}
            style={{ background: familyTones[family], color: core.black }}
          >
            <GamepadIcon size={20} />
            {platformName}
          </span>
        ) : null}
        <span className="romm-core-chip">
          <CartridgeIcon size={20} />
          The Collector
        </span>
        {line ? <span className="romm-core-play-line">{line}</span> : null}
      </div>
    </div>
  );
};
