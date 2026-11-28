import { FC } from "react";
import { Focusable } from "@decky/ui";
import { FAMILY_NAMES, familyTones, type ConsoleFamily } from "../../theme/coreTokens";
import type { FamilyArt } from "../../utils/consoleShelfStore";

function scrollIntoRow(target: EventTarget | null): void {
  if (target instanceof HTMLElement) target.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
}

/**
 * One console family on the Home row: a wide 16:9 tile with the family's hero from
 * the user's icon pack, dimmed, and its white logo centred over it; the family's
 * tone runs along the bottom. Without the pack's art the tile is gunmetal with the
 * family's name. No game art, counts or "last played". A runs `onOpen`.
 */
export const FamilyTile: FC<{ family: ConsoleFamily; art: FamilyArt | undefined; onOpen: () => void }> = ({
  family,
  art,
  onOpen,
}) => {
  const name = FAMILY_NAMES[family];
  return (
    <Focusable
      className="tc-family"
      focusClassName="tc-focus"
      data-family={family}
      aria-label={name}
      onActivate={onOpen}
      onClick={onOpen}
      onGamepadFocus={(e) => scrollIntoRow(e.currentTarget)}
    >
      <div className="tc-family__card">
        {art?.hero ? <img className="tc-family__hero" src={art.hero} alt="" /> : null}
        {art?.logo ? <img className="tc-family__logo" src={art.logo} alt={name} /> : null}
        {art?.logo === null ? <div className="tc-family__name">{name}</div> : null}
        <div className="tc-family__tone" style={{ background: familyTones[family] }} />
      </div>
    </Focusable>
  );
};
