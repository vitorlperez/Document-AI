import { exitDelayMs, MOTION_MS } from "./motion-logic";

/**
 * Fecha um <dialog> nativo com animação de saída. O `open` some na hora no close() nativo, então
 * marcamos data-closing (CSS anima o painel/backdrop), esperamos e só então chamamos close().
 * Para Esc: no handler `onCancel`, faça event.preventDefault() e chame esta função.
 */
export function closeDialogAnimated(dialog: HTMLDialogElement | null, onClosed?: () => void): void {
  if (!dialog || !dialog.open) { onClosed?.(); return; }
  if (dialog.hasAttribute("data-closing")) return;
  const reduced = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const finish = () => { dialog.removeAttribute("data-closing"); if (dialog.open) dialog.close(); onClosed?.(); };
  const wait = exitDelayMs(reduced, MOTION_MS.base);
  if (wait === 0) { finish(); return; }
  dialog.setAttribute("data-closing", "");
  window.setTimeout(finish, wait);
}
