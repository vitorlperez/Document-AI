/** Pure rules for the LP header that hides on scroll down and returns on scroll up. */
export const HEADER_SCROLL_DELTA = 8;
export const HEADER_TOP_ZONE = 24;

/**
 * @param {{ hidden: boolean; lastY: number }} state
 * @param {number} y current scrollY
 * @param {{ pinned?: boolean; headerHeight?: number }} [opts] pinned = menu open or focus inside the header
 * @returns {{ hidden: boolean; lastY: number }}
 */
export function nextHeaderState(state, y, { pinned = false, headerHeight = 72 } = {}) {
  const current = Math.max(0, y); // iOS rubber-band gives negative values
  if (pinned || current <= HEADER_TOP_ZONE) return { hidden: false, lastY: current };
  const delta = current - state.lastY;
  if (Math.abs(delta) < HEADER_SCROLL_DELTA) return state; // below threshold: keep lastY so slow drags still accumulate
  if (delta > 0) return { hidden: current > headerHeight ? true : state.hidden, lastY: current };
  return { hidden: false, lastY: current };
}
