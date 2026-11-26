/**
 * SaveSortWarning — the banner the game detail panel shows while a RetroArch
 * save-sorting migration is still pending, i.e. while save file paths written
 * under the old sorting may no longer be where the emulator looks.
 */

import { FC } from "react";
import { core, tint } from "../theme/coreTokens";

export const SaveSortWarning: FC = () => (
  <div
    style={{
      padding: "8px 12px",
      marginBottom: "12px",
      backgroundColor: tint(core.warning, 0.15),
      borderLeft: `3px solid ${core.warning}`,
      borderRadius: "4px",
    }}
  >
    <div style={{ fontSize: "13px", fontWeight: "bold", color: core.warning, marginBottom: "4px" }}>
      {"\u26A0\uFE0F RetroArch save sorting changed"}
    </div>
    <div style={{ fontSize: "12px", color: core.steel }}>
      Save file paths may be incorrect. Go to Settings to migrate.
    </div>
  </div>
);
