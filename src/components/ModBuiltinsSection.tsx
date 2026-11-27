/**
 * The entries of a built-in-toggle mod target — codes, cheats and patches the
 * emulator already has for this game — each with an On/Off switch.
 *
 * Every switch is one backend edit of the emulator's own file (copied to
 * romm-mod-backups first, refused while the emulator runs), so the list is
 * re-read after each one instead of being updated locally. Entries are named
 * by the `entry_id` the backend listed, never by anything typed here.
 */

import { FC, useCallback, useEffect, useState } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { listModBuiltins, logError, setModBuiltin } from "../api/backend";
import { showToast } from "../utils/toast";
import { detach } from "../utils/detach";
import type { ModBuiltinsAnswer, ModBuiltinEntry, ModTarget } from "../types";
import { core } from "../theme/coreTokens";

const LABEL = { fontSize: "12px", color: core.hint } as const;
const BODY = { fontSize: "13px", color: core.text } as const;

interface ModBuiltinsSectionProps {
  romId: number;
  target: ModTarget;
  emulatorLabel: string;
}

export const ModBuiltinsSection: FC<ModBuiltinsSectionProps> = ({ romId, target, emulatorLabel }) => {
  const [answer, setAnswer] = useState<ModBuiltinsAnswer | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAnswer(await listModBuiltins(romId, target.target_id));
      setFailed(false);
    } catch (e) {
      logError(`listModBuiltins failed: ${String(e)}`);
      setFailed(true);
    }
  }, [romId, target.target_id]);

  useEffect(() => {
    let cancelled = false;
    listModBuiltins(romId, target.target_id).then(
      (result) => {
        if (!cancelled) setAnswer(result);
      },
      (e: unknown) => {
        logError(`listModBuiltins failed: ${String(e)}`);
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [romId, target.target_id]);

  const toggle = async (entry: ModBuiltinEntry) => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await setModBuiltin(romId, target.target_id, entry.entry_id, !entry.enabled);
      if (!result.success) showToast(result.message || "Couldn't change it.");
      await load();
    } catch (e) {
      logError(`setModBuiltin failed: ${String(e)}`);
      showToast("Couldn't change it.");
    } finally {
      setBusy(false);
    }
  };

  if (failed) return <div style={BODY}>Couldn&apos;t read the list.</div>;
  if (!answer) return <div style={LABEL}>Reading the list…</div>;
  if (!answer.success) return <div style={BODY}>{answer.message}</div>;
  return (
    <div style={{ marginTop: "6px" }}>
      {answer.reason ? <div style={{ ...BODY, color: core.warning }}>{answer.reason}</div> : null}
      {answer.entries.length === 0 ? (
        <div style={LABEL}>None for this game.</div>
      ) : (
        <div style={LABEL}>Close {emulatorLabel} before switching; each change is written to its settings.</div>
      )}
      {answer.entries.map((entry) => (
        <Focusable
          key={entry.entry_id}
          flow-children="row"
          style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}
        >
          <div style={{ flex: 1 }}>
            <div style={BODY}>{entry.name}</div>
            {entry.description ? <div style={LABEL}>{entry.description}</div> : null}
            {entry.notes.map((note) => (
              <div key={note} style={LABEL}>
                {note}
              </div>
            ))}
          </div>
          <DialogButton
            disabled={busy || !entry.can_toggle}
            onClick={() => detach(toggle(entry))}
            style={{ width: "auto", minWidth: "70px" }}
          >
            {entry.enabled ? "On" : "Off"}
          </DialogButton>
        </Focusable>
      ))}
    </div>
  );
};
