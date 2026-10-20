import { TOUR_REPLAY_KEY, activePrimaryTab } from "./account-helpers";
import { companyPath } from "./types-and-api";

/** Window events that let the shell menus (avatar, "Mais" sheet) reach screens that live elsewhere in the tree. */
export const OPEN_PALETTE_EVENT = "arquivio:open-palette";
export const OPEN_SHORTCUTS_EVENT = "arquivio:open-shortcuts";
export const REPLAY_TOUR_EVENT = "arquivio:replay-tour";

export const openPalette = () => window.dispatchEvent(new Event(OPEN_PALETTE_EVENT));
export const openShortcuts = () => window.dispatchEvent(new Event(OPEN_SHORTCUTS_EVENT));

/** Consumes the "replay the tour" flag left by a menu click (the chat may mount after the navigation). */
export function consumeTourReplay(): boolean {
  try {
    if (window.sessionStorage.getItem(TOUR_REPLAY_KEY) !== "1") return false;
    window.sessionStorage.removeItem(TOUR_REPLAY_KEY);
    return true;
  } catch { return false; }
}

/** "Conhecer o app": the tour lives in the chat, so leave a flag, navigate there if needed and wake the chat if it is already open. */
export function requestTourReplay(pathname: string | null, companyId: string, onNavigate: (path: string) => void) {
  try { window.sessionStorage.setItem(TOUR_REPLAY_KEY, "1"); } catch { /* storage unavailable */ }
  if (activePrimaryTab(pathname ?? "") === "chat") window.dispatchEvent(new Event(REPLAY_TOUR_EVENT));
  else onNavigate(companyPath(companyId));
}

/** Platform-aware label for the modifier key (display only). */
export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
