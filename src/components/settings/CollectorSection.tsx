/**
 * The Collector's settings: whether its console shelf appears on Steam's Home,
 * under Recent games. Pure renderer: the parent owns the value and the save.
 */

import { FC } from "react";
import { PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";

export const CollectorSection: FC<{ homeShelf: boolean; onHomeShelfChange: (enabled: boolean) => void }> = ({
  homeShelf,
  onHomeShelfChange,
}) => (
  <PanelSection title="The Collector">
    <PanelSectionRow>
      <ToggleField
        label="Show The Collector on Home"
        description="A row of your consoles under Recent games, most played first. Select one to see its games."
        checked={homeShelf}
        onChange={onHomeShelfChange}
      />
    </PanelSectionRow>
  </PanelSection>
);
