"use client";

import { AlertTriangle, Check, ChevronDown, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./question-scope.css";
import { providerKey, toolLabel } from "./tool-groups";

export type QuestionContext = {
  id: string; name: string; status: string; source_id: string; source_provider: string;
  query_status: "ready" | "no_indexed_content" | "no_compatible_embeddings" | "not_ready";
  sync_in_progress?: boolean; source_status?: string;
  /** Espaços do chamador que concedem esta pasta (T-C3). */
  spaces?: { id: string; name: string }[];
};
export { providerKey, toolLabel };
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
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  const available = [...new Set(contexts.filter((item) => item.query_status === "ready" || item.query_status === "no_compatible_embeddings").map((item) => providerKey(item.source_provider)))].sort((a, b) => toolLabel(a).localeCompare(toolLabel(b), "pt-BR"));
  const selected = contexts.filter((item) => all || providers.includes(providerKey(item.source_provider)));
  const ready = selected.filter(contextReady).length;
  const readyTools = new Set(selected.filter(contextReady).map((item) => providerKey(item.source_provider))).size;
  const pending = selected.filter((item) => !contextReady(item) && !contextSyncing(item)).length;
  const summary = all ? "Todas as ferramentas" : providers.length ? providers.map(toolLabel).join(", ") : "Escolha uma ferramenta";
  const shortValue = all ? "Todas" : providers.length ? providers.map(toolLabel).join(", ") : "Escolha";
  const countText = `${readyTools} ${readyTools === 1 ? "ferramenta disponível" : "ferramentas disponíveis"}`;
  const warning = !loading && !error && (ready === 0 || pending > 0) && !syncInProgress ? (ready === 0 ? "Ainda não há conteúdo pronto nesta seleção." : `${pending} ${pending === 1 ? "pasta indisponível" : "pastas indisponíveis"} nesta seleção.`) : null;
  return <div ref={root} className="question-scope">
    <button ref={trigger} type="button" className="question-scope-trigger" data-active={!all && providers.length > 0 ? "true" : undefined} aria-label={`Ferramentas: ${summary}`} title={`${summary} · ${countText}`} aria-expanded={open} aria-controls="question-scope-menu" disabled={disabled || loading || Boolean(error)} onClick={() => setOpen((value) => !value)}>
      <Wrench size={13} aria-hidden="true" />
      {loading ? <span className="question-scope-summary">Carregando…</span> : <><span className="question-scope-kind" aria-hidden="true">Ferramentas</span><span className="question-scope-summary question-scope-value">{shortValue}</span></>}
      <ChevronDown size={12} aria-hidden="true" className="question-scope-chevron" />
    </button>
    {open && <div id="question-scope-menu" className="question-scope-menu" role="group" aria-label="Selecionar ferramentas">
      <button type="button" className="question-scope-option" aria-pressed={all} onClick={() => onChange(true, [])}><span className="question-scope-check">{all && <Check size={15} />}</span>Todas as ferramentas</button>
      {available.map((item) => <button type="button" key={item} className="question-scope-option" aria-pressed={!all && providers.includes(item)} onClick={() => onChange(false, all ? [item] : providers.includes(item) ? providers.filter((value) => value !== item) : [...providers, item])}><span className="question-scope-check">{!all && providers.includes(item) && <Check size={15} />}</span>{toolLabel(item)}</button>)}
      {available.length === 0 && <p className="question-scope-empty">Nenhuma ferramenta com conteúdo indexado.</p>}
      <p className="question-scope-count" aria-live="polite">{countText}</p>
    </div>}
    {error && <span role="alert" className="question-scope-flag" tabIndex={0} data-tip={error} aria-label={error}><AlertTriangle size={13} aria-hidden="true" /><button type="button" className="question-scope-retry" onClick={onRetry}>Tentar de novo</button></span>}
    {warning && <span role="status" className="question-scope-flag" tabIndex={0} data-tip={warning} aria-label={warning}><AlertTriangle size={13} aria-hidden="true" /></span>}
  </div>;
}
