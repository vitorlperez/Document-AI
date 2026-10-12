"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ClipboardCopy, Download, ListPlus } from "lucide-react";
import { answerWithSources } from "./answer-blocks";
import { API_BASE } from "./product/types-and-api";
import { ClickUpTaskModal } from "./clickup-task-modal";
import { Spinner, Transition } from "./ui";

type Source = { document_name: string; source_url: string | null };
type ExportFormat = "md" | "docx" | "pdf";
const FORMATS: { value: ExportFormat; label: string }[] = [{ value: "md", label: "Markdown (.md)" }, { value: "docx", label: "Word (.docx)" }, { value: "pdf", label: "PDF (.pdf)" }];

/** "Copiar com fontes", "Exportar" and (only with ClickUp connected) "Criar tarefa no ClickUp" for one persisted answer; export is rendered by the backend from the stored message. */
export function AnswerActions({ organizationId, conversationId, messageId, text, sources, clickUpEnabled = false }: { organizationId: string; conversationId: string; messageId: string; text: string; sources: Source[]; clickUpEnabled?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return;
    menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [menu]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    setError(null);
    try {
      await navigator.clipboard.writeText(answerWithSources(text, sources));
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch { setError("Não foi possível copiar."); }
  }

  async function download(format: ExportFormat) {
    setMenu(false); setBusy(true); setError(null);
    try {
      const response = await fetch(`${API_BASE}/organizations/${organizationId}/conversations/${conversationId}/messages/${messageId}/export?format=${format}`, { credentials: "include" });
      if (!response.ok) throw new Error();
      const name = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? `resposta.${format}`;
      const url = URL.createObjectURL(await response.blob());
      const link = Object.assign(document.createElement("a"), { href: url, download: name });
      link.click();
      URL.revokeObjectURL(url);
    } catch { setError("Não foi possível exportar esta resposta."); }
    finally { setBusy(false); }
  }

  const button = "mo-interactive inline-flex min-h-11 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted-foreground hover:bg-sage hover:text-ink disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";
  return <div ref={root} className="relative mt-3 flex flex-wrap items-center gap-1" role="group" aria-label="Ações da resposta">
    <button type="button" className={button} onClick={() => { void copy(); }}>{copied ? <Check size={14} className="mo-check-pop" aria-hidden="true" /> : <ClipboardCopy size={14} aria-hidden="true" />}{copied ? "Copiado" : "Copiar com fontes"}</button>
    <span role="status" className="sr-only">{copied ? "Resposta copiada com as fontes." : busy ? "Exportando resposta…" : ""}</span>
    <div className="relative">
      <button ref={trigger} type="button" className={button} disabled={busy} aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((open) => !open)}>{busy ? <Spinner size={14} /> : <Download size={14} aria-hidden="true" />}{busy ? "Exportando…" : "Exportar"}</button>
      <Transition show={menu} variant="slide" className="answer-export-menu absolute left-0 top-full z-10 mt-1 min-w-40 rounded-md border border-[var(--card-edge)] bg-[var(--surface-raised)] p-1 shadow-xl">
        <div ref={menuRef} role="menu" aria-label="Formato de exportação" inert={!menu} onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); setMenu(false); trigger.current?.focus(); }
          else if (event.key === "Tab") setMenu(false);
          else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
            const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
            buttons[next]?.focus();
          }
        }}>
        {FORMATS.map((format) => <button key={format.value} type="button" role="menuitem" className="flex min-h-11 w-full items-center rounded px-3 text-left text-xs font-medium text-ink hover:bg-sage focus-visible:bg-sage focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary" onClick={() => { trigger.current?.focus(); void download(format.value); }}>{format.label}</button>)}
        </div>
      </Transition>
    </div>
    {clickUpEnabled && <button type="button" className={button} aria-haspopup="dialog" onClick={() => setTaskOpen(true)}><ListPlus size={14} aria-hidden="true" />Criar tarefa no ClickUp</button>}
    {taskOpen && <ClickUpTaskModal base={`/organizations/${organizationId}/conversations/${conversationId}/messages/${messageId}/clickup-task`} onClose={() => setTaskOpen(false)} />}
    {error && <p role="alert" className="w-full text-xs text-[var(--danger-ink)]">{error}</p>}
  </div>;
}
