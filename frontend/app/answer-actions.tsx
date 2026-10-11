"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ClipboardCopy, Download, ListPlus } from "lucide-react";
import { answerWithSources } from "./answer-blocks";
import { API_BASE } from "./product/types-and-api";
import { ClickUpTaskModal } from "./clickup-task-modal";

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

  const button = "inline-flex min-h-9 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-muted-foreground hover:bg-sage hover:text-ink disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary";
  return <div className="relative mt-3 flex flex-wrap items-center gap-1" role="group" aria-label="Ações da resposta">
    <button type="button" className={button} onClick={() => { void copy(); }}>{copied ? <Check size={14} aria-hidden="true" /> : <ClipboardCopy size={14} aria-hidden="true" />}{copied ? "Copiado" : "Copiar com fontes"}</button>
    <div className="relative">
      <button type="button" className={button} disabled={busy} aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((open) => !open)}><Download size={14} aria-hidden="true" />{busy ? "Exportando…" : "Exportar"}</button>
      {menu && <div role="menu" className="absolute left-0 top-full z-10 mt-1 min-w-40 rounded-md border border-line bg-white p-1 shadow-md">
        {FORMATS.map((format) => <button key={format.value} type="button" role="menuitem" className="block w-full rounded px-3 py-2 text-left text-xs text-ink hover:bg-sage" onClick={() => { void download(format.value); }}>{format.label}</button>)}
      </div>}
    </div>
    {clickUpEnabled && <button type="button" className={button} aria-haspopup="dialog" onClick={() => setTaskOpen(true)}><ListPlus size={14} aria-hidden="true" />Criar tarefa no ClickUp</button>}
    {taskOpen && <ClickUpTaskModal base={`/organizations/${organizationId}/conversations/${conversationId}/messages/${messageId}/clickup-task`} onClose={() => setTaskOpen(false)} />}
    {error && <p role="alert" className="w-full text-xs text-rose-700">{error}</p>}
  </div>;
}
