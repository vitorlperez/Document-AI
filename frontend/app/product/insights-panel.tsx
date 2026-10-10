"use client";

import Link from "next/link";
import { Lightbulb, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { type Company, api, companyPath, documentFailureLabel, messageFor } from "./types-and-api";

type FolderHealth = { workspace_id: string; name: string; provider: string; status: string; indexed: number; failed: number; skipped: number; error_codes: Record<string, number>; actions: { kind: string; workspace_id: string }[] };
type Suggestion = { kind: "connect_folder" | "reprocess"; workspace_id?: string; name?: string; reason: string; count?: number };
type Insights = {
  days: number; folders: FolderHealth[]; suggestions: Suggestion[];
  answers: { total_answers: number; gap_answers: number; gap_ratio: number; feedback: { up: number; down: number }; retrieval_status: Record<string, number>; assessment: Record<string, number>; by_provider: { provider: string; answers: number; gap_answers: number }[] };
};

const statusLabel: Record<string, string> = { sufficient_evidence: "Com evidência suficiente", no_indexed_content: "Sem conteúdo indexado", below_evidence_threshold: "Evidência insuficiente", no_compatible_embeddings: "Índice incompatível", invalid_generation_output: "Resposta inválida" };
const suggestionText = (item: Suggestion) => item.reason === "no_folders" ? "Conecte uma fonte e escolha pastas para começar a responder perguntas." : item.reason === "many_unanswered" ? "Muitas perguntas ficaram sem resposta fundamentada. Conecte as pastas que faltam ou confira os documentos com falha." : `Reprocesse “${item.name}”: ${item.count} documento(s) com falha.`;

export function InsightsPanel({ company, setNotice, setError }: { company: Company; setNotice?: (message: string | null) => void; setError?: (message: string | null) => void }) {
  const [data, setData] = useState<Insights | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<Insights>(`/organizations/${company.id}/insights`, { signal: controller.signal, cache: "no-store" }).then(setData).catch((caught) => { if (!controller.signal.aborted) setFailure(messageFor(caught)); });
    return () => controller.abort();
  }, [company.id]);
  async function reprocess(workspaceId: string, name: string) {
    setBusy(workspaceId);
    try { await api(`/library/workspaces/${workspaceId}/reprocess?organization_id=${company.id}`, { method: "POST" }); setNotice?.(`Reprocessamento de “${name}” iniciado. Acompanhe pela Biblioteca.`); }
    catch (caught) { const message = messageFor(caught); setFailure(message); setError?.(message); } finally { setBusy(null); }
  }
  const answers = data?.answers;
  return <section className="rounded-lg border border-line-soft bg-panel p-4 sm:p-6" aria-labelledby="insights-title">
    <div className="flex items-center gap-3"><Lightbulb size={22} className="text-primary" aria-hidden="true" /><h2 id="insights-title" className="text-xl font-semibold">Lacunas e qualidade</h2></div>
    <p className="mt-2 text-sm text-muted-foreground">Últimos {data?.days ?? 30} dias. Mostramos apenas contagens e metadados; o texto das conversas pessoais nunca aparece aqui.</p>
    {failure && <p role="alert" className="mt-4 text-sm text-rose-700">{failure}</p>}
    {!data && !failure && <p role="status" className="mt-4 text-sm">Carregando análise…</p>}
    {data && answers && <>
      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["Respostas", answers.total_answers], ["Sem fundamento", `${Math.round(answers.gap_ratio * 100)}%`], ["👍 Úteis", answers.feedback.up], ["👎 Não úteis", answers.feedback.down]].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-paper p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="text-xl font-semibold">{value}</dd></div>)}
      </dl>
      {Object.keys(answers.retrieval_status).length > 0 && <ul className="mt-4 flex flex-wrap gap-2 text-xs">{Object.entries(answers.retrieval_status).map(([key, count]) => <li key={key} className="rounded-full border border-line px-3 py-1">{statusLabel[key] ?? key}: {count}</li>)}</ul>}
      {data.suggestions.length > 0 && <div className="mt-6"><h3 className="font-semibold">Ações sugeridas</h3><ul className="mt-2 space-y-2">{data.suggestions.map((item, index) => <li key={`${item.kind}-${item.workspace_id ?? index}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-paper p-3 text-sm"><span>{suggestionText(item)}</span>{item.kind === "reprocess" && item.workspace_id ? <button type="button" disabled={busy === item.workspace_id} onClick={() => void reprocess(item.workspace_id!, item.name ?? "pasta")} className="inline-flex min-h-11 items-center gap-1 rounded-lg border border-line px-3 font-semibold disabled:opacity-50"><RefreshCw size={14} aria-hidden="true" />Reprocessar</button> : <Link href={companyPath(company.id, "/integrations")} className="inline-flex min-h-11 items-center font-semibold text-primary underline">Conectar pasta</Link>}</li>)}</ul></div>}
      <div className="mt-6"><h3 className="font-semibold">Saúde por pasta</h3>
        {data.folders.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">Nenhuma pasta conectada.</p> : <ul className="mt-2 divide-y divide-line-soft">{data.folders.map((folder) => <li key={folder.workspace_id} className="py-3 text-sm"><div className="flex flex-wrap justify-between gap-2"><span className="font-semibold">{folder.name}</span><span className="text-muted-foreground">{folder.indexed} indexados · {folder.failed} com falha · {folder.skipped} ignorados</span></div>
          {Object.entries(folder.error_codes).map(([code, count]) => <p key={code} className="mt-1 text-xs text-muted-foreground">{count}× {documentFailureLabel(code)}</p>)}</li>)}</ul>}
      </div>
    </>}
  </section>;
}
