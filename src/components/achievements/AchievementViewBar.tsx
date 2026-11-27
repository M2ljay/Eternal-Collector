/**
 * The view switch at the top of the achievements tab: the full list, the game's
 * goals, and its notes. Plain DialogButtons in one Focusable row, so the D-pad
 * moves between them and A selects; the active view carries the crimson underline.
 */

import { FC } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { core } from "../../theme/coreTokens";

export type AchievementView = "all" | "goals" | "notes";

interface AchievementViewBarProps {
  view: AchievementView;
  goalCount: number;
  doneCount: number;
  hasNotes: boolean;
  onSelect: (view: AchievementView) => void;
}

const LABELS: Record<AchievementView, string> = { all: "All", goals: "Goals", notes: "Notes" };

export const AchievementViewBar: FC<AchievementViewBarProps> = ({ view, goalCount, doneCount, hasNotes, onSelect }) => {
  const caption = (v: AchievementView): string => {
    if (v === "goals" && goalCount > 0) return `Goals ${doneCount}/${goalCount}`;
    if (v === "notes" && hasNotes) return "Notes •";
    return LABELS[v];
  };
  return (
    <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
      {(["all", "goals", "notes"] as const).map((v) => (
        <DialogButton
          key={v}
          aria-label={LABELS[v]}
          onClick={() => onSelect(v)}
          style={{
            minWidth: "auto",
            width: "auto",
            padding: "6px 14px",
            background: view === v ? core.gunmetalRaised : core.gunmetal,
            color: view === v ? core.text : core.steel,
            borderBottom: `2px solid ${view === v ? core.crimson : "transparent"}`,
          }}
        >
          {caption(v)}
        </DialogButton>
      ))}
    </Focusable>
  );
};
