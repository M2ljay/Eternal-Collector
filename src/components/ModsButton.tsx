/**
 * The game page's Mods button. Shown only under the Windows native look (where
 * EmuDeck for Windows is the launcher) and only for an installed game; the panel
 * it opens says plainly when the emulator has no known mod folder.
 */

import type { FC } from "react";
import { FaPuzzlePiece } from "react-icons/fa";
import { nativeLook, NativeMenuButton } from "../utils/nativeLook";
import { showModsModal } from "./ModsModal";

interface ModsButtonProps {
  romId: number | null;
  romName: string;
  installed: boolean;
  onFocus: (e: { currentTarget: EventTarget | null }) => void;
}

export const ModsButton: FC<ModsButtonProps> = ({ romId, romName, installed, onFocus }) => {
  if (!nativeLook() || !installed || !romId) return null;
  return (
    <NativeMenuButton onClick={() => showModsModal(romId, romName)} onFocus={onFocus} title="Mods">
      <FaPuzzlePiece size={22} />
    </NativeMenuButton>
  );
};
