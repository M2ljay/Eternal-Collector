import { core } from "../../theme/coreTokens";

/**
 * The Collector's stylesheet. Rendered as a <style> element by the row and the
 * console page themselves, so nothing is injected into Steam's document while the
 * plugin is unloaded, and every selector is prefixed `tc-` so none can reach
 * Steam's own elements. No Steam class names are used: they are hashed per build.
 *
 * The Home row's geometry comes from CSS variables the row sets from Steam's own
 * Recent games row (`utils/steamRowGeometry.ts`); the defaults here are only the
 * fallback when that row cannot be measured.
 *
 * Colours come from the Core palette (`theme/coreTokens.ts`). The fixed greys left
 * in the `tc-case` shapes draw the physical cases and cartridges.
 */

/** Room inside the scrolling row for the focus ring and scale, given back by a negative margin. */
const FOCUS_ROOM = 16;
/** The least room at either end of the row for a tile's 3px ring, even when Steam's inset measures 0. */
const EDGE_ROOM = 8;

export const COLLECTOR_CSS = `
.tc-shelf{--tc-inset:24px;--tc-capsule-h:240px;--tc-gap:12px;--tc-pad-top:12px;--tc-title-gap:12px;--tc-pad-bottom:24px;
  box-sizing:border-box;padding:var(--tc-pad-top) 0 var(--tc-pad-bottom);color:${core.steel};min-width:0}
.tc-shelf__title{display:flex;align-items:center;gap:10px;margin:0 max(var(--tc-inset),${EDGE_ROOM}px) var(--tc-title-gap);color:${core.white};font-family:var(--tc-title-font,inherit);
  font-size:var(--tc-title-size,20px);font-weight:var(--tc-title-weight,600);line-height:var(--tc-title-lh,1.3);
  letter-spacing:var(--tc-title-ls,normal);text-transform:var(--tc-title-tt,none)}
.tc-shelf__row{display:flex;gap:var(--tc-gap);overflow-x:auto;overflow-y:hidden;box-sizing:border-box;
  padding:${FOCUS_ROOM}px max(var(--tc-inset),${EDGE_ROOM}px);margin:-${FOCUS_ROOM}px 0;
  scroll-padding-inline:max(var(--tc-inset),${EDGE_ROOM}px);scrollbar-width:none}
.tc-shelf__row::-webkit-scrollbar{display:none}

.tc-family{flex:0 0 auto;height:calc(var(--tc-capsule-h) * .82);aspect-ratio:16/9;cursor:pointer;outline:none}
.tc-family__card{position:relative;width:100%;height:100%;overflow:hidden;border-radius:var(--core-radius-float,10px);
  background:${core.gunmetal};transition:transform .14s ease-out,box-shadow .14s ease-out}
.tc-family.tc-focus .tc-family__card,.tc-family.gpfocus .tc-family__card,.tc-family:focus-visible .tc-family__card{
  transform:translateY(-4px);box-shadow:0 0 0 3px ${core.crimson}}
.tc-family__hero{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(.5)}
.tc-family__logo{position:absolute;left:50%;top:calc(50% - 2px);transform:translate(-50%,-50%);max-width:80%;max-height:36%;
  object-fit:contain}
.tc-family__name{position:absolute;inset:0 0 4px;display:flex;align-items:center;justify-content:center;padding:0 12px;
  text-align:center;font-size:calc(var(--tc-capsule-h) * .14);font-weight:700;color:${core.steel}}
.tc-family__tone{position:absolute;left:0;right:0;bottom:0;height:4px}

.tc-page{position:absolute;inset:0;overflow-y:auto;background:${core.black};color:${core.steel};padding:64px 48px 48px;box-sizing:border-box}
.tc-page__head{display:flex;align-items:baseline;gap:16px;margin-bottom:22px}
.tc-page__title{font-size:30px;font-weight:700;color:${core.white};margin:0}
.tc-page__count{font-size:15px;color:${core.steel};opacity:.8}
.tc-page__section{font-size:15px;letter-spacing:.08em;text-transform:uppercase;color:${core.steel};opacity:.75;margin:22px 0 10px}
.tc-page__status{font-size:15px;color:${core.steel};opacity:.8;padding:12px 0}
.tc-grid{display:flex;flex-direction:column;gap:18px}
.tc-grid__row{display:flex;gap:18px}

.tc-case{flex:0 0 auto;width:180px;box-sizing:border-box;padding:10px;border-radius:6px;background:${core.black};cursor:pointer;
  transition:transform .14s ease-out,box-shadow .14s ease-out,background-color .14s ease-out}
.tc-case.tc-focus,.tc-case.gpfocus,.tc-case:focus-visible{background:${core.gunmetal};box-shadow:0 0 0 3px ${core.crimson};transform:translateY(-5px);outline:none}
.tc-case--continue{width:260px}
.tc-case__shell{position:relative;width:100%;overflow:hidden;background:${core.gunmetal};border:1px solid ${core.gunmetalRaised};box-sizing:border-box}
.tc-case__art{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.tc-case__fallback{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:10px;text-align:center;
  font-size:14px;font-weight:600;color:${core.steel}}
.tc-case--dvd-case .tc-case__shell,.tc-case--keep-case .tc-case__shell{aspect-ratio:7/10;border-radius:4px;border-top:10px solid #2b3036}
.tc-case--gc-box .tc-case__shell{aspect-ratio:14/19;border-radius:4px;border-top:8px solid #2b3036}
.tc-case--jewel-case .tc-case__shell{aspect-ratio:1/1;border-radius:2px;border-left:8px solid #2b3036}
.tc-case--snes-cart .tc-case__shell{aspect-ratio:10/8;border-radius:8px 8px 3px 3px;border:8px solid #8a8f96;border-top-width:16px}
.tc-case--n64-cart .tc-case__shell{aspect-ratio:10/8;border-radius:16px 16px 4px 4px;border:8px solid #2b2f35;border-top-width:16px}
.tc-case--nes-cart .tc-case__shell{aspect-ratio:3/4;border-radius:4px;border:7px solid #3a3f46;border-top-width:14px}
.tc-case--small-cart .tc-case__shell{aspect-ratio:1/1;border-radius:4px 14px 4px 4px;border:7px solid #4a5058}
.tc-case--umd .tc-case__shell{aspect-ratio:9/10;border-radius:8px 8px 40px 40px;border:6px solid ${core.gunmetal}}
.tc-case__name{font-size:14px;font-weight:600;color:${core.white};margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-case__meta{font-size:12px;opacity:.8;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-case__chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.tc-chip{font-size:11px;line-height:16px;padding:1px 7px;border-radius:9px;border:1px solid ${core.gunmetalRaised};color:${core.steel};white-space:nowrap}
.tc-chip--synced{border-color:${core.success};color:${core.success}}
.tc-chip--pending{border-color:${core.warning};color:${core.warning}}
.tc-chip--conflict{border-color:${core.crimson};color:${core.white};background:${core.crimson}}
.tc-chip--hardcore{border-color:${core.crimson}}
.tc-chip--award{border-color:${core.crimson};color:${core.white}}
.tc-more{margin-top:20px}
`;
