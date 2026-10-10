"use client";

import { Gauge } from "lucide-react";
import { useEffect, useState } from "react";
import { type Company, api, messageFor } from "./types-and-api";

type UsageRow = { metric: string; used: number; limit: number; ratio: number; level: "ok" | "warning" | "exceeded" };
type Usage = { period_start: string; metrics: UsageRow[]; active_documents: UsageRow };

const labels: Record<string, string> = {
  questions: "Perguntas no mês", processed_bytes: "Arquivos processados", embedding_tokens: "Tokens de indexação", ocr_pages: "Páginas de OCR", active_documents: "Documentos ativos",
};
export const formatUsage = (metric: string, value: number) => metric === "processed_bytes" ? `${(value / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB` : value.toLocaleString("pt-BR");
const barTone = { ok: "bg-emerald-500", warning: "bg-amber-500", exceeded: "bg-rose-600" } as const;
const levelText = { ok: "", warning: "Atenção: mais de 80% do limite usado.", exceeded: "Limite atingido: novas operações deste tipo serão recusadas." } as const;

export function UsagePanel({ company }: { company: Company }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<Usage>(`/organizations/${company.id}/usage`, { signal: controller.signal, cache: "no-store" }).then(setUsage).catch((caught) => { if (!controller.signal.aborted) setError(messageFor(caught)); });
    return () => controller.abort();
  }, [company.id]);
  const rows = usage ? [...usage.metrics, usage.active_documents] : [];
  return <section className="rounded-lg border border-line-soft bg-panel p-4 sm:p-6" aria-labelledby="usage-title">
    <div className="flex items-center gap-3"><Gauge size={22} className="text-primary" aria-hidden="true" /><h2 id="usage-title" className="text-xl font-semibold">Uso e cotas</h2></div>
    <p className="mt-2 text-sm text-muted-foreground">Consumo do mês corrente da organização. Avisamos a partir de 80% e bloqueamos novas operações em 100%.</p>
    {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
    {!usage && !error && <p role="status" className="mt-4 text-sm">Carregando uso…</p>}
    <ul className="mt-4 space-y-4">{rows.map((row) => <li key={row.metric}>
      <div className="flex items-baseline justify-between gap-3 text-sm"><span className="font-semibold">{labels[row.metric] ?? row.metric}</span><span className="text-muted-foreground">{formatUsage(row.metric, row.used)} de {formatUsage(row.metric, row.limit)} ({Math.min(100, Math.round(row.ratio * 100))}%)</span></div>
      <div role="progressbar" aria-label={labels[row.metric] ?? row.metric} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.round(row.ratio * 100))} className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-sage"><div className={`h-full ${barTone[row.level]}`} style={{ width: `${Math.min(100, row.ratio * 100)}%` }} /></div>
      {row.level !== "ok" && <p role={row.level === "exceeded" ? "alert" : undefined} className={`mt-1 text-xs ${row.level === "exceeded" ? "text-rose-700" : "text-amber-700"}`}>{levelText[row.level]}</p>}
    </li>)}</ul>
  </section>;
}
