/**
 * The QAM's Achievements page: every goal the user pinned across games, and the
 * unlock timeline (game, achievement, date, points, hardcore) filterable by game
 * and console.
 *
 * Goals are local and always shown. The timeline and "Check goals" ask
 * RetroAchievements' Web API, which needs the key the user stores in Settings;
 * without one the page says so in one line instead of showing an empty list.
 */

import { FC, useEffect, useMemo, useState } from "react";
import { ButtonItem, DropdownItem, Field, Navigation, PanelSection, PanelSectionRow } from "@decky/ui";
import {
  debugLog,
  getAchievementGoals,
  getUnlockTimeline,
  refreshAchievementGoals,
  unpinAchievementGoal,
} from "../api/backend";
import type { GoalsOverviewAnswer, OverviewGoal, TimelineEntry, TimelineRange } from "../types";
import { core } from "../theme/coreTokens";
import {
  ALL,
  filterTimeline,
  formatUnlockDate,
  sumPoints,
  timelineFacets,
  type TimelineFilter,
} from "../utils/achievementJournal";
import { detach } from "../utils/detach";
import { getEventTarget } from "../utils/events";
import { scrollToTop } from "../utils/scrollHelpers";
import { showAchievementMenu } from "./achievements/achievementMenus";
import { GoalStatusMark } from "./achievements/GoalsView";

export const NO_KEY_LINE =
  "Add a RetroAchievements Web API key in Settings → The Collector to see your unlock timeline and check goals across games.";

const RANGES: { data: TimelineRange; label: string }[] = [
  { data: 30, label: "Last 30 days" },
  { data: 90, label: "Last 90 days" },
  { data: 365, label: "Last year" },
];

const rowText = { fontSize: "13px", color: core.text } as const;
const subText = { fontSize: "11px", color: core.hint } as const;

/** The label line of one goal row: the achievement, its game, and its state. */
const GoalRowLabel: FC<{ goal: OverviewGoal }> = ({ goal }) => {
  const done = goal.unlocked_at !== null;
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "10px" }}>
      <GoalStatusMark done={done} />
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <span style={rowText}>{goal.title}</span>
        <span style={subText}>
          {`${goal.game_title} · ${goal.points} pts`}
          {done && goal.unlocked_at ? ` · ${formatUnlockDate(goal.unlocked_at)}` : ""}
          {done && goal.unlocked_hardcore ? " · hardcore" : ""}
        </span>
      </span>
    </span>
  );
};

/** The label line of one timeline entry. */
const TimelineRowLabel: FC<{ entry: TimelineEntry }> = ({ entry }) => (
  <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
    <span style={rowText}>
      {entry.title}
      {entry.hardcore ? (
        <span style={{ marginLeft: "6px", fontSize: "10px", fontWeight: 700, color: core.crimsonText }}>HC</span>
      ) : null}
    </span>
    <span style={subText}>
      {`${entry.game_title}${entry.console_name ? ` (${entry.console_name})` : ""} · ${entry.points} pts · ${formatUnlockDate(entry.unlocked_at)}`}
    </span>
  </span>
);

export const AchievementsPage: FC<{ onBack: () => void }> = ({ onBack }) => {
  const [goals, setGoals] = useState<OverviewGoal[]>([]);
  const [webApi, setWebApi] = useState(false);
  const [goalStatus, setGoalStatus] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [range, setRange] = useState<TimelineRange>(30);
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [timelineStatus, setTimelineStatus] = useState<string | null>(null);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [filter, setFilter] = useState<TimelineFilter>({ game: ALL, console: ALL });

  const applyGoals = (answer: GoalsOverviewAnswer) => {
    if (answer.success) {
      setGoals(answer.goals);
      setWebApi(answer.web_api_configured);
    } else {
      setGoalStatus(answer.message);
    }
  };

  useEffect(() => {
    getAchievementGoals()
      .then(applyGoals)
      .catch((e: unknown) => {
        detach(debugLog(`Failed to load goals: ${e}`));
        setGoalStatus("Goals could not be loaded.");
      });
  }, []);

  const loadTimeline = async (days: TimelineRange, force: boolean): Promise<void> => {
    setLoadingTimeline(true);
    setTimelineStatus(null);
    try {
      const answer = await getUnlockTimeline(days, force);
      if (answer.success) {
        setEntries(answer.entries);
      } else if (answer.reason === "no_web_api_key") {
        setEntries([]);
      } else {
        setTimelineStatus(answer.message);
      }
    } catch (e) {
      detach(debugLog(`Failed to load the unlock timeline: ${e}`));
      setTimelineStatus("The unlock timeline could not be loaded.");
    } finally {
      setLoadingTimeline(false);
    }
  };

  useEffect(() => {
    if (!webApi) return;
    const run = async () => {
      await loadTimeline(range, false);
    };
    detach(run());
  }, [webApi, range]);

  const checkGoals = () => {
    setChecking(true);
    setGoalStatus(null);
    refreshAchievementGoals()
      .then((answer) => {
        applyGoals(answer);
        if (answer.success) {
          const ticked = answer.changed ?? 0;
          setGoalStatus(ticked > 0 ? `${ticked} goal${ticked === 1 ? "" : "s"} unlocked` : "No new unlocks");
        }
      })
      .catch((e: unknown) => {
        detach(debugLog(`Failed to check goals: ${e}`));
        setGoalStatus("Goals could not be checked.");
      })
      .finally(() => setChecking(false));
  };

  const removeGoal = (goal: OverviewGoal) => {
    if (goal.rom_id === null) return;
    unpinAchievementGoal(goal.rom_id, goal.achievement_id)
      .then((answer) => (answer.success ? getAchievementGoals() : null))
      .then((answer) => {
        if (answer) applyGoals(answer);
      })
      .catch((e: unknown) => {
        detach(debugLog(`Failed to remove goal: ${e}`));
        setGoalStatus("The goal could not be removed.");
      });
  };

  const facets = useMemo(() => timelineFacets(entries), [entries]);
  const shown = useMemo(() => filterTimeline(entries, filter), [entries, filter]);
  const openCount = goals.filter((g) => g.unlocked_at === null).length;

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={onBack}
            // @ts-expect-error onFocus works at runtime; not in Decky's ButtonItem types
            onFocus={scrollToTop}
          >
            Back
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={goals.length > 0 ? `Goals (${openCount} open)` : "Goals"}>
        {goals.length === 0 ? (
          <PanelSectionRow>
            <Field
              label={<span style={subText}>No goals yet. Pin achievements from a game’s Achievements tab.</span>}
              focusable={true}
              bottomSeparator="none"
            />
          </PanelSectionRow>
        ) : null}
        {goals.map((goal) => (
          <PanelSectionRow key={`${goal.ra_game_id}-${goal.achievement_id}`}>
            <Field
              label={<GoalRowLabel goal={goal} />}
              focusable={true}
              bottomSeparator="none"
              onClick={(e: MouseEvent | CustomEvent) =>
                showAchievementMenu(
                  {
                    achievementId: goal.achievement_id,
                    title: goal.title,
                    isGoal: true,
                    ...(goal.rom_id === null ? {} : { onUnpin: () => removeGoal(goal) }),
                    ...(goal.app_id === null
                      ? {}
                      : {
                          onOpenGame: () => {
                            Navigation.CloseSideMenus();
                            Navigation.Navigate(`/library/app/${goal.app_id}`);
                          },
                        }),
                  },
                  getEventTarget(e),
                )
              }
            />
          </PanelSectionRow>
        ))}
        {webApi && openCount > 0 ? (
          <PanelSectionRow>
            <ButtonItem layout="below" bottomSeparator="none" disabled={checking} onClick={checkGoals}>
              {checking ? "Checking…" : "Check goals on RetroAchievements"}
            </ButtonItem>
          </PanelSectionRow>
        ) : null}
        {goalStatus ? (
          <PanelSectionRow>
            <Field
              label={
                <span data-testid="goal-status" style={subText}>
                  {goalStatus}
                </span>
              }
              focusable={true}
              bottomSeparator="none"
            />
          </PanelSectionRow>
        ) : null}
      </PanelSection>

      <PanelSection title="Unlock timeline">
        {webApi ? (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="Period"
                rgOptions={RANGES}
                selectedOption={range}
                onChange={(option) => setRange(option.data as TimelineRange)}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label="Game"
                rgOptions={[
                  { data: ALL, label: "All games" },
                  ...facets.games.map((g) => ({ data: g.id, label: g.title })),
                ]}
                selectedOption={filter.game}
                onChange={(option) => setFilter((f) => ({ ...f, game: String(option.data) }))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label="Console"
                rgOptions={[
                  { data: ALL, label: "All consoles" },
                  ...facets.consoles.map((c) => ({ data: c, label: c })),
                ]}
                selectedOption={filter.console}
                onChange={(option) => setFilter((f) => ({ ...f, console: String(option.data) }))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <Field
                label={
                  <span data-testid="timeline-summary" style={subText}>
                    {loadingTimeline
                      ? "Loading unlocks…"
                      : (timelineStatus ?? `${shown.length} unlocks · ${sumPoints(shown)} points`)}
                  </span>
                }
                focusable={true}
                bottomSeparator="none"
              />
            </PanelSectionRow>
            {shown.map((entry) => (
              <PanelSectionRow key={`${entry.achievement_id}-${entry.unlocked_at}`}>
                <Field
                  label={<TimelineRowLabel entry={entry} />}
                  focusable={true}
                  bottomSeparator="none"
                  onClick={(e: MouseEvent | CustomEvent) =>
                    showAchievementMenu(
                      { achievementId: entry.achievement_id, title: entry.title, isGoal: false },
                      getEventTarget(e),
                    )
                  }
                />
              </PanelSectionRow>
            ))}
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                bottomSeparator="none"
                disabled={loadingTimeline}
                onClick={() => detach(loadTimeline(range, true))}
              >
                Refresh timeline
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <PanelSectionRow>
            <Field
              label={
                <span data-testid="no-key-line" style={subText}>
                  {NO_KEY_LINE}
                </span>
              }
              focusable={true}
              bottomSeparator="none"
            />
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
};
