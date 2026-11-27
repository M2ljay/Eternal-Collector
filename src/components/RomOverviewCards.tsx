/**
 * The Overview tab's own cards on a ROM game page (Core design): RetroAchievements
 * and Save sync, each a button that opens its tab. Render only, from the panel's
 * state for the ROM it shows, so a version switch re-renders them with the
 * switched-to version's answers and nothing is read here.
 *
 * Other plugins' Overview cards (Forge's Mods card, a Club card) join the same
 * grid through the game page registry.
 */

import type { FC } from "react";
import { DialogButton } from "@decky/ui";
import type { SaveStatus } from "../types";
import { core } from "../theme/coreTokens";

interface RomOverviewCardsProps {
  raId: number | null;
  achievements: { earned: number; total: number } | null;
  saveSyncEnabled: boolean;
  saveStatus: SaveStatus | null;
  conflictCount: number;
  onOpenTab: (tab: string) => void;
}

interface SaveChip {
  label: string;
  background: string;
  color: string;
}

/** The Save sync card's chip: the setting, then conflicts, then the backend's resolved display. */
export function saveSyncChip(enabled: boolean, status: SaveStatus | null, conflictCount: number): SaveChip {
  const quiet = { background: core.gunmetalRaised, color: core.steel };
  if (!enabled) return { label: "Off", ...quiet };
  if (conflictCount > 0) return { label: "Conflict", background: core.crimson, color: core.white };
  switch (status?.save_sync_display?.status) {
    case "synced":
      return { label: "Synced with RomM", background: core.success, color: core.black };
    case "pending":
      return { label: "Waiting to sync", background: core.warning, color: core.black };
    case "conflict":
      return { label: "Conflict", background: core.crimson, color: core.white };
    default:
      return { label: status ? "No saves yet" : "Not checked yet", ...quiet };
  }
}

export const RomOverviewCards: FC<RomOverviewCardsProps> = ({
  raId,
  achievements,
  saveSyncEnabled,
  saveStatus,
  conflictCount,
  onOpenTab,
}) => {
  const chip = saveSyncChip(saveSyncEnabled, saveStatus, conflictCount);
  return (
    <>
      {raId ? (
        <DialogButton key="ra" className="romm-core-card" onClick={() => onOpenTab("achievements")}>
          <div className="romm-core-card-title">RetroAchievements</div>
          <div className="romm-core-card-value">
            {achievements && achievements.total > 0 ? `${achievements.earned} / ${achievements.total}` : "—"}
          </div>
          <div className="romm-core-card-note">Open the list</div>
        </DialogButton>
      ) : null}
      <DialogButton
        key="saves"
        className="romm-core-card"
        onClick={() => {
          if (saveSyncEnabled) onOpenTab("saves");
        }}
      >
        <div className="romm-core-card-title">Save sync</div>
        <span className="romm-core-status-chip" style={{ background: chip.background, color: chip.color }}>
          {chip.label}
        </span>
        <div className="romm-core-card-note">
          {saveSyncEnabled ? "Slots, versions and conflicts" : "Turn it on in The Collector's settings"}
        </div>
      </DialogButton>
    </>
  );
};
