/**
 * The Collector's stylesheet. Rendered as a <style> element by the row and the
 * console page themselves, so nothing is injected into Steam's document while the
 * plugin is unloaded, and every selector is prefixed `tc-` so none can reach
 * Steam's own elements. No Steam class names are used: they are hashed per build.
 *
 * Palette: black #000000, gunmetal #1A1D21, crimson #D7263D, steel #C9D1D9.
 */

export const COLLECTOR_CSS = `
.tc-shelf{padding:8px 0 24px;color:#C9D1D9;min-width:0}
.tc-shelf__title{font-size:20px;line-height:1.3;font-weight:600;margin:0 0 12px;color:#fff}
.tc-shelf__row{display:flex;gap:16px;overflow-x:auto;overflow-y:visible;padding:10px 4px 14px;scrollbar-width:none}
.tc-shelf__row::-webkit-scrollbar{display:none}

.tc-tile{flex:0 0 auto;width:248px;box-sizing:border-box;padding:12px 12px 14px;border-radius:6px;background:#000;
  color:#C9D1D9;transition:transform .14s ease-out,box-shadow .14s ease-out,background-color .14s ease-out;cursor:pointer}
.tc-tile.tc-focus,.tc-tile.gpfocus,.tc-tile:focus-visible{background:#1A1D21;box-shadow:0 0 0 3px #D7263D;
  transform:translateY(-6px);outline:none}
.tc-tile__media{height:136px;display:flex;align-items:flex-end;justify-content:center;margin-bottom:12px}
.tc-tile__name{font-size:17px;font-weight:600;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-tile__meta{font-size:13px;color:#C9D1D9;opacity:.85;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.tc-media{display:flex;align-items:flex-end;justify-content:center;gap:3px;height:100%}
.tc-media__item{box-sizing:border-box;flex:0 0 auto;position:relative;border:1px solid #3a4048}
.tc-media--dvd-case .tc-media__item{width:20px;height:128px;background:linear-gradient(90deg,#14171b,#1A1D21 45%,#101215);border-radius:2px}
.tc-media--dvd-case .tc-media__item::before{content:"";position:absolute;left:0;right:0;top:8px;height:16px;background:#C9D1D9;opacity:.18}
.tc-media--dvd-case .tc-media__item:nth-child(3n+2){height:122px}
.tc-media--gc-box{gap:0}
.tc-media--gc-box .tc-media__item{width:78px;height:100px;background:linear-gradient(160deg,#20242a,#121418);border-radius:3px;
  margin-left:-44px;box-shadow:-3px 0 6px rgba(0,0,0,.6)}
.tc-media--gc-box .tc-media__item:first-child{margin-left:0}
.tc-media--gc-box .tc-media__item::before{content:"";position:absolute;left:0;right:0;top:0;height:14px;background:#C9D1D9;opacity:.16}
.tc-media--jewel-case{flex-direction:column-reverse;align-items:center;justify-content:flex-start;gap:2px}
.tc-media--jewel-case .tc-media__item{width:112px;height:16px;background:linear-gradient(180deg,#2a3038,#14171b);border-radius:2px;border-color:#5b6470}
.tc-media--jewel-case .tc-media__item::before{content:"";position:absolute;left:8px;top:3px;bottom:3px;width:3px;background:#C9D1D9;opacity:.35}
.tc-media--jewel-case .tc-media__item:nth-child(even){transform:translateX(5px)}
.tc-media--snes-cart{gap:6px}
.tc-media--snes-cart .tc-media__item{width:44px;height:96px;background:#8a8f96;border-color:#5f646b;border-radius:4px 4px 2px 2px}
.tc-media--snes-cart .tc-media__item::before{content:"";position:absolute;left:6px;right:6px;top:16px;bottom:22px;background:#1A1D21;border-radius:2px}
.tc-media--snes-cart .tc-media__item::after{content:"";position:absolute;left:4px;right:4px;top:5px;height:5px;
  background:repeating-linear-gradient(90deg,#6d7279 0 3px,transparent 3px 6px)}
.tc-media--n64-cart{gap:6px}
.tc-media--n64-cart .tc-media__item{width:46px;height:88px;background:#2b2f35;border-color:#454b53;border-radius:12px 12px 3px 3px}
.tc-media--n64-cart .tc-media__item::before{content:"";position:absolute;left:7px;right:7px;top:14px;height:38px;background:#C9D1D9;opacity:.22;border-radius:2px}
.tc-media--nes-cart{gap:6px}
.tc-media--nes-cart .tc-media__item{width:40px;height:104px;background:#3a3f46;border-color:#555b63;border-radius:3px}
.tc-media--nes-cart .tc-media__item::before{content:"";position:absolute;left:6px;right:6px;top:10px;height:50px;background:#C9D1D9;opacity:.2}
.tc-media--small-cart{gap:8px}
.tc-media--small-cart .tc-media__item{width:34px;height:40px;background:#4a5058;border-color:#666d76;border-radius:3px 8px 3px 3px}
.tc-media--small-cart .tc-media__item::before{content:"";position:absolute;left:5px;right:5px;top:6px;height:18px;background:#C9D1D9;opacity:.3}
.tc-media--umd{gap:8px}
.tc-media--umd .tc-media__item{width:46px;height:50px;background:#1A1D21;border-radius:6px 6px 22px 22px;border-color:#4a515a}
.tc-media--umd .tc-media__item::before{content:"";position:absolute;left:9px;top:12px;width:26px;height:26px;border-radius:50%;
  border:2px solid #C9D1D9;opacity:.35}
.tc-media--keep-case .tc-media__item{width:22px;height:118px;background:linear-gradient(90deg,#15181c,#1f2328);border-radius:2px}

.tc-page{position:absolute;inset:0;overflow-y:auto;background:#000;color:#C9D1D9;padding:64px 48px 48px;box-sizing:border-box}
.tc-page__head{display:flex;align-items:baseline;gap:16px;margin-bottom:22px}
.tc-page__title{font-size:30px;font-weight:700;color:#fff;margin:0}
.tc-page__count{font-size:15px;color:#C9D1D9;opacity:.8}
.tc-page__section{font-size:15px;letter-spacing:.08em;text-transform:uppercase;color:#C9D1D9;opacity:.75;margin:22px 0 10px}
.tc-page__status{font-size:15px;color:#C9D1D9;opacity:.8;padding:12px 0}
.tc-grid{display:flex;flex-direction:column;gap:18px}
.tc-grid__row{display:flex;gap:18px}

.tc-case{flex:0 0 auto;width:180px;box-sizing:border-box;padding:10px;border-radius:6px;background:#000;cursor:pointer;
  transition:transform .14s ease-out,box-shadow .14s ease-out,background-color .14s ease-out}
.tc-case.tc-focus,.tc-case.gpfocus,.tc-case:focus-visible{background:#1A1D21;box-shadow:0 0 0 3px #D7263D;transform:translateY(-5px);outline:none}
.tc-case--continue{width:260px}
.tc-case__shell{position:relative;width:100%;overflow:hidden;background:#1A1D21;border:1px solid #3a4048;box-sizing:border-box}
.tc-case__art{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.tc-case__fallback{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:10px;text-align:center;
  font-size:14px;font-weight:600;color:#C9D1D9}
.tc-case--dvd-case .tc-case__shell,.tc-case--keep-case .tc-case__shell{aspect-ratio:7/10;border-radius:4px;border-top:10px solid #2b3036}
.tc-case--gc-box .tc-case__shell{aspect-ratio:14/19;border-radius:4px;border-top:8px solid #2b3036}
.tc-case--jewel-case .tc-case__shell{aspect-ratio:1/1;border-radius:2px;border-left:8px solid #2b3036}
.tc-case--snes-cart .tc-case__shell{aspect-ratio:10/8;border-radius:8px 8px 3px 3px;border:8px solid #8a8f96;border-top-width:16px}
.tc-case--n64-cart .tc-case__shell{aspect-ratio:10/8;border-radius:16px 16px 4px 4px;border:8px solid #2b2f35;border-top-width:16px}
.tc-case--nes-cart .tc-case__shell{aspect-ratio:3/4;border-radius:4px;border:7px solid #3a3f46;border-top-width:14px}
.tc-case--small-cart .tc-case__shell{aspect-ratio:1/1;border-radius:4px 14px 4px 4px;border:7px solid #4a5058}
.tc-case--umd .tc-case__shell{aspect-ratio:9/10;border-radius:8px 8px 40px 40px;border:6px solid #1A1D21}
.tc-case__name{font-size:14px;font-weight:600;color:#fff;margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-case__meta{font-size:12px;opacity:.8;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tc-case__chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
.tc-chip{font-size:11px;line-height:16px;padding:1px 7px;border-radius:9px;border:1px solid #3a4048;color:#C9D1D9;white-space:nowrap}
.tc-chip--synced{border-color:#C9D1D9}
.tc-chip--pending{border-color:#C9D1D9;color:#fff}
.tc-chip--conflict{border-color:#D7263D;color:#fff;background:#D7263D}
.tc-chip--hardcore{border-color:#D7263D}
.tc-chip--award{border-color:#D7263D;color:#fff}
.tc-more{margin-top:20px}
`;
