/**
 * The chip that opens screen two of a ROM game page (Core design): the platform
 * in its console family's tone. Screen one is the art, the logo and the play bar
 * only, as on a Steam game page.
 *
 * Classes prefixed with `romm-core-` are styled by `utils/corePageStyles.ts`.
 */

import type { FC } from "react";
import { consoleFamily, core, familyTones } from "../theme/coreTokens";
import { GamepadIcon } from "./icons";

interface RomPageChipsProps {
  platformName: string;
  platformSlug: string;
}

export const RomPageChips: FC<RomPageChipsProps> = ({ platformName, platformSlug }) => {
  const family = consoleFamily(platformSlug);
  if (!platformName) return null;
  return (
    <div className="romm-core-chips" data-romm="true">
      <span
        className="romm-core-chip romm-core-chip-tone"
        data-core-family={family}
        style={{ background: familyTones[family], color: core.black }}
      >
        <GamepadIcon size={20} />
        {platformName}
      </span>
    </div>
  );
};
