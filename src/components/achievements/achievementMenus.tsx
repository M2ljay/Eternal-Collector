/**
 * The context menu an achievement row opens (A on a row): pin or remove it as a
 * goal, and open its RetroAchievements page in Steam's browser. Shared by the
 * achievement list, the Goals view and the QAM goals list.
 */

import { Menu, MenuItem, showContextMenu } from "@decky/ui";
import { achievementPageUrl, openRetroAchievementsPage } from "../../utils/achievementJournal";

export interface AchievementMenuOptions {
  achievementId: number;
  title: string;
  isGoal: boolean;
  /** Absent where pinning is not offered (the QAM list only removes). */
  onPin?: () => void;
  /** Absent where removing is not possible (no ROM of the game is left). */
  onUnpin?: () => void;
  /** Opens the game's page in Steam (QAM only). */
  onOpenGame?: () => void;
}

export function showAchievementMenu(options: AchievementMenuOptions, target?: EventTarget): void {
  const { achievementId, title, isGoal, onPin, onUnpin, onOpenGame } = options;
  showContextMenu(
    <Menu label={title}>
      {!isGoal && onPin ? <MenuItem onClick={onPin}>Pin as goal</MenuItem> : null}
      {isGoal && onUnpin ? <MenuItem onClick={onUnpin}>Remove goal</MenuItem> : null}
      {onOpenGame ? <MenuItem onClick={onOpenGame}>Open game</MenuItem> : null}
      <MenuItem onClick={() => openRetroAchievementsPage(achievementPageUrl(achievementId))}>
        Open guide on RetroAchievements
      </MenuItem>
    </Menu>,
    target,
  );
}
