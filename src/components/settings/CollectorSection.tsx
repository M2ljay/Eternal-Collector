/**
 * The Collector's settings: whether its console shelf appears on Steam's Home,
 * under Recent games, and the RetroAchievements Web API key that powers the
 * unlock timeline and cross-game goal checks. Pure renderer: the parent owns the
 * values and the saves; the key is shown masked and entered through RaWebApiModal.
 */

import { FC } from "react";
import { DialogButton, Field, Focusable, PanelSection, PanelSectionRow, ToggleField, showModal } from "@decky/ui";
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
  homeShelf: boolean;
  onHomeShelfChange: (enabled: boolean) => void;
  raWebApi?: RaWebApiSettingsProps;
}

export const CollectorSection: FC<CollectorSectionProps> = ({ homeShelf, onHomeShelfChange, raWebApi }) => (
  <PanelSection title="The Collector">
    <PanelSectionRow>
      <ToggleField
        label="Show The Collector on Home"
        description="A row of your consoles under Recent games, most played first. Select one to see its games."
        checked={homeShelf}
        onChange={onHomeShelfChange}
      />
    </PanelSectionRow>
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
