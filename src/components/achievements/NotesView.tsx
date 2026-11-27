/**
 * The Notes view of the achievements tab: the user's free-text notes for the
 * game (edited with Steam's on-screen keyboard) and the RetroAchievements
 * link-outs — the game's page and, when RetroAchievements lists one, its guide.
 * Links open in Steam's browser; nothing is fetched from a guide site.
 */

import { FC } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { core } from "../../theme/coreTokens";
import { formatUnlockDate, openRetroAchievementsPage } from "../../utils/achievementJournal";

interface NotesViewProps {
  notes: string;
  notesUpdatedAt: string | null;
  gameUrl: string | null;
  guideUrl: string | null;
  webApiConfigured: boolean;
  onEdit: () => void;
}

export const NotesView: FC<NotesViewProps> = ({
  notes,
  notesUpdatedAt,
  gameUrl,
  guideUrl,
  webApiConfigured,
  onEdit,
}) => (
  <div data-testid="notes-view">
    <div
      style={{
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        color: notes ? core.text : core.hint,
        background: core.gunmetal,
        borderLeft: `3px solid ${core.crimson}`,
        padding: "10px 12px",
        marginBottom: "6px",
        minHeight: "40px",
      }}
    >
      {notes || "No notes yet."}
    </div>
    {notesUpdatedAt ? (
      <div style={{ fontSize: "11px", color: core.hint, marginBottom: "10px" }}>
        {`Edited ${formatUnlockDate(notesUpdatedAt)}`}
      </div>
    ) : null}
    <Focusable flow-children="horizontal" style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
      <DialogButton style={{ minWidth: "auto", width: "auto" }} onClick={onEdit}>
        {notes ? "Edit notes" : "Write notes"}
      </DialogButton>
      {gameUrl ? (
        <DialogButton style={{ minWidth: "auto", width: "auto" }} onClick={() => openRetroAchievementsPage(gameUrl)}>
          Game on RetroAchievements
        </DialogButton>
      ) : null}
      {guideUrl ? (
        <DialogButton style={{ minWidth: "auto", width: "auto" }} onClick={() => openRetroAchievementsPage(guideUrl)}>
          Game guide
        </DialogButton>
      ) : null}
    </Focusable>
    {!webApiConfigured ? (
      <div style={{ fontSize: "11px", color: core.hint, marginTop: "8px" }}>
        Add a RetroAchievements Web API key in Settings to link the game’s guide here.
      </div>
    ) : null}
  </div>
);
