"use client";

import { useCallback, useEffect, useState } from "react";
import { AnswerMarkdown } from "../answer-markdown";
import { automationButton } from "./automation-editor";
import { api, automationError, automationPath, downloadRunPdf, runErrorText, runStatusLabel, type Automation, type AutomationRun } from "./automations-api";

export const automationDate = (value: string | null) => value ? new Date(value).toLocaleString("pt-BR") : "Ainda não executada";
function safeSourceUrl(value: string | null): string | undefined { try { const url = new URL(value ?? ""); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } }

export function AutomationHistory({ organizationId, automation, revision, targetRunId = null, onClose, onSettled }: { organizationId: string; automation: Automation; revision: number; targetRunId?: string | null; onClose: () => void; onSettled: () => void }) {
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const path = `${automationPath(organizationId, automation.id)}/runs?limit=20`;
  const load = useCallback(async (signal: AbortSignal) => {
    try { const data = await api<{ items: AutomationRun[] }>(path, { signal, cache: "no-store" });
      if (targetRunId && !data.items.some((run) => run.id === targetRunId)) {
        const selected = await api<AutomationRun>(`${automationPath(organizationId, automation.id)}/runs/${encodeURIComponent(targetRunId)}`, { signal, cache: "no-store" });
        data.items.unshift(selected);
      }
      if (!signal.aborted) { setRuns(data.items); setError(null); } }
    catch (caught) { if (!signal.aborted) setError(automationError(caught)); }
    finally { if (!signal.aborted) setLoading(false); }
  }, [path, targetRunId, organizationId, automation.id]);
  useEffect(() => { const controller = new AbortController(); void Promise.resolve().then(() => { if (!controller.signal.aborted) void load(controller.signal); }); return () => controller.abort(); }, [load, revision, refresh]);
  useEffect(() => {
    if (!loading && targetRunId) document.getElementById(`automation-run-${targetRunId}`)?.scrollIntoView({ block: "start" });
  }, [loading, targetRunId, runs]);
  const pending = runs.some((run) => run.status === "queued" || run.status === "running");
  useEffect(() => {
    if (!pending) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const data = await api<{ items: AutomationRun[] }>(path, { signal: controller.signal, cache: "no-store" });
        if (controller.signal.aborted) return;
        setRuns(data.items); setError(null);
        if (data.items.some((run) => run.status === "queued" || run.status === "running")) timer = setTimeout(() => void tick(), 3000);
        else onSettled();
      } catch (caught) { if (!controller.signal.aborted) setError(automationError(caught)); }
    }
    timer = setTimeout(() => void tick(), 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [pending, path, onSettled, refresh, revision]);
  async function download(run: AutomationRun) { setDownloading(run.id); setError(null); try { await downloadRunPdf(organizationId, automation.id, run.id); } catch (caught) { setError(automationError(caught)); } finally { setDownloading(null); } }
  return <section aria-labelledby="automation-history-title" className="mt-6 min-w-0 rounded-lg border border-line bg-panel p-4 sm:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="automation-history-title" className="break-words text-xl font-semibold">Histórico: {automation.name}</h2><div className="flex gap-2"><button className={automationButton} onClick={() => setRefresh((value) => value + 1)}>Atualizar histórico</button><button className={automationButton} onClick={onClose}>Fechar histórico</button></div></div>
    <p className="mt-2 text-sm text-muted-foreground">Últimas 20 execuções. Cada execução usa uma pergunta da cota mensal.</p>
    {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
    {loading ? <p role="status" className="mt-4">Carregando execuções…</p> : !runs.length ? <p className="mt-4">Nenhuma execução registrada. Use “Executar agora” para gerar o primeiro resultado.</p> : <div className="mt-4 space-y-4">{runs.map((run) => <article key={run.id} id={`automation-run-${run.id}`} className="min-w-0 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">{automationDate(run.started_at)} · <span role="status">{runStatusLabel(run.status)}</span></h3>{run.pdf_available && <button disabled={downloading !== null} className={automationButton} onClick={() => void download(run)}>{downloading === run.id ? "Baixando…" : "Baixar PDF"}</button>}</div>
      <p className="mt-2 text-sm text-muted-foreground">{run.documents_considered} documentos considerados · {run.questions_used} pergunta(s) utilizada(s)</p>
      {(run.status === "quota" || run.status === "error") && <p className="mt-3 rounded-lg border border-rose-200 p-3 text-sm text-rose-700">{runErrorText(run)}</p>}
      {(run.status === "queued" || run.status === "running") && <p className="mt-3 text-sm">{run.status === "queued" ? "A execução está na fila. O resultado aparecerá aqui quando ficar pronto." : "Consultando os arquivos e preparando o resultado…"}</p>}
      {run.status === "empty" && <p className="mt-3 text-sm">Nenhum alerta a reportar nesta execução. Nenhuma notificação foi enviada.</p>}
      {run.result?.answer && <div className="mt-4 min-w-0 overflow-x-auto break-words"><AnswerMarkdown text={run.result.answer} fileNames={run.result.citations.map((citation) => citation.document_name)} /></div>}
      {!!run.result?.citations.length && <details className="mt-4"><summary className="min-h-11 cursor-pointer py-3 font-semibold">Fontes e citações ({run.result.citations.length})</summary><ol className="space-y-3">{run.result.citations.map((citation, index) => <li key={`${citation.document_id}-${index}`} className="break-words rounded-lg bg-paper p-3 text-sm"><p className="font-semibold">{index + 1}. {citation.document_name}{citation.page_number != null ? ` · Página ${citation.page_number}` : ""}</p><blockquote className="mt-2">{citation.excerpt}</blockquote>{safeSourceUrl(citation.source_url) && <a className="mt-2 inline-flex min-h-11 items-center text-primary underline" href={safeSourceUrl(citation.source_url)} target="_blank" rel="noreferrer">Abrir fonte: {citation.document_name}</a>}</li>)}</ol></details>}
      {!!run.result?.skipped_recipients.length && <p className="mt-3 text-sm text-amber-800">{run.result.skipped_recipients.length} destinatário(s) não recebeu(ram) o resultado por falta de acesso às pastas.</p>}
    </article>)}</div>}
  </section>;
}
