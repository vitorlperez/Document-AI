/** Desktop chat history sidebar: remembered collapsed state (per membership) and its toggle shortcut (Ctrl/⌘ + \\). */
export const historyCollapsedKey = (membershipId: string) => `arquivio:chat-history-collapsed:${membershipId}`;
export const parseHistoryCollapsed = (stored: string | null) => stored === "1";
export const isHistoryToggleKey = (event: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "shiftKey" | "altKey">) =>
  (event.metaKey || event.ctrlKey) && !event.shiftKey && !event.altKey && event.key === "\\";
