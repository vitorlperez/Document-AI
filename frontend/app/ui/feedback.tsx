"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { joinClass } from "./motion-logic";
import { Transition } from "./transitions";

type StateProps = { icon?: ReactNode; title: string; description?: ReactNode; actions?: ReactNode; className?: string };

function StateBody({ icon, title, description, actions }: StateProps) {
  return <>{icon && <div className="mo-state-icon" aria-hidden="true">{icon}</div>}<p className="mo-state-title">{title}</p>{description && <p className="mo-state-description">{description}</p>}{actions && <div className="mo-state-actions">{actions}</div>}</>;
}

/** Estado vazio: ícone (pop) + título + descrição + ação. Entrada sutil de 280 ms. */
export function EmptyState(props: StateProps) {
  return <div role="status" data-tone="neutral" className={joinClass("mo-state", props.className)}><StateBody {...props} /></div>;
}

/** Estado de erro: role=alert, tokens de perigo do tema. `actions` costuma ter o "Tentar novamente". */
export function ErrorState(props: StateProps) {
  return <div role="alert" data-tone="error" className={joinClass("mo-state", props.className)}><StateBody {...props} /></div>;
}

/** Coluna fixa dos toasts (empilha vários). Coloque uma por app, perto da raiz da casca. */
export function ToastViewport({ children, label = "Notificações" }: { children?: ReactNode; label?: string }) {
  return <div className="mo-toast-viewport" role="region" aria-label={label}>{children}</div>;
}

/**
 * Toast apresentacional com saída animada. A lane Shell controla `open` e o texto.
 * `duration` em ms (null = não fecha sozinho; erros devem usar null). Pausa ao passar o mouse.
 */
export function Toast({ open, tone = "info", title, description, action, duration = 6000, onDismiss, dismissLabel = "Fechar" }: { open: boolean; tone?: "info" | "success" | "error"; title: string; description?: ReactNode; action?: ReactNode; duration?: number | null; onDismiss?: () => void; dismissLabel?: string }) {
  const dismiss = useRef(onDismiss);
  useEffect(() => { dismiss.current = onDismiss; });
  const hovering = useRef(false);
  useEffect(() => {
    if (!open || duration === null) return;
    let timer = window.setTimeout(tick, duration);
    function tick() { if (hovering.current) { timer = window.setTimeout(tick, 1000); return; } dismiss.current?.(); }
    return () => window.clearTimeout(timer);
  }, [open, duration]);
  return (
    <Transition show={open} variant="slide" exitMs={120}>
      <div role={tone === "error" ? "alert" : "status"} data-tone={tone} className="mo-toast" onMouseEnter={() => { hovering.current = true; }} onMouseLeave={() => { hovering.current = false; }}>
        <div className="mo-toast-body"><p className="mo-toast-title">{title}</p>{description && <p className="mo-toast-description">{description}</p>}{action}</div>
        {onDismiss && <button type="button" onClick={onDismiss} aria-label={dismissLabel} className="mo-interactive mo-focus rounded-md px-2 text-lg leading-none">×</button>}
      </div>
    </Transition>
  );
}
