import { FC } from "react";
import { ModalRoot, DialogButton } from "@decky/ui";
import { core } from "../theme/coreTokens";

interface MigrationConflictModalProps {
  conflictCount: number;
  closeModal?: () => void;
  onChoice: (strategy: "overwrite" | "skip") => void;
}

export const MigrationConflictModal: FC<MigrationConflictModalProps> = ({ conflictCount, closeModal, onChoice }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: "16px", minWidth: "320px" }}>
      <div style={{ fontSize: "16px", fontWeight: "bold", color: core.white, marginBottom: "8px" }}>
        Files Already Exist
      </div>
      <div style={{ fontSize: "13px", color: core.steel, marginBottom: "16px" }}>
        {conflictCount} file(s) already exist at the destination.
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <DialogButton
          onClick={() => {
            closeModal?.();
            onChoice("overwrite");
          }}
        >
          Overwrite
        </DialogButton>
        <DialogButton
          onClick={() => {
            closeModal?.();
            onChoice("skip");
          }}
        >
          Skip
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()} style={{ opacity: 0.5 }}>
          Cancel
        </DialogButton>
      </div>
    </div>
  </ModalRoot>
);
