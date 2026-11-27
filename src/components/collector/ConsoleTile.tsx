import { FC } from "react";
import { Focusable, Navigation } from "@decky/ui";
import type { ShelfConsole } from "../../types";
import { consolePagePath } from "../../utils/consoleMedia";
import { CapsuleArt } from "./CapsuleArt";
import { ConsoleMedia } from "./ConsoleMedia";

function scrollIntoRow(target: EventTarget | null): void {
  if (target instanceof HTMLElement) target.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
}

/**
 * One console on the Home row, drawn as a portrait capsule the size of Steam's own:
 * the Steam capsule art of the console's cover game over its media stack, and
 * nothing else. The console's name appears only while the capsule has focus; no
 * game count and no "last played" are shown on Home. A opens its console page.
 */
export const ConsoleTile: FC<{ console: ShelfConsole }> = ({ console }) => {
  const open = () => Navigation.Navigate(consolePagePath(console.platform_slug));
  return (
    <Focusable
      className="tc-tile"
      focusClassName="tc-focus"
      data-platform={console.platform_slug}
      aria-label={console.name}
      onActivate={open}
      onClick={open}
      onGamepadFocus={(e) => scrollIntoRow(e.currentTarget)}
    >
      <div className="tc-tile__capsule">
        <div className="tc-tile__media">
          <ConsoleMedia platformSlug={console.platform_slug} gameCount={console.game_count} />
        </div>
        <CapsuleArt key={console.cover_app_id} appId={console.cover_app_id} className="tc-tile__art" fallback={null} />
        <div className="tc-tile__label">
          <div className="tc-tile__name">{console.name}</div>
        </div>
      </div>
    </Focusable>
  );
};
