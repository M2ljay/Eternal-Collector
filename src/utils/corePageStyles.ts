/**
 * The Core design for a ROM game page: one stylesheet, injected once into
 * Steam's Big Picture document while a ROM page is open.
 *
 * Everything is scoped under `.romm-core-page` (the wrapper the game detail
 * patch puts in place of Steam's overview panel), plus the two Steam containers
 * that wrapper sits in, reached with `:has()` so a Steam game page is never
 * touched. The play bar keeps Steam's own play-section classes, so a rule Core UI
 * writes for Steam's play bar reaches both pages.
 *
 * Black means starfield (Core UI's design rule). Core UI draws its animated field
 * only on surfaces it knows; until it knows this page, a still field is painted
 * here, and only while Core UI is on (`html[data-core-ui]`). Without Core UI the
 * page is plain black. If Core UI attaches its own canvas to the page
 * (`data-core-ui-host="1"`), the still field steps aside.
 */

import { core, tint } from "../theme/coreTokens";
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

/** The stylesheet text; class-map rules are left out when a map is missing. */
export function corePageCss(): string {
  const page = `.${CORE_PAGE_CLASS}`;
  const inner = sel(appDetailsClasses?.InnerContainer);
  const art = sel(appDetailsHeaderClasses?.ImgContainer);
  const playContainer = sel(appActionButtonClasses?.PlayButtonContainer);
  const rules: string[] = [];
  if (inner) {
    rules.push(`${inner}:has(> ${page}) { background: ${core.black} !important; }`);
    if (art) {
      rules.push(
        `${inner}:has(> ${page}) ${art} { -webkit-mask-image: linear-gradient(180deg, #000 30%, transparent 100%); mask-image: linear-gradient(180deg, #000 30%, transparent 100%); }`,
      );
    }
  }
  rules.push(`
${page} { position: relative; isolation: isolate; background: ${core.black}; color: ${core.steel}; padding: 0 2.8vw 48px; box-sizing: border-box; }
${page} > .romm-core-stars { display: none; position: absolute; inset: 0; z-index: -1; pointer-events: none; background-image: ${starfieldSvg()}; background-repeat: repeat; }
html[data-core-ui] ${page}:not([data-core-ui-host="1"]) > .romm-core-stars { display: block; }
${page} .romm-core-header { padding-top: 24px; }
${page} .romm-core-title { font-size: 48px; font-weight: 700; color: ${core.white}; letter-spacing: -0.02em; line-height: 1.1; }
${page} .romm-core-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 16px; }
${page} .romm-core-chip { display: inline-flex; align-items: center; gap: 10px; height: 40px; padding: 0 16px; background: ${core.gunmetal}; color: ${core.steel}; font-size: 16px; font-weight: 600; border-radius: ${FLOAT}; }
${page} .romm-core-play-line { font-size: 16px; color: ${core.steel}; }
${page} .romm-core-playbar { display: flex; align-items: center; gap: 20px; margin: 20px 0 0; padding: 16px 24px; box-sizing: border-box; background: ${tint(core.gunmetal, 0.62)} !important; backdrop-filter: blur(18px); border-radius: ${FLOAT}; }
${page} .romm-core-status { font-size: 16px; color: ${core.steel}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
${page} .romm-native-play, ${page} .romm-btn-play${playContainer ? `, ${page} ${playContainer}` : ""} { background: ${core.crimson} !important; color: ${core.white} !important; border-radius: 0 !important; }
${page} .romm-native-play.gpfocus, ${page} .romm-native-play:focus, ${page} .romm-btn-play.gpfocus, ${page} .romm-btn-play:focus { box-shadow: 0 0 0 3px ${core.white} !important; outline: none !important; filter: none !important; }
${page} .romm-native-menu-btn, ${page} .romm-gear-btn { background: ${core.gunmetal} !important; color: ${core.steel} !important; border-radius: 0 !important; }
${page} .romm-native-menu-btn.gpfocus, ${page} .romm-gear-btn.gpfocus { background: ${core.gunmetalRaised} !important; outline: 2px solid ${core.crimson} !important; outline-offset: 0 !important; }
${page} .romm-tab-bar { display: flex; gap: 32px; margin: 20px 0 16px; padding: 0 !important; background: transparent !important; border-bottom: 1px solid ${core.gunmetal} !important; }
${page} .romm-tab-content { padding: 0 !important; background: transparent !important; }
${page} .romm-tab { background: transparent !important; border: none !important; border-radius: 0 !important; padding: 12px 0 !important; min-width: 0 !important; width: auto !important; font-size: 18px !important; font-weight: 500 !important; color: ${core.hint} !important; box-shadow: inset 0 -3px 0 transparent; }
${page} .romm-tab.romm-tab-active { color: ${core.white} !important; font-weight: 600 !important; box-shadow: inset 0 -3px 0 ${core.crimson}; }
${page} .romm-tab.gpfocus { background: ${core.gunmetal} !important; color: ${core.white} !important; outline: none !important; }
${page} .romm-core-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; margin-bottom: 24px; }
${page} .romm-core-card { min-height: 150px; box-sizing: border-box; padding: 20px 22px !important; background: ${core.gunmetal} !important; border-radius: ${FLOAT} !important; text-align: left !important; color: ${core.steel} !important; width: auto !important; min-width: 0 !important; }
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
