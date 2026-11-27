/**
 * The Updates & DLC section of the GAME INFO pane: for each place this game's
 * updates and DLC live under its emulator, what is installed there, and a
 * button into the Mods panel narrowed to them (install from Downloads, open
 * the folder). Controller-only: one focusable button per row.
 *
 * Reads the game's targets once per ROM. The panel keys this component by the
 * ROM id, so its state can never outlive the version it was read for. Renders
 * nothing when the game has no update or DLC target (another emulator, another
 * platform, or mods unsupported).
 */

import { FC, useEffect, useState } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { getGameMods, logError } from "../api/backend";
import type { ModKind, ModTarget } from "../types";
import { core } from "../theme/coreTokens";
import { showModsModal } from "./ModsModal";
import { detach } from "../utils/detach";

const CONTENT_KINDS: readonly ModKind[] = ["update", "dlc"];
const LABEL = { fontSize: "12px", color: core.hint } as const;
const BODY = { fontSize: "13px", color: core.text } as const;

interface GameContentSectionProps {
  romId: number;
  romName: string;
}

/** One line on what a content target holds: its installed entries, or that nothing is installed. */
export function contentSummary(target: ModTarget): string {
  if (target.installed.length > 0) return `Installed: ${target.installed.map((e) => e.name).join(", ")}`;
  return target.scope === "readonly" ? "None found." : "Nothing installed yet.";
}

export const GameContentSection: FC<GameContentSectionProps> = ({ romId, romName }) => {
  const [targets, setTargets] = useState<ModTarget[]>([]);

  useEffect(() => {
    let cancelled = false;
    const read = async () => {
      try {
        const answer = await getGameMods(romId);
        if (!cancelled && answer.success) setTargets(answer.targets.filter((t) => CONTENT_KINDS.includes(t.kind)));
      } catch (e) {
        logError(`GameContentSection: getGameMods failed: ${String(e)}`);
      }
    };
    detach(read());
    return () => {
      cancelled = true;
    };
  }, [romId]);

  if (targets.length === 0) return null;
  return (
    <div className="romm-panel-section" data-romm="true" style={{ marginTop: "16px" }}>
      <div className="romm-panel-section-title">Updates &amp; DLC</div>
      <Focusable flow-children="down" style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {targets.map((target) => (
          <Focusable
            key={target.target_id}
            flow-children="row"
            style={{ display: "flex", alignItems: "center", gap: "12px" }}
          >
            <div style={{ flex: 1 }}>
              <div style={BODY}>{target.label}</div>
              <div style={LABEL}>{contentSummary(target)}</div>
              {target.notes.slice(0, 2).map((note) => (
                <div key={note} style={LABEL}>
                  {note}
                </div>
              ))}
            </div>
            <DialogButton
              onClick={() => showModsModal(romId, romName, CONTENT_KINDS)}
              style={{ width: "auto", minWidth: "110px" }}
            >
              {target.accepts === "none" ? "Details" : "Manage"}
            </DialogButton>
          </Focusable>
        ))}
      </Focusable>
    </div>
  );
};
