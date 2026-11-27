/**
 * The Collector's artwork settings: the SteamGridDB API key and the portrait
 * cover style. Pure renderer: the parent owns the masked-key display value, the
 * cover style and the handlers. The key is entered through SgdbApiKeyModal,
 * which validates it against SteamGridDB before saving, so this section carries
 * no status line of its own.
 */

import { FC } from "react";
import { PanelSection, PanelSectionRow, DialogButton, DropdownItem, Field, showModal } from "@decky/ui";
import type { CoverStyle } from "../../utils/caseArt";
import { SgdbApiKeyModal } from "./SgdbApiKeyModal";
import type { VerifyKeyResult } from "./SgdbApiKeyModal";

interface SteamGridDBSectionProps {
  sgdbApiKey: string;
  onVerifyKey: (key: string) => Promise<VerifyKeyResult>;
  onSaveKey: (key: string) => Promise<void>;
  coverStyle: CoverStyle;
  onCoverStyleChange: (style: CoverStyle) => void;
}

export const COVER_STYLE_OPTIONS: { data: CoverStyle; label: string }[] = [
  { data: "case", label: "Game case (preferred)" },
  { data: "plain", label: "Plain cover" },
];

export const COVER_STYLE_DESCRIPTION =
  "Game case uses SteamGridDB artwork drawn as the console's retail case where one exists, and the plain cover otherwise. Covers already in Steam change on the next artwork refresh or sync. Pick a different one per game with Choose artwork… on the game page.";

export const SteamGridDBSection: FC<SteamGridDBSectionProps> = ({
  sgdbApiKey,
  onVerifyKey,
  onSaveKey,
  coverStyle,
  onCoverStyleChange,
}) => {
  return (
    <PanelSection title="SteamGridDB">
      <PanelSectionRow>
        <Field label="API Key" description={sgdbApiKey ? "••••" : "Not configured"}>
          <DialogButton
            style={{ minWidth: "auto", width: "auto" }}
            onClick={() => showModal(<SgdbApiKeyModal onVerify={onVerifyKey} onSave={onSaveKey} />)}
          >
            Edit
          </DialogButton>
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Cover style"
          description={COVER_STYLE_DESCRIPTION}
          rgOptions={COVER_STYLE_OPTIONS}
          selectedOption={coverStyle}
          onChange={(option) => onCoverStyleChange(option.data as CoverStyle)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
};
