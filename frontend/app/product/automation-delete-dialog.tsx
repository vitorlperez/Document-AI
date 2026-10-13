"use client";

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { Trash2 } from "lucide-react";
import { useDialogBackdropClose } from "../modal-dismiss";
import { btn, closeDialogAnimated } from "../ui";

/** Confirmação destrutiva no padrão dos modais do app (<dialog> nativo, foco preso, saída animada, ESC/backdrop bloqueados em andamento). */
export function AutomationDeleteDialog({ name, busy, error, isOpen = true, returnFocus, onConfirm, onCancel }: { name: string; busy: boolean; error: string | null; isOpen?: boolean; returnFocus?: HTMLElement; onConfirm: () => void; onCancel: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const titleId = useId(); const descId = useId();
  const closing = useRef(false);
  const onClosed = useRef(onCancel);
  useEffect(() => { onClosed.current = onCancel; }, [onCancel]);
  useEffect(() => {
    const element = dialog.current;
    const trigger = returnFocus ?? document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (element && !element.open) element.showModal();
    cancelButton.current?.focus({ preventScroll: true });
    return () => { document.body.style.overflow = overflow; requestAnimationFrame(() => { if (trigger?.isConnected) trigger.focus({ preventScroll: true }); }); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  function requestClose() {
    if (busy || closing.current) return;
    closing.current = true;
    closeDialogAnimated(dialog.current, () => onClosed.current());
  }
  useDialogBackdropClose(dialog, requestClose, busy);
  useEffect(() => { if (!isOpen) closeDialogAnimated(dialog.current, () => onClosed.current()); }, [isOpen]);
  function trapFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? []);
    if (!items.length) { event.preventDefault(); return; }
    const current = items.indexOf(document.activeElement as HTMLElement);
    const next = event.shiftKey ? (current <= 0 ? items.length - 1 : current - 1) : (current + 1) % items.length;
    event.preventDefault(); items[next].focus();
  }
  return <dialog ref={dialog} role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descId} aria-busy={busy} className="automation-modal automation-modal-confirm" data-arquivio-motion-root="" onKeyDown={trapFocus} onCancel={(event) => { event.preventDefault(); requestClose(); }}>
    <section data-arquivio-motion="panel" className="automation-modal-panel">
      <div className="flex items-start gap-3"><span aria-hidden="true" className="grid size-10 shrink-0 place-items-center rounded-full bg-[var(--btn-danger-soft-bg)] text-[var(--btn-danger-soft-fg)]"><Trash2 size={20} /></span>
        <div className="min-w-0"><h2 id={titleId} className="text-xl font-semibold">Excluir automação?</h2>
          <p id={descId} className="mt-2 text-sm">Você vai excluir <strong className="break-words">{name}</strong>. Essa ação não pode ser desfeita: o histórico de execuções e os PDFs gerados deixam de ficar acessíveis, e a automação deixa de rodar.</p></div></div>
      {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 p-3 text-sm text-rose-700">{error}</p>}
      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <button ref={cancelButton} type="button" disabled={busy} className={btn("ghost")} onClick={requestClose}>Cancelar</button>
        <button type="button" disabled={busy} aria-busy={busy} className={btn("destructive")} onClick={onConfirm}>{busy ? "Excluindo…" : "Excluir"}</button>
      </div>
    </section>
  </dialog>;
}
