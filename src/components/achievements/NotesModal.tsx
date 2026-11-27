/**
 * Edit a game's achievement notes. Opens Steam's on-screen keyboard through the
 * focused TextField, keeps the text in this modal until Save, and shows how much
 * of the limit is used. Saving an empty field clears the notes.
 */

import { FC, useState, ChangeEvent } from "react";
import { ConfirmModal, Focusable, TextField } from "@decky/ui";
import { core } from "../../theme/coreTokens";

/** Mirrors MAX_NOTES_CHARS in py_modules/domain/ra_game_journal.py. */
export const MAX_NOTES_CHARS = 4000;

interface NotesModalProps {
  gameTitle: string;
  initial: string;
  closeModal?: () => void;
  /** Persists the text; resolves to an error message, or null on success. */
  onSave: (text: string) => Promise<string | null>;
}

export const NotesModal: FC<NotesModalProps> = ({ gameTitle, initial, closeModal, onSave }) => {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const tooLong = value.trim().length > MAX_NOTES_CHARS;

  const save = async () => {
    if (saving || tooLong) return;
    setSaving(true);
    try {
      const message = await onSave(value);
      if (message) {
        setError(message);
        return;
      }
      closeModal?.();
    } catch {
      setError("Saving the notes failed. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <ConfirmModal
      {...(closeModal !== undefined ? { closeModal } : {})}
      strTitle={`Notes — ${gameTitle}`}
      strOKButtonText={saving ? "Saving…" : "Save"}
      bOKDisabled={saving || tooLong}
      bDisableBackgroundDismiss={true}
      onOK={() => {
        void save();
      }}
    >
      <div style={{ fontSize: "12px", color: core.steel, marginBottom: "8px" }}>
        Your own notes for this game: routes, tips, what to try next. Leave empty to clear.
      </div>
      {/* Wrapped in <Focusable> like the other single-field modals: on the Deck,
          OSK-Enter on an unwrapped field otherwise closes the ModalRoot. */}
      <Focusable>
        <TextField
          focusOnMount={true}
          label="Notes"
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            setValue(e.target.value);
            setError(null);
          }}
        />
      </Focusable>
      <div
        data-testid="notes-count"
        style={{ fontSize: "11px", marginTop: "6px", color: tooLong ? core.crimsonText : core.hint }}
      >
        {`${value.trim().length} / ${MAX_NOTES_CHARS}`}
      </div>
      {error ? (
        <div data-testid="notes-error" style={{ fontSize: "12px", marginTop: "6px", color: core.crimsonText }}>
          {error}
        </div>
      ) : null}
    </ConfirmModal>
  );
};
