"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./question-scope.css";

export type QuestionContext = {
  id: string; name: string; status: string; source_id: string; source_provider: string;
  query_status: "ready" | "no_indexed_content" | "no_compatible_embeddings" | "not_ready";
  sync_in_progress?: boolean;
};
export const providerKey = (provider: string) => provider === "google_drive" ? "google" : provider;
export const toolLabel = (provider?: string | null) => ({
  google: "Google Drive", google_drive: "Google Drive", onedrive: "OneDrive",
  github: "GitHub", github_markdown: "GitHub Markdown", notion: "Notion", slack: "Slack", teams: "Microsoft Teams",
})[provider ?? ""] ?? (provider ? provider.replaceAll("_", " ") : "Fonte indexada");
export const contextSyncing = (context: QuestionContext) => Boolean(context.sync_in_progress) || context.status === "queued" || context.status === "syncing";
// Consultável assim que há conteúdo embedado, mesmo com a sincronização ainda em andamento (base parcial).
export const contextReady = (context: QuestionContext) => context.query_status === "ready" && (context.status === "ready" || context.status === "partial_failure" || contextSyncing(context));

export const PARTIAL_BASE_MESSAGE = "Base parcial: a sincronização ainda está em andamento e as respostas usam o que já está pronto.";
export const SYNC_PENDING_MESSAGE = "Sincronização em andamento — as respostas ficam disponíveis conforme a indexação termina.";

export function QuestionScopePicker({ syncInProgress = false, all, providers, contexts, loading, disabled, error, onRetry, onChange }: {
  syncInProgress?: boolean;
  all: boolean; providers: string[]; contexts: QuestionContext[];
  loading: boolean; disabled: boolean; error: string | null; onRetry: () => void;
  onChange: (all: boolean, providers: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  const available = [...new Set(contexts.filter((item) => item.query_status === "ready" || item.query_status === "no_compatible_embeddings").map((item) => providerKey(item.source_provider)))].sort((a, b) => toolLabel(a).localeCompare(toolLabel(b), "pt-BR"));
  const selected = contexts.filter((item) => all || providers.includes(providerKey(item.source_provider)));
  const ready = selected.filter(contextReady).length;
  const readyTools = new Set(selected.filter(contextReady).map((item) => providerKey(item.source_provider))).size;
  const pending = selected.filter((item) => !contextReady(item) && !contextSyncing(item)).length;
  const summary = all ? "Todas as ferramentas" : providers.length ? providers.map(toolLabel).join(", ") : "Escolha uma ferramenta";
  return <div ref={root} className="question-scope">
    <button type="button" className="question-scope-trigger" aria-label={`Ferramentas: ${summary}`} aria-expanded={open} aria-controls="question-scope-menu" disabled={disabled || loading || Boolean(error)} onClick={() => setOpen((value) => !value)}>
      <span className="question-scope-summary">{loading ? "Carregando ferramentas…" : summary}</span><ChevronDown size={15} aria-hidden="true" />
    </button>
    {open && <div id="question-scope-menu" className="question-scope-menu" role="group" aria-label="Selecionar ferramentas">
      <button type="button" className="question-scope-option" aria-pressed={all} onClick={() => onChange(true, [])}><span className="question-scope-check">{all && <Check size={15} />}</span>Todas as ferramentas</button>
      {available.map((item) => <button type="button" key={item} className="question-scope-option" aria-pressed={!all && providers.includes(item)} onClick={() => onChange(false, all ? [item] : providers.includes(item) ? providers.filter((value) => value !== item) : [...providers, item])}><span className="question-scope-check">{!all && providers.includes(item) && <Check size={15} />}</span>{toolLabel(item)}</button>)}
      {available.length === 0 && <p className="question-scope-empty">Nenhuma ferramenta com conteúdo indexado.</p>}
    </div>}
    <span className="question-scope-count" aria-live="polite">{readyTools} {readyTools === 1 ? "ferramenta disponível" : "ferramentas disponíveis"}</span>
    {error && <div role="alert" className="question-scope-warning">{error} <button type="button" onClick={onRetry}>Tentar novamente</button></div>}
    {!loading && !error && (ready === 0 || pending > 0) && !syncInProgress && <p className="question-scope-warning" role="status">{ready === 0 ? "Ainda não há conteúdo pronto nesta seleção." : `${pending} ${pending === 1 ? "pasta indisponível" : "pastas indisponíveis"} nesta seleção.`}</p>}
  </div>;
}
