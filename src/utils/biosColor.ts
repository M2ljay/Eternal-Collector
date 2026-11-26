import { core } from "../theme/coreTokens";
/**
 * Shared BIOS status-dot color mapping. The unmanaged/ok/partial/missing
 * CLASSIFICATION is a single backend source of truth
 * (`domain/bios.py::compute_bios_level`); every surface that renders a BIOS
 * status dot maps that level to a color through this one helper so the colors
 * never drift apart.
 *
 * Per-surface phrasing (the verbose label strings) stays in each component —
 * only the color mapping is shared here.
 */

/** Map a backend BIOS level to the status-dot colour.
 *  - `ok` → green
 *  - `partial` → amber
 *  - `missing` → crimson
 *  - `unmanaged` (no registry coverage — plugin makes no claim) → neutral
 *  - `null` (no level data) → neutral */
export function biosColorForLevel(level: "ok" | "partial" | "missing" | "unmanaged" | null): string {
  switch (level) {
    case "ok":
      return core.success;
    case "partial":
      return core.warning;
    case "missing":
      return core.crimson;
    case "unmanaged":
      return core.neutral;
    default:
      return core.neutral;
  }
}
