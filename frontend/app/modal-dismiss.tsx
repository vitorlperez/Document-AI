"use client";

import { useEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode, type RefObject } from "react";

/**
 * Shared dismiss behaviour for every modal in the app: click outside (overlay/backdrop) and ESC close it,
 * unless `busy` (an action is in flight inside the modal) — then it stays open so no state is lost.
 */

/** Native <dialog> opened with showModal(): closes on a click that lands on the backdrop (outside the dialog box). */
export function useDialogBackdropClose(ref: RefObject<HTMLDialogElement | null>, onClose: () => void, busy = false) {
  const press = useRef(false);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const outside = (event: globalThis.MouseEvent) => {
      const box = dialog.getBoundingClientRect();
      return event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom;
    };
    // Require press AND release outside, so selecting text and releasing over the backdrop does not dismiss.
    const down = (event: globalThis.MouseEvent) => { press.current = event.target === dialog && outside(event); };
    const up = (event: globalThis.MouseEvent) => { const started = press.current; press.current = false; if (started && event.target === dialog && outside(event) && !busy) onClose(); };
    // ESC fires "cancel" on a native dialog: block it while an action is in flight, like the backdrop click.
    const cancel = (event: Event) => { if (busy) event.preventDefault(); };
    dialog.addEventListener("mousedown", down);
    dialog.addEventListener("mouseup", up);
    dialog.addEventListener("cancel", cancel);
    return () => { dialog.removeEventListener("mousedown", down); dialog.removeEventListener("mouseup", up); dialog.removeEventListener("cancel", cancel); };
  }, [ref, onClose, busy]);
}

/** Custom overlay modal: backdrop click + ESC close, focus moves in on open and returns to the trigger on close. */
export function ModalOverlay({ onClose, busy = false, labelledBy, className, children }: { onClose: () => void; busy?: boolean; labelledBy: string; className?: string; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const press = useRef(false);
  const closeRef = useRef(onClose); const busyRef = useRef(busy);
  useEffect(() => { closeRef.current = onClose; busyRef.current = busy; });
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const focusable = () => Array.from(root.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
    (focusable()[0] ?? root.current)?.focus({ preventScroll: true });
    return () => { if (trigger?.isConnected) trigger.focus({ preventScroll: true }); };
  }, []);
  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.stopPropagation(); if (!busy) onClose(); return; }
    if (event.key !== "Tab") return;
    const items = Array.from(root.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  return <div ref={root} role="dialog" aria-modal="true" aria-labelledby={labelledBy} aria-busy={busy || undefined} tabIndex={-1} className={className} onKeyDown={keyDown}
    onMouseDown={(event: MouseEvent<HTMLDivElement>) => { press.current = event.target === event.currentTarget; }}
    onMouseUp={(event: MouseEvent<HTMLDivElement>) => { const started = press.current; press.current = false; if (started && event.target === event.currentTarget && !busyRef.current) closeRef.current(); }}>
    {children}
  </div>;
}
