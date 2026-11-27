/**
 * CaseArtPickerModal — "Choose artwork…" on the game page: pick which
 * SteamGridDB grid stands on the shortcut's portrait capsule.
 *
 * Lists the grids the backend ranks for the game (curated case-template authors
 * first, then case shape, then score; never NSFW) as portrait thumbnails in a
 * focus-managed grid: the D-pad moves between them and A applies the focused one
 * (letterboxed to 2:3 by utils/caseArt.ts). The choice is remembered as manual, so
 * an automatic pass or a sync keeps it; Refresh Artwork re-downloads it.
 *
 * Wrapped in Steam's ConfirmModal like SgdbGamePickerModal, whose single button
 * only closes.
 */

import { FC, useEffect, useState } from "react";
import { ConfirmModal, DialogButton, Focusable, Spinner } from "@decky/ui";
import { listCaseArt, debugLog, type CaseArtGrid } from "../api/backend";
import { applyCaseArt } from "../utils/caseArt";
import { detach } from "../utils/detach";
import { scrollFocusedToCenter } from "../utils/scrollHelpers";
import { showToast } from "../utils/toast";
import { core } from "../theme/coreTokens";

export interface CaseArtPickerModalProps {
  romId: number;
  appId: number;
  romName: string;
  /** Injected by showModal. */
  closeModal?: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; grids: CaseArtGrid[]; selected: number | null }
  | { kind: "error"; message: string };

const FAILURE_TEXT: Record<string, string> = {
  no_api_key: "Set a SteamGridDB API key in settings first.",
  no_sgdb_game: "No SteamGridDB game is known for this ROM yet. Run Refresh Artwork first.",
  not_synced: "This game is not synced to Steam.",
};

/** One grid: a 2:3 frame with the thumbnail letterboxed on black, as it will look on the shelf. */
const GridTile: FC<{
  grid: CaseArtGrid;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}> = ({ grid, selected, disabled, onSelect }) => (
  <DialogButton
    onClick={onSelect}
    onFocus={scrollFocusedToCenter}
    disabled={disabled}
    aria-label={`Grid by ${grid.author || "unknown"}${selected ? ", in use" : ""}`}
    style={{ display: "flex", flexDirection: "column", gap: "6px", padding: "6px", height: "auto", minWidth: "0" }}
  >
    <div
      data-grid-id={grid.id}
      style={{
        width: "100%",
        aspectRatio: "2 / 3",
        background: "#000",
        borderRadius: "4px",
        overflow: "hidden",
        outline: selected ? `3px solid ${core.crimson}` : "none",
      }}
    >
      <img
        src={grid.thumb}
        alt=""
        loading="lazy"
        style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
      />
    </div>
    <div style={{ fontSize: "11px", color: core.white, lineHeight: "1.2", textAlign: "center" }}>
      {grid.author || "Unknown author"}
      {grid.curated ? " · case template" : ""}
    </div>
    <div style={{ fontSize: "10px", color: core.hint }}>
      {grid.width}×{grid.height}
      {selected ? " · in use" : ""}
    </div>
  </DialogButton>
);

export const CaseArtPickerModalContent: FC<CaseArtPickerModalProps> = ({ romId, appId, romName, closeModal }) => {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    let live = true;
    listCaseArt(romId)
      .then((res) => {
        if (!live) return;
        if (res.success) setState({ kind: "ready", grids: res.grids, selected: res.selected_grid_id });
        else setState({ kind: "error", message: FAILURE_TEXT[res.reason] ?? "Could not reach SteamGridDB." });
      })
      .catch((e: unknown) => {
        detach(debugLog(`CaseArtPickerModal: listCaseArt rejected: ${e}`));
        if (live) setState({ kind: "error", message: "Could not reach SteamGridDB." });
      });
    return () => {
      live = false;
    };
  }, [romId]);

  const choose = async (gridId: number) => {
    if (applying) return;
    setApplying(true);
    try {
      const outcome = await applyCaseArt(romId, appId, { gridId });
      if (outcome === "applied") {
        showToast("Cover changed");
        closeModal?.();
      } else {
        showToast("Could not apply that artwork");
      }
    } catch (e) {
      detach(debugLog(`CaseArtPickerModal: apply was cancelled: ${e}`));
    } finally {
      setApplying(false);
    }
  };

  return (
    <ConfirmModal
      {...(closeModal !== undefined ? { closeModal } : {})}
      onOK={() => closeModal?.()}
      onCancel={() => closeModal?.()}
      strTitle="Choose artwork"
      strOKButtonText="Close"
      bAlertDialog={true}
    >
      <Focusable flow-children="column" style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <div style={{ fontSize: "13px", color: core.steel }}>{romName}</div>
        {state.kind === "loading" ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "16px" }}>
            <div style={{ width: "32px", height: "32px" }}>
              <Spinner />
            </div>
          </div>
        ) : null}
        {state.kind === "error" ? <div style={{ fontSize: "12px", color: core.warning }}>{state.message}</div> : null}
        {state.kind === "ready" && state.grids.length === 0 ? (
          <div style={{ fontSize: "12px", color: core.hint }}>SteamGridDB has no portrait artwork for this game.</div>
        ) : null}
        {state.kind === "ready" && state.grids.length > 0 ? (
          <Focusable
            className="romm-case-art-grid"
            flow-children="right"
            onOKActionDescription="Use this cover"
            style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "10px" }}
          >
            {state.grids.map((grid) => (
              <GridTile
                key={grid.id}
                grid={grid}
                selected={grid.id === state.selected}
                disabled={applying}
                onSelect={() => {
                  detach(choose(grid.id));
                }}
              />
            ))}
          </Focusable>
        ) : null}
      </Focusable>
    </ConfirmModal>
  );
};
