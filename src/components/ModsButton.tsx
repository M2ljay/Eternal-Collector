/**
 * The game page's Mods button. Shown only under the Windows native look (where
 * EmuDeck for Windows is the launcher) and only for an installed game; the panel
 * it opens says plainly when the emulator has no known mod folder. Hidden while
 * Forge has registered its Mods tab (`forge.mods`): that tab replaces the panel,
 * and still installs through The Collector's mods bridge.
 */

import type { FC } from "react";
import { PuzzleIcon } from "./icons";
import { nativeLook, NativeMenuButton } from "../utils/nativeLook";
import { showModsModal } from "./ModsModal";
import { FORGE_MODS_EXTENSION_ID, hasGamePageExtension, useGamePageExtensions } from "../utils/gamePageExtensions";

interface ModsButtonProps {
  romId: number | null;
  romName: string;
  installed: boolean;
  onFocus: (e: { currentTarget: EventTarget | null }) => void;
}

export const ModsButton: FC<ModsButtonProps> = ({ romId, romName, installed, onFocus }) => {
  const extensions = useGamePageExtensions();
  if (!nativeLook() || !installed || !romId || hasGamePageExtension(extensions, FORGE_MODS_EXTENSION_ID)) return null;
  return (
    <NativeMenuButton onClick={() => showModsModal(romId, romName)} onFocus={onFocus} title="Mods">
      <PuzzleIcon size={22} />
    </NativeMenuButton>
  );
};
