/**
 * Install-integrity notice — shown at the top of the QAM when the installed plugin
 * folder does not match its build's install manifest.
 *
 * Decky Loader can leave a half-copied folder behind when it replaces the plugin
 * (docs/architecture/plugin-self-update.md#half-copied-installs), and the backend's
 * other callables may not exist at all then, so this component asks only the
 * one callable that is guaranteed to answer and renders nothing otherwise. The
 * button reinstalls the published build through Decky's own installer.
 */

import { useEffect, useState, FC } from "react";
import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { getInstallIntegrity, logError, type InstallIntegrity } from "../api/backend";
import { detach } from "../utils/detach";
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

/** The notice's title and body for a report, or `null` when there is nothing to say. */
export function integrityNotice(report: InstallIntegrity | null): { title: string; body: string } | null {
  if (!report?.success) return null;
  const target = shortVersion(report.expected_version || report.current_version);
  const reinstall = target ? `Reinstall ${target}` : "Reinstall it";
  if (report.status === "incomplete") {
    return {
      title: "Update didn't finish",
      body: `${PLUGIN_DISPLAY_NAME}'s last update didn't finish copying. ${reinstall}.`,
    };
  }
  if (report.status === "stale_files") {
    return {
      title: "Old files left behind",
      body: `${PLUGIN_DISPLAY_NAME}'s last update left files from an older version behind. ${reinstall} to clean them up.`,
    };
  }
  return null;
}

const HANDED_OFF = "Decky will ask you to confirm, then reload the plugin.";

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
  const reinstall = async () => {
    setBusy(true);
    setStatus("Downloading and verifying...");
    const err = await reinstallPlugin();
    setStatus(err || HANDED_OFF);
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
          onClick={() => detach(reinstall())}
          description={selfUpdate ? status || undefined : "This Decky Loader cannot install plugins from here."}
        >
          {target ? `Reinstall ${target}` : "Reinstall"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};
