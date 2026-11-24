/**
 * Plugin updates — the fork build's own update channel (Windows only).
 *
 * Self-contained: loads its own state on mount and renders nothing on a build
 * the backend reports as unsupported (the Decky store build, any Linux build),
 * so that flow is untouched. The install and rollback buttons only hand the
 * work to Decky Loader, which asks for confirmation itself; the button text says
 * so instead of claiming the update happened.
 */

import { useState, useEffect, FC } from "react";
import { PanelSection, PanelSectionRow, ButtonItem, Field } from "@decky/ui";
import { checkPluginUpdate, getPluginRollback, logError } from "../../api/backend";
import type { PluginUpdateCheck, PluginRollback } from "../../api/backend";
import { detach } from "../../utils/detach";
import { canSelfUpdate, installPluginUpdate, rollbackPlugin, updateOffered } from "../../utils/pluginUpdate";

const HANDED_OFF = "Decky will ask you to confirm, then reload the plugin.";

function formatSize(bytes?: number): string {
  if (!bytes) return "";
  return ` (${(bytes / (1024 * 1024)).toFixed(1)} MB)`;
}

export const PluginUpdateSection: FC = () => {
  const [check, setCheck] = useState<PluginUpdateCheck | null>(null);
  const [rollback, setRollback] = useState<PluginRollback | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  async function refresh(force: boolean) {
    setBusy(true);
    try {
      const result = await checkPluginUpdate(force);
      setCheck(result);
      if (!result.success) setStatus(result.message);
      else if (force) setStatus(result.update_available ? "" : "You have the newest build.");
      setRollback(await getPluginRollback());
    } catch (e) {
      logError(`PluginUpdateSection: check failed: ${e}`);
      setStatus("Could not check for updates.");
    }
    setBusy(false);
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial async data load on mount
    detach(refresh(false));
  }, []);

  if (!check || (check.success && !check.supported)) return null;

  const handOff = async (action: () => Promise<string>) => {
    setBusy(true);
    setStatus("Downloading and verifying...");
    const err = await action();
    setStatus(err || HANDED_OFF);
    setBusy(false);
  };

  const offered = updateOffered(check) ? check : null;
  const kept = rollback?.success && rollback.available ? rollback : null;
  const selfUpdate = canSelfUpdate();

  return (
    <PanelSection title="Plugin Updates">
      <PanelSectionRow>
        <Field label="Installed" description={offered?.notes || undefined}>
          {check.current}
        </Field>
      </PanelSectionRow>
      {offered && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy || !selfUpdate}
            onClick={() => detach(handOff(installPluginUpdate))}
            description={selfUpdate ? undefined : "This Decky Loader cannot install plugins from here."}
          >
            {`Install ${offered.version}${formatSize(offered.size)}`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => detach(refresh(true))}>
          Check for Updates
        </ButtonItem>
      </PanelSectionRow>
      {kept && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={busy || !selfUpdate}
            onClick={() => detach(handOff(rollbackPlugin))}
            description="Reinstalls the build that was replaced by the last update."
          >
            {`Roll Back to ${kept.version}`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {status && (
        <PanelSectionRow>
          <Field description={status} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
};
