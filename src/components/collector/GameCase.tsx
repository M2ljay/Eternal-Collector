import { FC, useState } from "react";
import { Focusable, Navigation } from "@decky/ui";
import type { ConsoleGame } from "../../types";
import type { MediaKind } from "../../utils/consoleMedia";
import { relativePlayed } from "../../utils/relativePlayed";

export interface Chip {
  text: string;
  tone: "plain" | "synced" | "pending" | "conflict" | "hardcore" | "award";
}

const AWARD_TEXT = { mastered: "Mastered", completed: "Completed", beaten: "Beaten" } as const;

/** The save-sync chip, from the cached display the game page also shows before its live check. */
export function saveChip(game: ConsoleGame, saveSyncEnabled: boolean): Chip | null {
  if (!saveSyncEnabled) return null;
  const display = game.save_sync;
  if (!display) return { text: "No saves yet", tone: "plain" };
  switch (display.status) {
    case "synced":
      return { text: display.label ?? "Saves synced", tone: "synced" };
    case "pending":
      return { text: display.label ?? "Saves pending", tone: "pending" };
    case "conflict":
      return { text: display.label ?? "Save conflict", tone: "conflict" };
    default:
      return { text: display.label ?? "No saves", tone: "plain" };
  }
}

/** The RetroAchievements chips: progress, the hardcore mark and the highest award. */
export function achievementChips(game: ConsoleGame): Chip[] {
  const a = game.achievements;
  if (!a) return game.has_ra_set ? [{ text: "No progress yet", tone: "plain" }] : [];
  const chips: Chip[] = [{ text: `${a.earned} / ${a.total}`, tone: "plain" }];
  if (a.hardcore) chips.push({ text: "Hardcore", tone: "hardcore" });
  if (a.award) chips.push({ text: AWARD_TEXT[a.award], tone: "award" });
  return chips;
}

function scrollIntoPage(target: EventTarget | null): void {
  if (target instanceof HTMLElement) target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
}

/** Steam's own cover for a shortcut, filled by the plugin's artwork; the title stands in when it is missing. */
const CoverArt: FC<{ appId: number; name: string }> = ({ appId, name }) => {
  const sources = [`/customimages/${appId}p.png`, `/customimages/${appId}p.jpg`];
  const [attempt, setAttempt] = useState(0);
  if (attempt >= sources.length) return <div className="tc-case__fallback">{name}</div>;
  return (
    <img
      className="tc-case__art"
      src={sources[attempt]}
      alt=""
      loading="lazy"
      onError={() => setAttempt((n) => n + 1)}
    />
  );
};

/** One game drawn in its console's media; A opens the game page the plugin already owns. */
export const GameCase: FC<{
  game: ConsoleGame;
  kind: MediaKind;
  saveSyncEnabled: boolean;
  continueCase?: boolean;
  preferredFocus?: boolean;
}> = ({ game, kind, saveSyncEnabled, continueCase = false, preferredFocus = false }) => {
  const open = () => Navigation.Navigate(`/library/app/${game.app_id}`);
  const chips = [saveChip(game, saveSyncEnabled), ...achievementChips(game)].filter((c): c is Chip => c !== null);
  const classes = ["tc-case", `tc-case--${kind}`, continueCase ? "tc-case--continue" : ""].filter(Boolean).join(" ");
  return (
    <Focusable
      preferredFocus={preferredFocus}
      className={classes}
      focusClassName="tc-focus"
      data-rom-id={game.rom_id}
      aria-label={game.name}
      onActivate={open}
      onClick={open}
      onGamepadFocus={(e) => scrollIntoPage(e.currentTarget)}
    >
      <div className="tc-case__shell">
        <CoverArt appId={game.app_id} name={game.name} />
      </div>
      <div className="tc-case__name">{game.name}</div>
      <div className="tc-case__meta">
        {relativePlayed(game.last_played)}
        {game.installed ? "" : " · Not downloaded"}
      </div>
      {chips.length > 0 && (
        <div className="tc-case__chips">
          {chips.map((c) => (
            <span key={c.text} className={`tc-chip tc-chip--${c.tone}`}>
              {c.text}
            </span>
          ))}
        </div>
      )}
    </Focusable>
  );
};
