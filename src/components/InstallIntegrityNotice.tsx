/**
 * Install-integrity notice — shown at the top of the QAM when the installed plugin
 * folder does not match its build's install manifest.
 *
 * Decky Loader can leave a half-copied folder behind when it replaces the plugin
 * (docs/architecture/plugin-self-update.md#half-copied-installs), and the backend's
 * other callables may not exist at all then, so this component asks only the
 * one callable that is guaranteed to answer and renders nothing otherwise. The
 * button reinstalls the published build through Decky's own installer or, once
 * the backend restored the missing files from its kept copy of the build,
 * restarts the plugin so they load.
 */

import { useEffect, useState, FC } from "react";
import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { getInstallIntegrity, logError, type InstallIntegrity } from "../api/backend";
import { detach } from "../utils/detach";
import { reloadPlugin } from "../utils/installHandoff";
import { canSelfUpdate, reinstallPlugin } from "../utils/pluginUpdate";
import { PLUGIN_DISPLAY_NAME } from "../utils/toast";
import { core, tint } from "../theme/coreTokens";

type Shown = Extract<InstallIntegrity, { success: true }>;

/** `0.33.0-win.19` → `win.19`; any other version is shown whole. */
export function shortVersion(version: string | null | undefined): string {
  if (!version) return "";
  const match = /-(win\.\d+)$/.exec(version);
  return match?.[1] ?? version;
}

export interface Notice {
  title: string;
  body: string;
  action: "reinstall" | "restart";
}

/** The notice's title, body and button for a report, or `null` when there is nothing to say. */
export function integrityNotice(report: InstallIntegrity | null): Notice | null {
  if (!report?.success) return null;
  const target = shortVersion(report.expected_version || report.current_version);
  const reinstall = target ? `Reinstall ${target}` : "Reinstall it";
  if (report.status === "incomplete") {
    return {
      title: "Install cut short",
      body: `Reinstall ${PLUGIN_DISPLAY_NAME} — the last install was cut short.`,
      action: "reinstall",
    };
  }
  if (report.restart_needed && report.repaired?.length) {
    const files = report.repaired.length === 1 ? "1 file" : `${report.repaired.length} files`;
    return {
      title: "Files restored",
      body: `${PLUGIN_DISPLAY_NAME} restored ${files} the last install didn't copy. Restart it to load them.`,
      action: "restart",
    };
  }
  if (report.status === "stale_files") {
    return {
      title: "Old files left behind",
      body: `${PLUGIN_DISPLAY_NAME}'s last update left files from an older version behind. ${reinstall} to clean them up.`,
      action: "reinstall",
    };
  }
  return null;
}

const HANDED_OFF = "Decky will ask you to confirm, then reload the plugin.";
const RESTARTING = "Decky is restarting the plugin.";

export const InstallIntegrityNotice: FC = () => {
  const [report, setReport] = useState<Shown | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    let live = true;
    detach(
      getInstallIntegrity().then(
        (answer) => {
          if (live && answer.success) setReport(answer);
        },
        (e) => logError(`InstallIntegrityNotice: check failed: ${e}`),
      ),
    );
    return () => {
      live = false;
    };
  }, []);

  const notice = integrityNotice(report);
  if (!notice || !report) return null;

  const selfUpdate = canSelfUpdate();
  const target = shortVersion(report.expected_version || report.current_version);
  const restart = notice.action === "restart";
  const run = async () => {
    setBusy(true);
    setStatus(restart ? "Restarting..." : "Downloading and verifying...");
    const err = restart ? await reloadPlugin() : await reinstallPlugin();
    setStatus(err || (restart ? RESTARTING : HANDED_OFF));
    setBusy(false);
  };

  return (
    <PanelSection title={notice.title}>
      <PanelSectionRow>
        <div
          style={{
            padding: "8px 12px",
            backgroundColor: tint(core.warning, 0.15),
            borderLeft: `3px solid ${core.warning}`,
            borderRadius: "4px",
            fontSize: "13px",
            lineHeight: 1.5,
            color: core.text,
          }}
        >
          {notice.body}
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy || !selfUpdate}
          onClick={() => detach(run())}
          description={selfUpdate ? status || undefined : "This Decky Loader cannot install plugins from here."}
        >
          {restart ? `Restart ${PLUGIN_DISPLAY_NAME}` : target ? `Reinstall ${target}` : "Reinstall"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};
