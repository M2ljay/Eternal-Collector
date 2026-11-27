/* global module */
// Bundle-size gate for `pnpm size` (size-limit). The limit is a decision, not a ceiling to drift up to:
// raise it only with the reason written here.
//
// 830 KB -> 860 KB (0.33.0-win.30): the Forge bridge (game page registry and mods bridge), the mod kinds in the
// Mods panel (built-in toggles, cheat files) and the Updates & DLC section brought the bundle to about 834 KB.
// The margin is kept small so the next growth is a decision again.
module.exports = [
  {
    name: "dist/index.js (raw)",
    path: "dist/index.js",
    brotli: false,
    limit: "860 KB",
  },
];
