/**
 * The Core design for a ROM game page: one stylesheet, injected once into
 * Steam's Big Picture document while a ROM page is open.
 *
 * The layout is Clean Gameview's: screen one is the hero art filling the view
 * (cover, dimmed), the logo locked bottom-left and a transparent play bar above
 * the footer; screen two, one scroll down, is black. Everything is scoped under
 * `.romm-core-page` (the wrapper the game detail patch puts in place of Steam's
 * overview panel) or reaches Steam's header through `InnerContainer:has(>
 * .romm-core-page)`, so a Steam game page is never touched. The play bar keeps
 * Steam's own play-section classes, so a rule Core UI writes for Steam's play bar
 * reaches both pages.
 *
 * Black means starfield (Core UI's design rule). Core UI draws its animated field
 * only on surfaces it knows; until it knows this page, a still field is painted
 * here, and only while Core UI is on (`html[data-core-ui]`). Without Core UI the
 * page is plain black. If Core UI attaches its own canvas to the page
 * (`data-core-ui-host="1"`), the still field steps aside.
 */

import { core } from "../theme/coreTokens";
import { appActionButtonClasses, appDetailsClasses, appDetailsHeaderClasses, findSP } from "./deckyUiInternals";

export const CORE_PAGE_STYLE_ID = "romm-core-page-styles";
export const CORE_PAGE_CLASS = "romm-core-page";
const FLOAT = "var(--core-radius-float, 10px)";

/** A seeded field of faint stars: none brighter than Core UI's 24% ceiling. */
export function starfieldSvg(seed = 7, count = 36, width = 640, height = 400): string {
  let x = seed;
  const next = () => {
    x = (x * 16807) % 2147483647;
    return x / 2147483647;
  };
  let dots = "";
  for (let i = 0; i < count; i++) {
    const r = (0.6 + next() * 1.6).toFixed(1);
    const a = (0.08 + next() * 0.16).toFixed(2);
    dots += `<circle cx='${Math.round(next() * width)}' cy='${Math.round(next() * height)}' r='${r}' fill='%23fff' fill-opacity='${a}'/>`;
  }
  return `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}'>${dots}</svg>")`;
}

function sel(cls: string | undefined): string | null {
  return cls ? `.${cls.split(" ")[0]}` : null;
}

/**
 * Screen one's measures, from the Clean Gameview theme (shared.css) that Core's
 * restyle of Steam's own game page uses too: an 80px play bar above a 40px
 * footer, the logo at most 120px tall, the art at 60% brightness.
 */
export const GAME_VIEW = { playbar: 80, footer: 40, logo: 120, brightness: 0.6 } as const;

/** The stylesheet text; class-map rules are left out when a map is missing. */
export function corePageCss(): string {
  const page = `.${CORE_PAGE_CLASS}`;
  const inner = sel(appDetailsClasses?.InnerContainer);
  const h = appDetailsHeaderClasses;
  const playContainer = sel(appActionButtonClasses?.PlayButtonContainer);
  const bar = `var(--romm-gv-playbar, ${GAME_VIEW.playbar}px)`;
  const foot = `var(--romm-gv-footer, ${GAME_VIEW.footer}px)`;
  const rules: string[] = [];
  if (inner) {
    const on = `${inner}:has(> ${page})`;
    rules.push(`${on} { background: ${core.black} !important; }`);
    const header: [string | undefined, string][] = [
      [h?.TopCapsule, `height: calc(100vh - ${bar} - ${foot}) !important;`],
      [h?.HeaderBackgroundImage, "height: 100vh !important;"],
      [
        h?.ImgSrc,
        `object-fit: cover !important; object-position: center !important; filter: brightness(${GAME_VIEW.brightness}) !important;`,
      ],
      [h?.TopGradient, "background: transparent !important;"],
      [
        h?.BoxSizer,
        `top: calc(100vh - ${GAME_VIEW.logo}px * 1.3 - ${bar} - ${foot}) !important; max-height: ${GAME_VIEW.logo}px !important;`,
      ],
    ];
    for (const [cls, body] of header) {
      const s = sel(cls);
      if (s) rules.push(`${on} ${s} { ${body} }`);
    }
  }
  rules.push(`
${page} { position: relative; isolation: isolate; color: ${core.steel}; padding: 0 0 48px; box-sizing: border-box; background: linear-gradient(180deg, transparent calc(${bar} + ${foot}), ${core.black} calc(${bar} + ${foot})); }
${page} > .romm-core-stars { display: none; position: absolute; left: 0; right: 0; top: calc(${bar} + ${foot}); bottom: 0; z-index: -1; pointer-events: none; background-image: ${starfieldSvg()}; background-repeat: repeat; }
html[data-core-ui] ${page}:not([data-core-ui-host="1"]) > .romm-core-stars { display: block; }
${page} .romm-core-playbar { height: calc(${bar} + ${foot}) !important; margin: 0 !important; padding: 0 2.8vw ${foot} !important; box-sizing: border-box; display: flex; align-items: center; background: transparent !important; backdrop-filter: none !important; border-radius: 0 !important; }
${page} .romm-native-play, ${page} .romm-btn-play${playContainer ? `, ${page} ${playContainer}` : ""} { background: ${core.crimson} !important; color: ${core.white} !important; border-radius: 0 !important; }
${page} .romm-native-play.gpfocus, ${page} .romm-native-play:focus, ${page} .romm-btn-play.gpfocus, ${page} .romm-btn-play:focus { box-shadow: 0 0 0 3px ${core.white} !important; outline: none !important; filter: none !important; }
${page} .romm-core-playbar .romm-native-menu-btn { width: 48px !important; height: 48px !important; min-width: 48px !important; padding: 0 !important; display: flex !important; align-items: center; justify-content: center; background: ${core.black} !important; color: ${core.steel} !important; border-radius: 0 !important; }
${page} .romm-core-playbar .romm-native-menu-btn.gpfocus { background: ${core.gunmetal} !important; color: ${core.white} !important; outline: 2px solid ${core.crimson} !important; outline-offset: 0 !important; }
${page} .romm-core-below { padding: 28px 2.8vw 0; }
${page} .romm-core-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
${page} .romm-core-chip { display: inline-flex; align-items: center; gap: 10px; height: 40px; padding: 0 16px; background: ${core.gunmetal}; color: ${core.steel}; font-size: 16px; font-weight: 600; border-radius: ${FLOAT}; }
${page} .romm-tab-bar { display: flex; gap: 32px; margin: 20px 0 16px; padding: 0 !important; background: transparent !important; border-bottom: 1px solid ${core.gunmetal} !important; }
${page} .romm-tab-content { padding: 0 !important; background: transparent !important; }
${page} .romm-tab { background: transparent !important; border: none !important; border-radius: 0 !important; padding: 12px 0 !important; min-width: 0 !important; width: auto !important; font-size: 18px !important; font-weight: 500 !important; color: ${core.hint} !important; box-shadow: inset 0 -3px 0 transparent; }
${page} .romm-tab.romm-tab-active { color: ${core.white} !important; font-weight: 600 !important; box-shadow: inset 0 -3px 0 ${core.crimson}; }
${page} .romm-tab.gpfocus { background: ${core.gunmetal} !important; color: ${core.white} !important; outline: none !important; }
${page} .romm-core-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; margin-bottom: 24px; }
${page} .romm-core-card { width: 100% !important; min-height: 150px; box-sizing: border-box; padding: 20px 22px !important; background: ${core.gunmetal} !important; border-radius: ${FLOAT} !important; text-align: left !important; color: ${core.steel} !important; min-width: 0 !important; }
${page} .romm-core-card.gpfocus { background: ${core.gunmetalRaised} !important; outline: 2px solid ${core.crimson} !important; outline-offset: 0 !important; }
${page} .romm-core-card-title { font-size: 13px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: ${core.steel}; }
${page} .romm-core-card-value { font-size: 28px; font-weight: 600; color: ${core.white}; margin-top: 12px; }
${page} .romm-core-card-note { font-size: 15px; color: ${core.hint}; margin-top: 8px; }
${page} .romm-core-status-chip { display: inline-flex; align-items: center; height: 36px; padding: 0 14px; margin-top: 12px; font-size: 16px; font-weight: 600; border-radius: ${FLOAT}; }
${page} .romm-ext-card { background: ${core.gunmetal}; border-radius: ${FLOAT}; padding: 4px; }
${page} .romm-core-media img { max-width: 240px; border-radius: 4px; display: block; margin-bottom: 16px; }
`);
  return rules.join("\n");
}

/** Put the stylesheet in Steam's document once; later calls only refresh its text. */
export function ensureCorePageStyles(): void {
  const doc = findSP()?.document;
  if (!doc) return;
  let style = doc.getElementById(CORE_PAGE_STYLE_ID);
  if (!style) {
    style = doc.createElement("style");
    style.id = CORE_PAGE_STYLE_ID;
    doc.head.appendChild(style);
  }
  const css = corePageCss();
  if (style.textContent !== css) style.textContent = css;
}
