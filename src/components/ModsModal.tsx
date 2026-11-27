/**
 * The Mods panel for one game (EmuDeck on Windows): where its mods go under the
 * emulator it launches with, what is installed there, and installing from the
 * Downloads folder (a cheat file is renamed to the name the emulator looks
 * for), removing, switching the codes and patches the emulator already has,
 * turning on the emulator's setting and opening the folder.
 *
 * Nothing here holds a path the backend did not just report. Every write goes
 * through a confirmation that states what will happen, and the backend never
 * deletes: replaced and removed entries are moved to a backup folder whose
 * location the confirmation and the result toast both name.
 */

import { FC, useCallback, useEffect, useState, type ReactNode } from "react";
import { ConfirmModal, DialogButton, Focusable, ModalRoot, showModal } from "@decky/ui";
import {
  enableModSetting,
  getGameMods,
  installMod,
  listModSources,
  logError,
  openModFolder,
  previewModInstall,
  removeMod,
} from "../api/backend";
import { formatBytes } from "../utils/formatters";
import { showToast } from "../utils/toast";
import { detach } from "../utils/detach";
import type { GameModsAnswer, ModEntry, ModFailure, ModInstallPreview, ModSource, ModTarget } from "../types";
import { core } from "../theme/coreTokens";
import { ModBuiltinsSection } from "./ModBuiltinsSection";

const LABEL = { fontSize: "12px", color: core.hint } as const;
const BODY = { fontSize: "13px", color: core.text } as const;
const PATH = { fontSize: "12px", color: core.steel, wordBreak: "break-all" } as const;
const SECTION = {
  padding: "10px 12px",
  marginBottom: "10px",
  background: core.gunmetal,
  borderRadius: "4px",
} as const;
const PREVIEW_ROWS = 20;

type View =
  | { kind: "main" }
  | { kind: "sources"; target: ModTarget; sources: ModSource[] | null; folder: string; error: string | null }
  | { kind: "preview"; target: ModTarget; preview: ModInstallPreview };

function failureText(answer: ModFailure | undefined, fallback: string): string {
  return answer?.message || fallback;
}

export function entrySummary(entry: ModEntry): string {
  const parts: string[] = [];
  if (entry.is_dir && entry.files != null) parts.push(`${entry.files}${entry.partial ? "+" : ""} files`);
  if (entry.size != null) parts.push(formatBytes(entry.size));
  if (entry.modified) parts.push(new Date(entry.modified * 1000).toLocaleDateString());
  return parts.join(" · ");
}

function confirm(title: string, description: string, okText: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    showModal(
      <ConfirmModal
        strTitle={title}
        strDescription={description}
        strOKButtonText={okText}
        strCancelButtonText="Cancel"
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    );
  });
}

function settingHint(target: ModTarget, emulator: string): string | null {
  const setting = target.setting;
  if (!setting || setting.state === "on") return null;
  if (setting.state === "unknown") {
    return `Couldn't read whether ${setting.label} is on in ${emulator} (${setting.file}).`;
  }
  if (target.kind === "files") return `Texture packs are off in ${emulator} (${setting.label}).`;
  return `${setting.label} is off in ${emulator}; these have no effect until it is on.`;
}

interface ModsModalProps {
  romId: number;
  gameName: string;
  closeModal?: () => void;
}

export const ModsModal: FC<ModsModalProps> = ({ romId, gameName, closeModal }) => {
  const [answer, setAnswer] = useState<GameModsAnswer | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ kind: "main" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAnswer(await getGameMods(romId));
      setLoadError(null);
    } catch (e) {
      logError(`getGameMods failed: ${String(e)}`);
      setLoadError("Couldn't read this game's mod folders.");
    }
  }, [romId]);

  useEffect(() => {
    let cancelled = false;
    getGameMods(romId).then(
      (result) => {
        if (!cancelled) setAnswer(result);
      },
      (e: unknown) => {
        logError(`getGameMods failed: ${String(e)}`);
        if (!cancelled) setLoadError("Couldn't read this game's mod folders.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [romId]);

  const emulatorLabel = answer?.success ? (answer.emulator?.label ?? "the emulator") : "the emulator";

  const run = async <T,>(work: () => Promise<T>): Promise<T | null> => {
    if (busy) return null;
    setBusy(true);
    try {
      return await work();
    } catch (e) {
      logError(`mods action failed: ${String(e)}`);
      showToast("Something went wrong — nothing was changed that wasn't reported.");
      return null;
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (target: ModTarget, entry: ModEntry | null) => {
    const what = entry ? `${target.path}\\${entry.name}` : target.path;
    const size = entry ? entrySummary(entry) : "the whole game folder";
    const ok = await confirm(
      "Remove Mod",
      `Move ${what} (${size}) out of ${emulatorLabel}'s mod folder? It is moved to a romm-mod-backups folder, not deleted.`,
      "Remove",
    );
    if (!ok) return;
    const result = await run(() => removeMod(romId, target.target_id, entry ? entry.name : null));
    if (!result) return;
    showToast(result.success ? `Removed. Backup: ${result.backup_folder}` : failureText(result, "Couldn't remove it."));
    await load();
  };

  const handleEnable = async (target: ModTarget) => {
    const setting = target.setting;
    if (!setting) return;
    const ok = await confirm(
      `Turn On ${setting.label}`,
      `Close ${emulatorLabel} first. This sets [${setting.section}] ${setting.key} in ${setting.file}; a copy of the file is saved to romm-mod-backups before it is changed.`,
      "Turn On",
    );
    if (!ok) return;
    const result = await run(() => enableModSetting(romId, target.target_id));
    if (!result) return;
    showToast(result.success ? `${setting.label} is on.` : failureText(result, "Couldn't change the setting."));
    await load();
  };

  const handleOpen = async (target: ModTarget) => {
    const result = await run(() => openModFolder(romId, target.target_id));
    if (result && !result.success) showToast(failureText(result, "Couldn't open the folder."));
  };

  const handleBrowse = async (target: ModTarget) => {
    setView({ kind: "sources", target, sources: null, folder: "", error: null });
    const result = await run(() => listModSources(romId, target.target_id));
    if (!result) {
      setView({ kind: "sources", target, sources: [], folder: "", error: "Couldn't list the Downloads folder." });
    } else if (result.success) {
      setView({ kind: "sources", target, sources: result.entries, folder: result.folder, error: null });
    } else {
      setView({ kind: "sources", target, sources: [], folder: "", error: result.message });
    }
  };

  const handlePick = async (target: ModTarget, sourceName: string) => {
    const result = await run(() => previewModInstall(romId, target.target_id, sourceName));
    if (!result) return;
    if (!result.success) {
      showToast(failureText(result, "This can't be installed."));
      return;
    }
    setView({ kind: "preview", target, preview: result });
  };

  const handleInstall = async (target: ModTarget, preview: ModInstallPreview) => {
    const result = await run(() => installMod(romId, target.target_id, preview.source, preview.fingerprint));
    if (!result) return;
    if (result.success) {
      const backup = result.backup_folder ? ` Replaced files: ${result.backup_folder}` : "";
      showToast(`Installed ${result.written} files.${backup}`);
      setView({ kind: "main" });
      await load();
      return;
    }
    showToast(failureText(result, "Couldn't install it."));
    if (result.reason === "changed") await handlePick(target, preview.source);
    else if (result.reason === "partial") await load();
  };

  const header = (
    <div style={{ marginBottom: "10px" }}>
      <div style={{ fontSize: "16px", fontWeight: "bold", color: core.white }}>Mods — {gameName}</div>
      {answer?.success && answer.emulator ? (
        <div style={LABEL}>
          {answer.emulator.label}
          {answer.game_id ? ` · Game ID ${answer.game_id}` : ""}
        </div>
      ) : null}
    </div>
  );

  let body;
  if (loadError) {
    body = <div style={BODY}>{loadError}</div>;
  } else if (!answer) {
    body = <div style={BODY}>Reading this game&apos;s mod folders…</div>;
  } else if (!answer.success) {
    body = <div style={BODY}>{answer.message}</div>;
  } else if (view.kind === "sources") {
    body = (
      <SourcesView
        view={view}
        busy={busy}
        onPick={(s) => detach(handlePick(view.target, s.name))}
        onBack={() => setView({ kind: "main" })}
      />
    );
  } else if (view.kind === "preview") {
    body = (
      <PreviewView
        preview={view.preview}
        busy={busy}
        onInstall={() => detach(handleInstall(view.target, view.preview))}
        onBack={() => setView({ kind: "main" })}
      />
    );
  } else {
    body = (
      <Focusable flow-children="column" style={{ display: "flex", flexDirection: "column" }}>
        {answer.note ? <div style={{ ...BODY, marginBottom: "10px" }}>{answer.note}</div> : null}
        {answer.targets.map((target) => (
          <TargetSection
            key={target.target_id}
            target={target}
            hint={settingHint(target, emulatorLabel)}
            busy={busy}
            builtins={
              target.kind === "builtinToggle" ? (
                <ModBuiltinsSection romId={romId} target={target} emulatorLabel={emulatorLabel} />
              ) : null
            }
            onRemove={(entry) => detach(handleRemove(target, entry))}
            onEnable={() => detach(handleEnable(target))}
            onOpen={() => detach(handleOpen(target))}
            onBrowse={() => detach(handleBrowse(target))}
          />
        ))}
        {answer.omitted.map((o) => (
          <div key={o.label} style={{ ...LABEL, marginBottom: "6px" }}>
            Not offered: {o.label} — {o.reason}
          </div>
        ))}
      </Focusable>
    );
  }

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: "16px", minWidth: "520px" }}>
        {header}
        {body}
        <DialogButton onClick={() => closeModal?.()} style={{ marginTop: "8px" }}>
          Close
        </DialogButton>
      </div>
    </ModalRoot>
  );
};

interface TargetSectionProps {
  target: ModTarget;
  hint: string | null;
  busy: boolean;
  builtins: ReactNode;
  onRemove: (entry: ModEntry | null) => void;
  onEnable: () => void;
  onOpen: () => void;
  onBrowse: () => void;
}

const TargetSection: FC<TargetSectionProps> = ({
  target,
  hint,
  busy,
  builtins,
  onRemove,
  onEnable,
  onOpen,
  onBrowse,
}) => (
  <div style={SECTION}>
    <div style={{ fontSize: "14px", fontWeight: "bold", color: core.white }}>{target.label}</div>
    <div style={PATH}>
      {target.scope === "patch" ? `Beside the ROM: ${target.path}` : target.path}
      {target.scope === "shared" ? " (shared by every game)" : ""}
      {target.file_name ? ` — as ${target.file_name}` : ""}
    </div>
    {target.notes.map((note) => (
      <div key={note} style={LABEL}>
        {note}
      </div>
    ))}
    {hint ? (
      <Focusable flow-children="row" style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "6px" }}>
        <div style={{ ...BODY, color: core.warning, flex: 1 }}>{hint}</div>
        {target.setting?.can_enable ? (
          <DialogButton disabled={busy} onClick={onEnable} style={{ width: "auto", minWidth: "90px" }}>
            Turn On
          </DialogButton>
        ) : null}
      </Focusable>
    ) : null}
    {builtins}
    {target.scope === "toggle" ? null : (
      <div style={{ ...LABEL, marginTop: "8px" }}>
        {target.installed.length ? "Installed here:" : "Nothing installed here yet."}
      </div>
    )}
    {target.installed.map((entry) => (
      <Focusable
        key={entry.name}
        flow-children="row"
        style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}
      >
        <div style={{ flex: 1 }}>
          <div style={BODY}>
            {entry.name}
            {entry.is_dir ? "\\" : ""}
          </div>
          <div style={LABEL}>{entrySummary(entry)}</div>
        </div>
        <DialogButton disabled={busy} onClick={() => onRemove(entry)} style={{ width: "auto", minWidth: "90px" }}>
          Remove
        </DialogButton>
      </Focusable>
    ))}
    {target.installed_truncated ? <div style={LABEL}>More entries are in the folder than are listed.</div> : null}
    <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
      {target.accepts === "none" ? null : (
        <DialogButton disabled={busy} onClick={onBrowse}>
          Install from Downloads
        </DialogButton>
      )}
      <DialogButton disabled={busy} onClick={onOpen}>
        Open Folder
      </DialogButton>
      {target.scope === "game" && target.exists && target.installed.length ? (
        <DialogButton disabled={busy} onClick={() => onRemove(null)}>
          Remove All
        </DialogButton>
      ) : null}
    </Focusable>
  </div>
);

function sourceKindsText(target: ModTarget): string {
  if (target.accepts === "patch") return ".ips / .bps / .ups files, or a .zip holding one";
  if (target.accepts === "cheat_file") {
    const ext = target.file_name?.slice(target.file_name.lastIndexOf(".")) ?? "";
    return `a ${ext} file, or a .zip holding exactly one; it is saved as ${target.file_name ?? "the game's cheat file"}`;
  }
  return ".zip files and folders";
}

interface SourcesViewProps {
  view: Extract<View, { kind: "sources" }>;
  busy: boolean;
  onPick: (source: ModSource) => void;
  onBack: () => void;
}

const SourcesView: FC<SourcesViewProps> = ({ view, busy, onPick, onBack }) => {
  const kinds = sourceKindsText(view.target);
  return (
    <Focusable flow-children="column" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
      <div style={BODY}>
        Pick what to install as {view.target.label} ({kinds}).
      </div>
      {view.folder ? <div style={PATH}>{view.folder}</div> : null}
      {view.error ? <div style={BODY}>{view.error}</div> : null}
      {view.sources === null ? <div style={BODY}>Reading Downloads…</div> : null}
      {view.sources?.length === 0 && !view.error ? (
        <div style={BODY}>Nothing in Downloads fits. Put the mod there and try again.</div>
      ) : null}
      {view.sources?.map((source) => (
        <DialogButton key={source.name} disabled={busy || !source.supported} onClick={() => onPick(source)}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <div style={{ fontSize: "13px", color: core.white }}>
              {source.name}
              {source.is_dir ? "\\" : ""}
            </div>
            <div style={LABEL}>
              {source.supported ? entrySummary(source) : "Extract this archive first — only .zip can be installed."}
            </div>
          </div>
        </DialogButton>
      ))}
      <DialogButton onClick={onBack}>Back</DialogButton>
    </Focusable>
  );
};

interface PreviewViewProps {
  preview: ModInstallPreview;
  busy: boolean;
  onInstall: () => void;
  onBack: () => void;
}

const PreviewView: FC<PreviewViewProps> = ({ preview, busy, onInstall, onBack }) => (
  <Focusable flow-children="column" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
    <div style={BODY}>
      Install {preview.source}: {preview.write_count} files, {formatBytes(preview.total_bytes)}, into
    </div>
    <div style={PATH}>{preview.destination}</div>
    {preview.stripped_folder ? (
      <div style={LABEL}>
        The archive&apos;s own {preview.stripped_folder} folder is this game&apos;s folder, so its contents go straight
        in.
      </div>
    ) : null}
    {preview.replace_count ? (
      <div style={{ ...BODY, color: core.warning }}>
        {preview.replace_count} existing files will be replaced. They are moved to {preview.backup_root} first.
      </div>
    ) : (
      <div style={LABEL}>Nothing already there is replaced.</div>
    )}
    <div style={{ maxHeight: "180px", overflowY: "auto" }}>
      {preview.writes.slice(0, PREVIEW_ROWS).map((w) => (
        <div key={w.path} style={PATH}>
          {w.replaces ? "replace  " : "new  "}
          {w.path}
        </div>
      ))}
      {preview.write_count > PREVIEW_ROWS ? (
        <div style={LABEL}>…and {preview.write_count - PREVIEW_ROWS} more files.</div>
      ) : null}
    </div>
    <Focusable flow-children="row" style={{ display: "flex", gap: "8px" }}>
      <DialogButton disabled={busy} onClick={onInstall}>
        Install
      </DialogButton>
      <DialogButton onClick={onBack}>Back</DialogButton>
    </Focusable>
  </Focusable>
);

/** Open the Mods panel for a game. */
export function showModsModal(romId: number, gameName: string): void {
  showModal(<ModsModal romId={romId} gameName={gameName} />);
}
