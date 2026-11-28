/**
 * The Overview tab's own cards on a ROM game page (Core design): RetroAchievements
 * and Save sync, each a button that opens its tab, placed by `order` among the
 * cards other plugins register. Render only, from the panel's
 * state for the ROM it shows, so a version switch re-renders them with the
 * switched-to version's answers and nothing is read here.
 *
 * Other plugins' Overview cards (Forge's Mods card, a Club card) join the same
 * grid through the game page registry.
 */

import type { ReactNode } from "react";
import { DialogButton } from "@decky/ui";
import type { SaveStatus } from "../types";
import { core } from "../theme/coreTokens";

export interface RomOverviewCardsProps {
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

/** A card The Collector draws itself, placed among the registered cards by `order`. */
export interface BuiltinCard {
  key: string;
  order: number;
  node: ReactNode;
}

/** Card orders: Forge's Mods card goes between them at 20, a Club card after them at 40. */
export const BUILTIN_CARD_ORDER = { achievements: 10, saves: 30 } as const;

export function romOverviewCards({
  raId,
  achievements,
  saveSyncEnabled,
  saveStatus,
  conflictCount,
  onOpenTab,
}: RomOverviewCardsProps): BuiltinCard[] {
  const chip = saveSyncChip(saveSyncEnabled, saveStatus, conflictCount);
  const cards: BuiltinCard[] = [];
  if (raId) {
    cards.push({
      key: "ra",
      order: BUILTIN_CARD_ORDER.achievements,
      node: (
        <DialogButton className="romm-core-card" onClick={() => onOpenTab("achievements")}>
          <div className="romm-core-card-title">RetroAchievements</div>
          <div className="romm-core-card-value">
            {achievements && achievements.total > 0 ? `${achievements.earned} / ${achievements.total}` : "\u2014"}
          </div>
          <div className="romm-core-card-note">Open the list</div>
        </DialogButton>
      ),
    });
  }
  cards.push({
    key: "saves",
    order: BUILTIN_CARD_ORDER.saves,
    node: (
      <DialogButton
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
    ),
  });
  return cards;
}
