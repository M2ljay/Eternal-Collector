import { FC } from "react";
import { Focusable, Navigation } from "@decky/ui";
import type { ShelfConsole } from "../../types";
import { consolePagePath } from "../../utils/consoleMedia";
import { relativePlayed } from "../../utils/relativePlayed";
import { pluralize } from "../../utils/pluralize";
import { ConsoleMedia } from "./ConsoleMedia";

function scrollIntoRow(target: EventTarget | null): void {
  if (target instanceof HTMLElement) target.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
}

/** One console on the Home row; A opens its console page. */
export const ConsoleTile: FC<{ console: ShelfConsole }> = ({ console }) => {
  const open = () => Navigation.Navigate(consolePagePath(console.platform_slug));
  const games = pluralize(console.game_count, "game");
  return (
    <Focusable
      className="tc-tile"
      focusClassName="tc-focus"
      data-platform={console.platform_slug}
      aria-label={`${console.name}, ${games}`}
      onActivate={open}
      onClick={open}
      onGamepadFocus={(e) => scrollIntoRow(e.currentTarget)}
    >
      <div className="tc-tile__media">
        <ConsoleMedia platformSlug={console.platform_slug} gameCount={console.game_count} />
      </div>
      <div className="tc-tile__name">{console.name}</div>
      <div className="tc-tile__meta">
        {games} · {relativePlayed(console.last_played)}
      </div>
    </Focusable>
  );
};
