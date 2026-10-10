"use client";

import { ExternalLink, Library, X } from "lucide-react";
import { useEffect, useState } from "react";
import { REDUCED_MOTION_QUERY } from "./interface-motion";
import { providerKey, toolLabel } from "./question-scope";
import { ProviderMark, api, messageFor } from "./product/types-and-api";
import "./source-reading.css";

/** How long each tool stays "being read" before the next one lights up. */
const READING_STEP_MS = 760;

/** One entry per tool actually selected for the question; a generic Biblioteca entry when none is known. */
export function readingSources(providers: readonly string[] | undefined): { key: string; label: string; provider?: string }[] {
  const keys = [...new Set((providers ?? []).map(providerKey))];
  return keys.length > 0 ? keys.map((key) => ({ key, label: toolLabel(key), provider: key })) : [{ key: "library", label: "Biblioteca" }];
}

/**
 * Same idea as the landing demo: the selected tools' logos, lit one after another while the answer is prepared,
 * then settled as "sources consulted" once it arrives. The row keeps its place, so the hand-off to the text is continuous.
 */
export function SourceReadingStatus({ providers, reading }: { providers?: readonly string[]; reading: boolean }) {
  const sources = readingSources(providers);
  const [step, setStep] = useState(0);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const sync = () => setReduced(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  const cycling = reading && !reduced && sources.length > 1;
  useEffect(() => {
    if (!cycling) return;
    const timer = window.setInterval(() => setStep((value) => value + 1), READING_STEP_MS);
    return () => window.clearInterval(timer);
  }, [cycling]);
  const active = reading && !reduced ? step % sources.length : -1;
  const current = sources[Math.max(active, 0)];
  const label = reading ? (reduced ? "Consultando suas fontes…" : sources.length === 1 && !current.provider ? "Lendo documentos da Biblioteca…" : `Lendo ${current.label}…`) : sources.length === 1 ? `Fonte consultada: ${current.label}` : "Fontes consultadas";
  return <div className={`source-reading${reading ? " is-reading" : ""}`} data-motion={reduced ? "reduced" : undefined}>
    <span role="status" className="sr-only">{reading ? "Consultando suas fontes…" : "Fontes consultadas"}</span>
    <span className="source-reading-logos" aria-hidden="true">{sources.map((source, index) => <span key={source.key} className={`source-reading-logo${index === active ? " is-active" : ""}`} title={source.label}>{source.provider ? <ProviderMark provider={source.provider} size="sm" /> : <Library size={16} />}</span>)}</span>
    <span key={label} className="source-reading-label" aria-hidden="true">{label}</span>
  </div>;
}

export type EvidenceCitation = { document_id: string; document_name: string; excerpt: string; page_number: number | null; source_url: string | null; chunk_id?: string };
type EvidencePassage = { text: string; page_number: number | null; source_url: string | null };

/** Splits the passage around the cited excerpt (ignoring a trailing ellipsis) so the evidence can be highlighted. */
export function splitHighlight(text: string, excerpt: string): [string, string, string] | null {
  const needle = excerpt.replace(/…$/, "").trim();
  if (needle.length < 8) return null;
  const at = text.toLowerCase().indexOf(needle.toLowerCase());
  return at < 0 ? null : [text.slice(0, at), text.slice(at, at + needle.length), text.slice(at + needle.length)];
}

/** Side panel opened by a [N] citation: the cited passage highlighted, its page and a link to the original. Fetched only on click. */
export function SourceEvidencePanel({ organizationId, number, citation, onClose }: { organizationId: string; number: number; citation: EvidenceCitation; onClose: () => void }) {
  const [passage, setPassage] = useState<EvidencePassage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!citation.chunk_id) return;
    let cancelled = false;
    void api<EvidencePassage>(`/organizations/${organizationId}/documents/${citation.document_id}/evidence?chunk_id=${citation.chunk_id}`)
      .then((result) => { if (!cancelled) setPassage(result); })
      .catch((caught) => { if (!cancelled) setError(messageFor(caught)); });
    return () => { cancelled = true; };
  }, [organizationId, citation.document_id, citation.chunk_id]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const text = passage?.text ?? citation.excerpt;
  const parts = splitHighlight(text, citation.excerpt);
  const page = passage?.page_number ?? citation.page_number;
  const url = passage?.source_url ?? citation.source_url;
  const loading = Boolean(citation.chunk_id) && !passage && !error;
  return <aside role="complementary" aria-label={`Verificar fonte ${number}`} className="source-evidence fixed inset-y-0 right-0 z-40 flex w-[26rem] max-w-full flex-col border-l border-line bg-panel shadow-xl">
    <div className="flex items-start justify-between gap-2 border-b border-line-soft px-4 py-3">
      <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fonte {number}</p><h2 className="break-words text-sm font-semibold text-ink">{citation.document_name}</h2>{page != null && <p className="text-xs text-muted-foreground">Página {page}</p>}</div>
      <button type="button" autoFocus onClick={onClose} aria-label="Fechar painel de fonte" className="grid min-h-11 min-w-11 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-sage"><X size={16} aria-hidden="true" /></button>
    </div>
    <div className="flex-1 overflow-y-auto px-4 py-4 text-sm leading-6 text-ink">
      {loading ? <p role="status" className="text-xs text-muted-foreground">Carregando trecho…</p> : <p className="whitespace-pre-wrap break-words">{parts ? <>{parts[0]}<mark className="rounded bg-sage-selected px-0.5 text-ink">{parts[1]}</mark>{parts[2]}</> : text}</p>}
      {error && <p role="alert" className="mt-3 text-xs text-muted-foreground">Não foi possível carregar o trecho completo; mostrando o resumo da citação.</p>}
    </div>
    {url && <div className="border-t border-line-soft px-4 py-3"><a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-xs font-semibold text-primary hover:underline"><ExternalLink size={14} aria-hidden="true" />Abrir original</a></div>}
  </aside>;
}
