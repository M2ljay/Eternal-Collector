/**
 * The Goals view of the achievements tab: the game's pinned achievements, open
 * ones first, each ticked off once it is unlocked — recorded in the journal, or
 * seen in RomM's progress for this game. A on a row opens its menu (remove the
 * goal, open its RetroAchievements page).
 */

import { FC } from "react";
import { DialogButton } from "@decky/ui";
import type { AchievementGoal } from "../../types";
import { core } from "../../theme/coreTokens";
import { formatUnlockDate, isGoalDone, type SeenUnlock } from "../../utils/achievementJournal";
import { scrollFocusedToCenter } from "../../utils/scrollHelpers";
import { getEventTarget } from "../../utils/events";
import { showAchievementMenu } from "./achievementMenus";

interface GoalsViewProps {
  goals: AchievementGoal[];
  seen: Map<number, SeenUnlock>;
  onUnpin: (achievementId: number) => void;
}

export const GoalStatusMark: FC<{ done: boolean }> = ({ done }) => (
  <span
    aria-label={done ? "Unlocked" : "Not unlocked yet"}
    style={{
      flex: "0 0 auto",
      width: "22px",
      height: "22px",
      borderRadius: "50%",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "13px",
      fontWeight: 700,
      color: done ? core.black : core.steel,
      background: done ? core.success : "transparent",
      border: done ? "none" : `2px solid ${core.hint}`,
    }}
  >
    {done ? "✓" : ""}
  </span>
);

export const GoalsView: FC<GoalsViewProps> = ({ goals, seen, onUnpin }) => {
  if (goals.length === 0) {
    return <div className="romm-panel-muted">No goals yet. Select an achievement in All and choose “Pin as goal”.</div>;
  }
  const ordered = [...goals].sort((a, b) => Number(isGoalDone(a, seen)) - Number(isGoalDone(b, seen)));
  return (
    <div data-testid="goals-view">
      {ordered.map((goal) => {
        const done = isGoalDone(goal, seen);
        const unlock = seen.get(goal.achievement_id);
        const when = goal.unlocked_at ?? unlock?.unlocked_at ?? null;
        const hardcore = goal.unlocked_hardcore || (unlock?.hardcore ?? false);
        return (
          <DialogButton
            key={goal.achievement_id}
            aria-label={goal.title}
            onFocus={scrollFocusedToCenter}
            onClick={(e: MouseEvent) =>
              showAchievementMenu(
                {
                  achievementId: goal.achievement_id,
                  title: goal.title,
                  isGoal: true,
                  onUnpin: () => onUnpin(goal.achievement_id),
                },
                getEventTarget(e),
              )
            }
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              textAlign: "left",
              background: "transparent",
              border: "none",
              padding: "8px 4px",
            }}
          >
            <GoalStatusMark done={done} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: done ? core.text : core.steel, fontWeight: 600 }}>{goal.title}</div>
              {goal.description ? <div style={{ fontSize: "12px", color: core.hint }}>{goal.description}</div> : null}
              {done && when ? (
                <div style={{ fontSize: "11px", color: core.success }}>
                  {`Unlocked ${formatUnlockDate(when)}${hardcore ? " · hardcore" : ""}`}
                </div>
              ) : null}
            </div>
            <div style={{ fontSize: "12px", color: done ? core.text : core.hint }}>{`${goal.points} pts`}</div>
          </DialogButton>
        );
      })}
    </div>
  );
};
