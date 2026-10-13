"use client";

import { useEffect, useState } from "react";
import { AnswerMarkdown } from "../answer-markdown";
import { LoadingBlock, SkeletonCard } from "../ui";
import { btn } from "../ui";
import { automationDate } from "./automation-history";
import { api, automationError, automationPath, downloadRunPdf, runErrorText, runStatusLabel, type AutomationRun } from "./automations-api";

type ReportView = { automation: { id: string; name: string; folders: string[] }; run: AutomationRun };
function safeSourceUrl(value: string | null): string | undefined { try { const url = new URL(value ?? ""); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } }

/** Read-only view of one run, reached from the e-mail link by recipients who cannot manage the automation. */
export function AutomationReportView({ organizationId, automationId, runId }: { organizationId: string; automationId: string; runId: string }) {
  const [data, setData] = useState<ReportView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<ReportView>(`${automationPath(organizationId, automationId)}/runs/${encodeURIComponent(runId)}/view`, { signal: controller.signal, cache: "no-store" })
      .then((value) => { if (!controller.signal.aborted) setData(value); })
      .catch(() => { if (!controller.signal.aborted) setError("Este relatório não está disponível para você. Ele exige que você seja destinatário e tenha acesso às pastas da automação."); });
    return () => controller.abort();
  }, [organizationId, automationId, runId]);
  async function download() { setDownloading(true); try { await downloadRunPdf(organizationId, automationId, runId); } catch (caught) { setError(automationError(caught)); } finally { setDownloading(false); } }
  if (error && !data) return <p role="alert" className="mt-6 rounded-lg border border-rose-200 p-4 text-sm text-rose-700">{error}</p>;
  if (!data) return <LoadingBlock label="Carregando relatório…" className="mt-6"><SkeletonCard lines={4} /></LoadingBlock>;
  const { automation, run } = data;
  return <section aria-labelledby="automation-report-title" data-variant="slide" className="mo-enter mt-6 min-w-0 rounded-lg border border-line bg-panel p-4 sm:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="automation-report-title" className="break-words text-xl font-semibold">{automation.name}</h2>{run.pdf_available && <button disabled={downloading} className={btn("primary", "sm")} aria-busy={downloading} onClick={() => void download()}>{downloading ? "Baixando…" : "Baixar PDF"}</button>}</div>
    <p className="mt-2 text-sm text-muted-foreground">{automationDate(run.started_at)} · <span role="status">{runStatusLabel(run.status)}</span> · {run.documents_considered} documentos considerados</p>
    {automation.folders.length > 0 && <p className="mt-1 break-words text-sm text-muted-foreground">{automation.folders.length === 1 ? "Pasta" : "Pastas"}: {automation.folders.join(" · ")}</p>}
    {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
    {(run.status === "quota" || run.status === "error") && <p className="mt-3 rounded-lg border border-rose-200 p-3 text-sm text-rose-700">{runErrorText(run)}</p>}
    {run.status === "empty" && <p className="mt-3 text-sm">Nenhum alerta a reportar nesta execução.</p>}
    {run.result?.answer && <div className="mt-4 min-w-0 overflow-x-auto break-words"><AnswerMarkdown text={run.result.answer} fileNames={run.result.citations.map((citation) => citation.document_name)} /></div>}
    {!!run.result?.citations.length && <details className="mt-4"><summary className="min-h-11 cursor-pointer py-3 font-semibold">Fontes e citações ({run.result.citations.length})</summary><ol className="space-y-3">{run.result.citations.map((citation, index) => <li key={`${citation.document_id}-${index}`} className="break-words rounded-lg bg-paper p-3 text-sm"><p className="font-semibold">{index + 1}. {citation.document_name}{citation.page_number != null ? ` · Página ${citation.page_number}` : ""}</p><blockquote className="mt-2">{citation.excerpt}</blockquote>{safeSourceUrl(citation.source_url) && <a className="mt-2 inline-flex min-h-11 items-center text-primary underline" href={safeSourceUrl(citation.source_url)} target="_blank" rel="noreferrer">Abrir fonte: {citation.document_name}</a>}</li>)}</ol></details>}
  </section>;
}
