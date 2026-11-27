/**
 * RomMGameInfoPanel — the RomM panel injected below the PlaySection on game
 * detail pages.
 *
 * The shell around the Overview / Achievements / Saves / Media / Details / BIOS
 * panes: it owns
 * the panel's ROM identity, its event lane, the tab selection, and the
 * whole-panel replacements (version mismatch, corrupt-settings reset, pending
 * RetroDECK migration) that pre-empt all of them. It also hosts the tabs and
 * Overview cards other plugins register (`utils/gamePageExtensions.ts`), handing
 * each the context of the ROM the panel shows at that render — so a version
 * switch reaches them through the same state write that re-keys the panes.
 *
 * The panel body itself takes no ROM-level actions — download, play, uninstall,
 * version and core selection live in the RomMPlaySection gear menu. The panes
 * below it are not all passive: the SAVES pane switches slots and rolls back
 * versions.
 *
 * CSS classes prefixed with `romm-panel-` are injected separately by styleInjector.
 */

import { useState, useEffect, useRef, useMemo, useCallback, FC } from "react";
import { Focusable } from "@decky/ui";
import { refreshMigrationState, logError } from "../api/backend";
import { AchievementsTab } from "./AchievementsTab";
import { BiosTab } from "./BiosTab";
import { PanelTabBar } from "./PanelTabBar";
import { SaveSortWarning } from "./SaveSortWarning";
import { bindRomInState, loadData, type PanelReadSeqs, type PanelState } from "./panelState";
import { wirePanelEvents } from "./panelEvents";
import { useSaveSlotsLoad } from "./panelSlotsLoad";
import { buildTabContent } from "./panelTabContent";
import { setMigrationStatus, useMigrationStatus } from "../utils/migrationStore";
import { useSettingsResetState } from "../utils/settingsResetStore";
import { setSaveSortMigrationStatus, useSaveSortMigrationState } from "../utils/saveSortMigrationStore";
import { VersionErrorCard, useVersionError } from "./VersionErrorCard";
import { MigrationBlockedCard } from "./MigrationBlockedCard";
import { SettingsResetCard } from "./SettingsResetCard";
import { detach } from "../utils/detach";
import {
  extensionLabel,
  extensionTabKey,
  useGamePageExtensions,
  visibleExtensions,
  DEFAULT_EXTENSION_ORDER,
  type RomPageContext,
} from "../utils/gamePageExtensions";
import { ExtensionOverviewCards, ExtensionTabPane } from "./GamePageExtensions";
import { GameContentSection } from "./GameContentSection";
import { RomOverviewCards } from "./RomOverviewCards";

function pageLocale(): string {
  return globalThis.navigator.language || "en";
}

interface RomMGameInfoPanelProps {
  appId: number;
}

export const RomMGameInfoPanel: FC<RomMGameInfoPanelProps> = ({ appId }) => {
  // Subscribe to version error — re-renders when global state changes
  const versionError = useVersionError();

  const [state, setState] = useState<PanelState>({
    loading: true,
    romId: null,
    romName: "",
    platformName: "",
    platformSlug: "",
    installed: false,
    installedRom: null,
    metadata: null,
    coverBase64: null,
    biosStatus: null,
    biosLevel: null,
    coreInfo: null,
    saveSyncEnabled: false,
    saveStatus: null,
    conflicts: [],
    error: false,
    activeTab: "info",
    raId: null,
    achievements: null,
    slotConfirmed: false,
    activeSlot: "default",
    activeSlotKnown: false,
    availableSlots: [],
    lastKnownSlots: null,
    slotsLoading: false,
    regions: [],
    languages: [],
  });
  const romIdRef = useRef<number | null>(null);
  // Tracks the panel's own platform so the broadcast `bios` data-changed
  // handler can reject events for other platforms without a stale closure
  // (mirrors romIdRef). bios events fan out to every mounted panel (#1082).
  const platformSlugRef = useRef<string>("");
  // Load-once gate for the lazy SAVES tab data; the rule it enforces is stated
  // at `panelSlotsLoad.ts`. It lives here because a version switch resets it.
  const slotsLoadedRef = useRef(false);
  // Read sequences ordering two answers about the same ROM; the rule they
  // enforce is stated at `takeReadTicket`. They live here because the loads, the
  // event lane and the lazy slots lane take tickets from the same counters.
  const readSeqs = useRef<PanelReadSeqs>({ detail: 0, saveStatus: 0, slots: 0, slotTracking: 0, bios: 0 });
  const migration = useMigrationStatus();
  const settingsReset = useSettingsResetState();
  const saveSortPending = useSaveSortMigrationState().pending;

  useEffect(() => {
    refreshMigrationState()
      .then(({ retrodeck, save_sort }) => {
        setMigrationStatus(retrodeck);
        setSaveSortMigrationStatus(save_sort);
      })
      .catch((e) => logError(`Failed to refresh migration state: ${e}`));
  }, [appId]);

  useEffect(() => {
    let cancelled = false;

    detach(loadData(appId, () => cancelled, romIdRef, platformSlugRef, readSeqs, setState));

    const unwire = wirePanelEvents({
      appId,
      cancelled: () => cancelled,
      romIdRef,
      platformSlugRef,
      slotsLoadedRef,
      readSeqs,
      setState,
    });

    return () => {
      cancelled = true;
      unwire();
    };
  }, [appId]);

  useSaveSlotsLoad(state, slotsLoadedRef, readSeqs, setState);

  const extensions = useGamePageExtensions();
  const openExtensionTab = useCallback(
    (extensionId: string) => setState((prev) => ({ ...prev, activeTab: extensionTabKey(extensionId) })),
    [],
  );
  const extensionCtx = useMemo<RomPageContext | null>(
    () =>
      state.romId
        ? {
            appId,
            romId: state.romId,
            name: state.romName,
            platformSlug: state.platformSlug,
            platformName: state.platformName,
            installed: state.installed,
            locale: pageLocale(),
            openTab: openExtensionTab,
          }
        : null,
    [appId, state.romId, state.romName, state.platformSlug, state.platformName, state.installed, openExtensionTab],
  );

  // --- Version mismatch — replace entire panel with polished error card ---
  if (versionError) {
    return (
      <div data-romm="true">
        <VersionErrorCard message={versionError} />
      </div>
    );
  }

  // --- Corrupt-settings reset — surface the reason instead of a bare "offline" ---
  if (settingsReset.pending) {
    return (
      <div data-romm="true">
        <SettingsResetCard backedUpTo={settingsReset.backedUpTo} compact={true} />
      </div>
    );
  }

  // --- Pending RetroDECK migration — block the page until resolved ---
  if (migration.pending) {
    return (
      <div data-romm="true">
        <MigrationBlockedCard />
      </div>
    );
  }

  // --- Loading state ---
  // Use minHeight so Steam's scroll container allocates enough space
  // before async data loads and expands the panel.
  if (state.loading) {
    return (
      <div data-romm="true" className="romm-panel-container" style={{ minHeight: "500px" }}>
        <div className="romm-panel-loading">Loading...</div>
      </div>
    );
  }

  // --- Error / not found state ---
  if (state.error || !state.romId || !extensionCtx) {
    return null;
  }

  const romId = state.romId;
  const ctx = extensionCtx;
  const extensionTabs = visibleExtensions(extensions, "tab", ctx);
  const activeExtension = extensionTabs.find((e) => extensionTabKey(e.extension.id) === state.activeTab) ?? null;
  // An extension tab that unregistered or stopped being available leaves the
  // user on the Overview, the tab every ROM has, instead of an empty body.
  const activeTab = state.activeTab.startsWith("ext:") && !activeExtension ? "info" : state.activeTab;
  const tabState = activeTab === state.activeTab ? state : { ...state, activeTab };

  return (
    <div data-romm="true">
      {saveSortPending ? <SaveSortWarning key="save-sort-warning" /> : null}
      <PanelTabBar
        activeTab={activeTab}
        hasAchievements={!!state.raId}
        hasSaves={state.saveSyncEnabled}
        hasBios={!!state.biosStatus}
        extensionTabs={extensionTabs.map((e) => ({
          id: extensionTabKey(e.extension.id),
          label: extensionLabel(e.extension, ctx.locale),
          order: e.extension.order ?? DEFAULT_EXTENSION_ORDER,
        }))}
        onSelect={(tabId) => setState((prev) => ({ ...prev, activeTab: tabId }))}
      />
      <Focusable noFocusRing={true} className="romm-tab-content" style={{ paddingBottom: "48px" }}>
        {activeTab === "info" ? (
          <ExtensionOverviewCards key="ext-cards" entries={extensions} ctx={ctx}>
            <RomOverviewCards
              raId={state.raId}
              achievements={state.achievements}
              saveSyncEnabled={state.saveSyncEnabled}
              saveStatus={state.saveStatus}
              conflictCount={state.conflicts.length}
              onOpenTab={(tabId) => setState((prev) => ({ ...prev, activeTab: tabId }))}
            />
          </ExtensionOverviewCards>
        ) : null}
        {activeExtension ? <ExtensionTabPane key="ext-tab" entry={activeExtension} ctx={ctx} /> : null}
        {buildTabContent({ appId, binding: bindRomInState(romId, setState), state: tabState })}
        {activeTab === "info" && state.installed ? (
          <GameContentSection key={`content-${romId}`} romId={romId} romName={state.romName} />
        ) : null}
        {/* Mounted for every ROM and rendering nothing until their tab is active.
            For achievements that is load-bearing: the list is fetched by the tab
            itself, and unmounting it on a tab switch would re-fetch (and re-spinner)
            on every visit. Its key is the ROM, so a version switch remounts it —
            which is how its per-rom state and load-once gate re-key. BiosTab needs
            no key: it renders from props and holds nothing of its own. */}
        <AchievementsTab
          key={`achievements-${romId}`}
          romId={romId}
          raId={state.raId}
          isActive={activeTab === "achievements"}
        />
        <BiosTab
          biosStatus={state.biosStatus}
          biosLevel={state.biosLevel}
          coreInfo={state.coreInfo}
          isActive={activeTab === "bios"}
        />
      </Focusable>
    </div>
  );
};
