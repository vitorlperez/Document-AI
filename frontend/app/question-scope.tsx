"use client";

import { RefreshCw } from "lucide-react";
import "./question-scope.css";

export type QuestionScope = "folder" | "provider" | "organization";
export type QuestionContext = {
  id: string; name: string; status: string; source_id: string; source_provider: string;
  query_status: "ready" | "no_indexed_content" | "no_compatible_embeddings" | "not_ready";
};

export const providerKey = (provider: string) => provider === "google_drive" ? "google" : provider;

export const toolLabel = (provider?: string | null) => ({
  google: "Google Drive", google_drive: "Google Drive", onedrive: "OneDrive",
  github: "GitHub", github_markdown: "GitHub Markdown", notion: "Notion", slack: "Slack", teams: "Microsoft Teams",
})[provider ?? ""] ?? (provider ? provider.replaceAll("_", " ") : "Fonte indexada");

export const contextReady = (context: QuestionContext) => context.query_status === "ready" && (context.status === "ready" || context.status === "partial_failure");

export function QuestionScopePicker({ scope, provider, contextId, contexts, loading, disabled, error, onRetry, onChange }: {
  scope: QuestionScope; provider: string; contextId: string; contexts: QuestionContext[];
  loading: boolean; disabled: boolean; error: string | null; onRetry: () => void;
  onChange: (scope: QuestionScope, value: string) => void;
}) {
  const providers = [...new Set(contexts.map((item) => providerKey(item.source_provider)).filter(Boolean))].sort((a, b) => toolLabel(a).localeCompare(toolLabel(b), "pt-BR"));
  const selected = contexts.filter((item) => scope === "organization" || (scope === "provider" ? providerKey(item.source_provider) === provider : item.id === contextId));
  const ready = selected.filter(contextReady).length;
  const pending = selected.length - ready;
  const partial = selected.some((item) => item.status === "partial_failure");
  const value = scope === "organization" ? "organization" : scope === "provider" ? `provider:${provider}` : `folder:${contextId}`;
  return <section className="question-scope" aria-label="Contexto da pergunta">
    <div className="question-scope-row">
      <label htmlFor="question-scope">Consultar em</label>
      <select id="question-scope" value={value} disabled={disabled || loading || Boolean(error)} aria-describedby="question-scope-note" onChange={(event) => {
        const selectedValue = event.target.value;
        if (selectedValue === "organization") onChange("organization", "");
        else if (selectedValue.startsWith("provider:")) onChange("provider", selectedValue.slice(9));
        else onChange("folder", selectedValue.slice(7));
      }}>
        <option value="organization">Todas as ferramentas · conteúdo indexado</option>
        <optgroup label="Uma ferramenta inteira">{scope === "provider" && !providers.includes(provider) && <option value={`provider:${provider}`}>Ferramenta indisponível — selecione outro contexto</option>}{providers.map((item) => <option value={`provider:${item}`} key={item}>{toolLabel(item)} · todas as pastas indexadas</option>)}</optgroup>
        <optgroup label="Uma pasta específica">
          {scope === "folder" && !contexts.some((item) => item.id === contextId) && <option value={`folder:${contextId}`}>Pasta indisponível — selecione outro contexto</option>}
          {contexts.map((item) => <option key={item.id} value={`folder:${item.id}`} disabled={!contextReady(item)}>{toolLabel(item.source_provider)} / {item.name}{!contextReady(item) ? " · aguardando indexação" : ""}</option>)}
        </optgroup>
      </select>
      {!loading && !error && <span className="question-scope-count">{ready} {ready === 1 ? "pasta disponível" : "pastas disponíveis"}</span>}
    </div>
    <p id="question-scope-note">{loading ? <span role="status" aria-live="polite" className="inline-flex items-center gap-2"><RefreshCw size={13} className="motion-safe:animate-spin" aria-hidden="true" />Carregando contextos autorizados…</span> : "Consulta apenas conteúdo já sincronizado e indexado nesta organização. Não busca arquivos novos nas ferramentas em tempo real."}</p>
    {error ? <div role="alert" className="question-scope-warning">{error} <button type="button" onClick={onRetry}>Tentar novamente</button></div> : !loading && <>
      {contexts.length === 0 ? <p className="question-scope-warning">Nenhuma pasta disponível. Conecte e sincronize uma fonte para começar.</p> : ready === 0 ? <p className="question-scope-warning">Este contexto ainda não tem conteúdo pronto para perguntas. Aguarde a indexação ou escolha outro contexto.</p> : null}
      {(pending > 0 || partial) && <p className="question-scope-warning">Cobertura parcial: {pending > 0 ? `${pending} ${pending === 1 ? "pasta ainda não está disponível" : "pastas ainda não estão disponíveis"}. ` : ""}{partial ? "Há pastas com falhas de sincronização. " : ""}A resposta considera somente as evidências disponíveis.</p>}
    </>}
  </section>;
}
