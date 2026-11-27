/**
 * The small cross-game goals list on the QAM's main page: the oldest open goals
 * (at most three) with their games. Reads the local journal only, so it costs no
 * network request; renders nothing when no goal is open. "All goals" opens the
 * Achievements page.
 */

import { FC, useEffect, useState } from "react";
import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { debugLog, getAchievementGoals } from "../../api/backend";
import type { OverviewGoal } from "../../types";
import { core } from "../../theme/coreTokens";
import { detach } from "../../utils/detach";

export const QAM_GOAL_LIMIT = 3;

export const GoalsQamSection: FC<{ onOpen: () => void }> = ({ onOpen }) => {
  const [open, setOpen] = useState<OverviewGoal[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const answer = await getAchievementGoals();
        if (cancelled || !answer.success) return;
        const openGoals = answer.goals.filter((g) => g.unlocked_at === null);
        setOpen(openGoals.slice(0, QAM_GOAL_LIMIT));
        setTotal(openGoals.length);
      } catch (e) {
        detach(debugLog(`Failed to load goals for the QAM: ${e}`));
      }
    };
    detach(load());
    return () => {
      cancelled = true;
    };
  }, []);

  if (open.length === 0) return null;

  return (
    <PanelSection title={`Goals (${total})`}>
      {open.map((goal) => (
        <PanelSectionRow key={`${goal.ra_game_id}-${goal.achievement_id}`}>
          <Field
            label={
              <span style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontSize: "13px", color: core.text }}>{goal.title}</span>
                <span style={{ fontSize: "11px", color: core.hint }}>{`${goal.game_title} · ${goal.points} pts`}</span>
              </span>
            }
            focusable={true}
            bottomSeparator="none"
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ButtonItem layout="below" bottomSeparator="none" onClick={onOpen}>
          All goals and unlock timeline
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};
