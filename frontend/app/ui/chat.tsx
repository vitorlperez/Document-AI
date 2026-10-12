import type { ReactNode } from "react";
import { joinClass } from "./motion-logic";

/** Três pontos de "pensando". Altura fixa (sem layout shift); `label` fica como texto acessível. */
export function TypingIndicator({ label = "Pensando…", className }: { label?: string; className?: string }) {
  return <span role="status" aria-live="polite" className={joinClass("mo-typing", className)}><i aria-hidden="true" /><i aria-hidden="true" /><i aria-hidden="true" /><span className="sr-only">{label}</span></span>;
}

/**
 * Texto em streaming com cursor. state="streaming": cursor sólido; "idle": pisca; "done": sem cursor.
 * `children` é o texto/markdown já renderizado; a lane do chat decide como obtê-lo (hoje: answer-reveal).
 */
export function StreamingText({ children, state = "streaming", className }: { children: ReactNode; state?: "streaming" | "idle" | "done"; className?: string }) {
  return <span className={className} aria-busy={state === "streaming"}>{children}{state !== "done" && <span aria-hidden="true" className="mo-caret" data-state={state} />}</span>;
}
