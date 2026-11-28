/**
 * Reads the geometry of Steam's own Recent games row from the DOM it rendered, so
 * The Collector's Home row can sit on the same lines: the same left inset, the
 * same portrait capsule size and gap, the same vertical rhythm and the same title
 * typography.
 *
 * Read-only: it measures Steam's elements (bounding boxes and computed styles) and
 * never writes to them. Steam's class names are hashed per build and its carousel
 * sizes tiles in JavaScript, so copying classes would carry neither the size nor a
 * stable name; the rendered boxes are what stays true across builds and themes.
 * Anything it cannot find falls back to {@link FALLBACK_GEOMETRY}.
 */

export interface RowGeometry {
  /** Left edge of the row's first tile, from the row's own left edge. */
  inset: number;
  capsuleWidth: number;
  capsuleHeight: number;
  gap: number;
  /** Space above the title (or above the capsules when the row has no title). */
  paddingTop: number;
  /** Space between the title's bottom and the capsules' top. */
  titleGap: number;
  /** Space under the capsules, down to the row's bottom edge. */
  paddingBottom: number;
  title: TitleTypography | null;
  /** Whether the numbers came from Steam's row rather than the fallback. */
  measured: boolean;
}

export interface TitleTypography {
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  lineHeight: string;
  letterSpacing: string;
  textTransform: string;
}

/** Used only when Steam's row cannot be measured: a 2:3 capsule of Steam's usual Home size. */
export const FALLBACK_GEOMETRY: RowGeometry = {
  inset: 24,
  capsuleWidth: 160,
  capsuleHeight: 240,
  gap: 12,
  paddingTop: 12,
  titleGap: 12,
  paddingBottom: 24,
  title: null,
  measured: false,
};

const MIN_CAPSULE_HEIGHT = 60;
const PORTRAIT_MIN = 1.2;
const PORTRAIT_MAX = 1.8;

interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function box(el: Element): Box {
  const r = el.getBoundingClientRect();
  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)]!;
}

function isPortrait(b: Box): boolean {
  if (b.width <= 0 || b.height < MIN_CAPSULE_HEIGHT) return false;
  const ratio = b.height / b.width;
  return ratio >= PORTRAIT_MIN && ratio <= PORTRAIT_MAX;
}

/**
 * The row's title: the first leaf element with short visible text that comes
 * before the row's first image in document order and is laid out above `above`
 * (the capsules' top). A game name printed under a capsule comes after its image.
 */
function findTitle(root: Element, above: number): Element | null {
  const walker = root.ownerDocument.createTreeWalker(root, 1 /* NodeFilter.SHOW_ELEMENT */);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node as Element;
    if (el.tagName === "IMG") return null;
    if (el.childElementCount > 0 || el.tagName === "STYLE") continue;
    const text = el.textContent.trim();
    if (text === "" || text.length > 60) continue;
    const b = box(el);
    if (b.height > 0 && b.bottom <= above) return el;
  }
  return null;
}

function typography(el: Element): TitleTypography | null {
  const view = el.ownerDocument.defaultView;
  if (!view) return null;
  const s = view.getComputedStyle(el);
  const size = Number.parseFloat(s.fontSize);
  if (!Number.isFinite(size) || size < 12 || size > 64) return null;
  return {
    fontFamily: s.fontFamily,
    fontSize: s.fontSize,
    fontWeight: s.fontWeight,
    lineHeight: s.lineHeight,
    letterSpacing: s.letterSpacing,
    textTransform: s.textTransform,
  };
}

/**
 * Measure Steam's Recent games row. `row` is the row's root element (the shelf's
 * previous sibling); `later` are rows after the shelf, searched for title
 * typography when the Recent games row has no title of its own. Returns `null`
 * when the row holds no portrait capsule to measure.
 */
export function measureRecentsRow(row: Element, later: Element[] = []): RowGeometry | null {
  const rowBox = box(row);
  const images = [...row.querySelectorAll("img")].map(box).filter((b) => b.width > 0 && b.height > 0);
  const capsules = images.filter(isPortrait).sort((a, b) => a.left - b.left);
  if (capsules.length === 0) return null;

  const capsuleWidth = Math.round(median(capsules.map((c) => c.width)));
  const capsuleHeight = Math.round(median(capsules.map((c) => c.height)));
  const gaps = capsules
    .slice(1)
    .map((c, i) => c.left - capsules[i]!.right)
    .filter((g) => g >= 0 && g < capsuleWidth);
  const gap = gaps.length > 0 ? Math.round(Math.min(...gaps)) : FALLBACK_GEOMETRY.gap;

  // Full-bleed art (Core's Art Hero Home spreads the focused game's art across the
  // row) starts at the row's edge and says nothing about where the content starts.
  const visible = images.filter((b) => b.left >= rowBox.left - 0.5 && b.width < rowBox.width * 0.6);
  const firstLeft = Math.min(...(visible.length > 0 ? visible : capsules).map((b) => b.left));
  const inset = Math.max(0, Math.round(firstLeft - rowBox.left));

  const tilesTop = Math.min(...capsules.map((c) => c.top));
  const tilesBottom = Math.max(...capsules.map((c) => c.bottom));
  const ownTitle = findTitle(row, tilesTop);
  const titleBox = ownTitle ? box(ownTitle) : null;
  const paddingTop = Math.max(0, Math.round((titleBox ? titleBox.top : tilesTop) - rowBox.top));
  const titleGap = titleBox ? Math.max(0, Math.round(tilesTop - titleBox.bottom)) : FALLBACK_GEOMETRY.titleGap;
  const paddingBottom = Math.max(0, Math.round(rowBox.bottom - tilesBottom));

  let title = ownTitle ? typography(ownTitle) : null;
  for (const next of later) {
    if (title) break;
    const found = findTitle(next, Number.POSITIVE_INFINITY);
    title = found ? typography(found) : null;
  }

  return { inset, capsuleWidth, capsuleHeight, gap, paddingTop, titleGap, paddingBottom, title, measured: true };
}
