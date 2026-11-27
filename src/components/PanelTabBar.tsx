/**
 * PanelTabBar — the tab strip at the top of the RomM game detail panel.
 *
 * A tab exists only when its pane has something to show, which is why the panel
 * passes the three optional panes' presence rather than the state they are
 * derived from. Tabs other plugins registered (`utils/gamePageExtensions.ts`)
 * arrive already filtered and labelled, and are merged in by order; Overview
 * stays first. The active tab carries one crimson underline (Core design).
 *
 * CSS classes prefixed with `romm-tab` are styled by styleInjector and, on the
 * Core page, by `utils/corePageStyles.ts`.
 */

import { FC } from "react";
import { DialogButton, Focusable } from "@decky/ui";
import { BUILTIN_TAB_ORDER } from "../utils/gamePageExtensions";

/** A tab another plugin contributed: `id` is the panel's `activeTab` key for it. */
export interface ExtensionTabItem {
  id: string;
  label: string;
  order: number;
}

interface PanelTabBarProps {
  activeTab: string;
  hasAchievements: boolean;
  hasSaves: boolean;
  hasBios: boolean;
  extensionTabs?: readonly ExtensionTabItem[];
  onSelect: (tabId: string) => void;
}

export const PanelTabBar: FC<PanelTabBarProps> = ({
  activeTab,
  hasAchievements,
  hasSaves,
  hasBios,
  extensionTabs = [],
  onSelect,
}) => {
  const builtin: { id: string; label: string; order: number; visible: boolean }[] = [
    { id: "info", label: "Overview", order: BUILTIN_TAB_ORDER.info, visible: true },
    { id: "achievements", label: "Achievements", order: BUILTIN_TAB_ORDER.achievements, visible: hasAchievements },
    { id: "saves", label: "Saves", order: BUILTIN_TAB_ORDER.saves, visible: hasSaves },
    { id: "media", label: "Media", order: BUILTIN_TAB_ORDER.media, visible: true },
    { id: "details", label: "Details", order: BUILTIN_TAB_ORDER.details, visible: true },
    { id: "bios", label: "BIOS", order: BUILTIN_TAB_ORDER.bios, visible: hasBios },
  ];
  // Stable sort: a built-in tab wins a tie because it is listed first.
  const tabs = [
    ...builtin,
    ...extensionTabs.map((t) => ({ ...t, order: Math.max(t.order, BUILTIN_TAB_ORDER.info + 1), visible: true })),
  ].sort((a, b) => a.order - b.order);

  return (
    <Focusable className="romm-tab-bar" flow-children="right" data-romm="true">
      {tabs
        .filter((t) => t.visible)
        .map((t) => (
          <DialogButton
            key={`tab-${t.id}`}
            className={`romm-tab ${activeTab === t.id ? "romm-tab-active" : ""}`}
            onClick={() => onSelect(t.id)}
            noFocusRing={false}
          >
            {t.label}
          </DialogButton>
        ))}
    </Focusable>
  );
};
