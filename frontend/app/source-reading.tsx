"use client";

import { Library } from "lucide-react";
import { useEffect, useState } from "react";
import { REDUCED_MOTION_QUERY } from "./interface-motion";
import { providerKey, toolLabel } from "./question-scope";
import { ProviderMark } from "./product/types-and-api";
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
