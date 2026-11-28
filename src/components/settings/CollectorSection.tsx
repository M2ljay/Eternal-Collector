/**
 * The Collector's settings: the RetroAchievements Web API key that powers the
 * unlock timeline, cross-game goal checks and the achievements bridge. Pure
 * renderer: the parent owns the values and the saves; the key is shown masked
 * and entered through RaWebApiModal.
 */

import { FC } from "react";
import { DialogButton, Field, Focusable, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { RaWebApiModal } from "./RaWebApiModal";

export interface RaWebApiSettingsProps {
  username: string;
  /** Whether a key is stored (the frontend only ever sees the mask). */
  configured: boolean;
  onVerify: (username: string, key: string) => Promise<{ success: boolean; message: string }>;
  onSave: (username: string, key: string) => Promise<{ success: boolean; message?: string }>;
  onClear: () => void;
}

interface CollectorSectionProps {
  raWebApi?: RaWebApiSettingsProps;
}

export const CollectorSection: FC<CollectorSectionProps> = ({ raWebApi }) => (
  <PanelSection title="The Collector">
    {raWebApi ? (
      <PanelSectionRow>
        <Field
          label="RetroAchievements Web API"
          description={
            raWebApi.configured
              ? `${raWebApi.username} · key ••••`
              : "Not configured. Needed for the unlock timeline and goal checks."
          }
        >
          <Focusable flow-children="horizontal" style={{ display: "flex", gap: "6px" }}>
            <DialogButton
              style={{ minWidth: "auto", width: "auto" }}
              onClick={() =>
                showModal(
                  <RaWebApiModal
                    initialUsername={raWebApi.username}
                    hasStoredKey={raWebApi.configured}
                    onVerify={raWebApi.onVerify}
                    onSave={raWebApi.onSave}
                  />,
                )
              }
            >
              Edit
            </DialogButton>
            {raWebApi.configured ? (
              <DialogButton style={{ minWidth: "auto", width: "auto" }} onClick={raWebApi.onClear}>
                Remove
              </DialogButton>
            ) : null}
          </Focusable>
        </Field>
      </PanelSectionRow>
    ) : null}
  </PanelSection>
);
