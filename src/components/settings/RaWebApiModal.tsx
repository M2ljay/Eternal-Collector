/**
 * Prompt for the RetroAchievements Web API username and key, checked against
 * RetroAchievements before anything is saved. The key is the one from the user's
 * RetroAchievements settings page (Settings → Keys → Web API Key), entered here
 * for The Collector's timeline and goal checks; it is never an emulator's login.
 * The key is write-only: never pre-filled, never echoed back. Leaving the key
 * empty while one is stored keeps the stored key (only the username changes).
 */

import { FC, useState, ChangeEvent } from "react";
import { TextField, Focusable } from "@decky/ui";
import { ValidatingModalShell } from "./ValidatingModalShell";
import { core } from "../../theme/coreTokens";

/** The placeholder the backend reads as "keep the stored key". */
export const KEEP_STORED_KEY = "••••";

interface RaWebApiModalProps {
  closeModal?: () => void;
  initialUsername: string;
  hasStoredKey: boolean;
  onVerify: (username: string, key: string) => Promise<{ success: boolean; message: string }>;
  onSave: (username: string, key: string) => Promise<{ success: boolean; message?: string }>;
}

const helperTextStyle = { fontSize: "12px", marginBottom: "12px", color: core.steel } as const;

export const RaWebApiModal: FC<RaWebApiModalProps> = ({
  closeModal,
  initialUsername,
  hasStoredKey,
  onVerify,
  onSave,
}) => {
  const [username, setUsername] = useState(initialUsername);
  const [key, setKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const keyToSend = key.trim() === "" && hasStoredKey ? KEEP_STORED_KEY : key.trim();
  const canSubmit = username.trim() !== "" && keyToSend !== "";

  const submit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const check = await onVerify(username.trim(), keyToSend);
      if (!check.success) {
        setError(check.message);
        return;
      }
      const saved = await onSave(username.trim(), keyToSend);
      if (!saved.success) {
        setError(saved.message ?? "Saving failed. Try again.");
        return;
      }
      closeModal?.();
    } catch {
      setError("Could not reach RetroAchievements. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ValidatingModalShell
      {...(closeModal === undefined ? {} : { closeModal })}
      title="RetroAchievements Web API"
      error={error}
      errorTestId="ra-web-error"
      submitLabel={submitting ? "Checking…" : "Save"}
      submitDisabled={!canSubmit || submitting}
      onSubmit={() => {
        void submit();
      }}
    >
      <div style={helperTextStyle}>
        For the unlock timeline and checking goals across games. Copy the Web API key from your RetroAchievements
        settings page. It is sent only to retroachievements.org.
        {hasStoredKey ? " Leave the key empty to keep the stored one." : ""}
      </div>
      <Focusable>
        <TextField
          focusOnMount={true}
          label="Username"
          value={username}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            setUsername(e.target.value);
            setError(null);
          }}
        />
        <TextField
          label="Web API key"
          value={key}
          bIsPassword
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            setKey(e.target.value);
            setError(null);
          }}
        />
      </Focusable>
    </ValidatingModalShell>
  );
};
