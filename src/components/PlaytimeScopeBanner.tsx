import { FC } from "react";
import { PanelSection, PanelSectionRow, ButtonItem } from "@decky/ui";
import { setPlaytimeScopeState } from "../utils/playtimeScopeStore";
import { core, tint } from "../theme/coreTokens";

/** Title of the account-wide QAM playtime-scope banner. */
export const PLAYTIME_SCOPE_TITLE = "Cross-device playtime";

/** Body text prompting the user to re-mint a scoped Client API Token. */
export const PLAYTIME_SCOPE_MESSAGE = "Sign in again to enable cross-device playtime sync.";

/**
 * QAM PanelSection shown while the Client API Token lacks the `roms.user.read`
 * scope needed to read cross-device playtime. Account-wide (no per-game card).
 *
 * Dismiss is local-only — it just clears the shared store for this view. There
 * is no backend dismiss callable: the durable flag clears itself once a scoped
 * token is minted (a fresh sign-in or a later successful reconcile), so the
 * next MainPage mount re-fetches the real state.
 */
export const PlaytimeScopeBanner: FC = () => {
  const handleDismiss = () => {
    setPlaytimeScopeState({ pending: false });
  };

  return (
    <PanelSection title={PLAYTIME_SCOPE_TITLE}>
      <PanelSectionRow>
        <div
          style={{
            padding: "8px 12px",
            backgroundColor: tint(core.warning, 0.15),
            borderLeft: `3px solid ${core.warning}`,
            borderRadius: "4px",
          }}
        >
          <div
            style={{
              fontSize: "13px",
              fontWeight: "bold",
              color: core.warning,
              marginBottom: "6px",
            }}
          >
            {"⚠️"} {PLAYTIME_SCOPE_TITLE}
          </div>
          <div style={{ fontSize: "12px", color: core.text, lineHeight: 1.5 }}>{PLAYTIME_SCOPE_MESSAGE}</div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={handleDismiss}>
          Dismiss
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
};
