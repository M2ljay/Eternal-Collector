/**
 * The Media tab of a ROM game page: the cover The Collector holds for the game,
 * and the way into the artwork picker (the same picker the options menu opens).
 */

import type { FC } from "react";
import { DialogButton, Focusable, showModal } from "@decky/ui";
import { CaseArtPickerModalContent } from "./CaseArtPickerModal";

interface RomMediaTabProps {
  appId: number;
  romId: number;
  romName: string;
  coverBase64: string | null;
}

export const RomMediaTab: FC<RomMediaTabProps> = ({ appId, romId, romName, coverBase64 }) => (
  <Focusable className="romm-core-media" flow-children="down">
    {coverBase64 ? <img alt="" src={`data:image/png;base64,${coverBase64}`} /> : null}
    {coverBase64 ? null : <div className="romm-panel-muted">No cover yet.</div>}
    <DialogButton
      style={{ width: "auto", minWidth: "200px", marginTop: "8px" }}
      onClick={() => showModal(<CaseArtPickerModalContent romId={romId} appId={appId} romName={romName} />)}
    >
      Choose artwork…
    </DialogButton>
  </Focusable>
);
