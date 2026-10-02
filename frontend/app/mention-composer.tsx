"use client";

import { FileText, FolderOpen, X } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type ChangeEvent, type KeyboardEvent, type RefObject } from "react";
import { providerKey, toolLabel } from "./question-scope";
import "./mention-composer.css";

export type MentionCandidate = { node_id: string; kind: "file" | "folder"; name: string; source_id: string; source_provider: string; path: string; query_status: string };
type Trigger = { start: number; end: number; query: string; kind: "file" | "folder" | null; command: boolean };

const MOBILE_QUERY = "(max-width: 767px)";
function useIsMobile() {
  return useSyncExternalStore(
    (notify) => { const media = window.matchMedia(MOBILE_QUERY); media.addEventListener("change", notify); return () => media.removeEventListener("change", notify); },
    () => window.matchMedia(MOBILE_QUERY).matches,
    () => false,
  );
}

export function MentionComposer({ organizationId, value, onChange, mentions, onMentionsChange, all, providers, disabled, textareaRef, onSubmit }: {
  organizationId: string; value: string; onChange: (value: string) => void; mentions: MentionCandidate[];
  onMentionsChange: (items: MentionCandidate[]) => void; all: boolean; providers: string[];
  disabled: boolean; textareaRef: RefObject<HTMLTextAreaElement | null>; onSubmit: () => void;
}) {
  const isMobile = useIsMobile();
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [items, setItems] = useState<MentionCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const generation = useRef(0);
  const composing = useRef(false);
  const dismissedTriggerStart = useRef<number | null>(null);
  useEffect(() => {
    if (!trigger || trigger.command || !trigger.query.trim()) { generation.current += 1; return; }
    const current = ++generation.current;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true); setError(null);
      try {
        const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/library/mention-candidates?organization_id=${organizationId}&q=${encodeURIComponent(trigger.query.trim())}&limit=20`, { credentials: "include", signal: controller.signal });
        if (!response.ok) throw new Error("Não foi possível buscar arquivos e pastas.");
        const result = await response.json() as { items: MentionCandidate[] };
        if (current === generation.current) { setItems(result.items.filter((item) => (all || providers.includes(providerKey(item.source_provider))) && (!trigger.kind || item.kind === trigger.kind))); setActive(0); }
      } catch (caught) { if (!controller.signal.aborted && current === generation.current) setError(caught instanceof Error ? caught.message : "Falha ao buscar menções."); }
      finally { if (current === generation.current) setLoading(false); }
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [all, organizationId, providers, trigger]);
  function update(event: ChangeEvent<HTMLTextAreaElement>) {
    const next = event.target.value; onChange(next);
    if (composing.current) return;
    setItems([]); setActive(0); setLoading(false); setError(null);
    const before = next.slice(0, event.target.selectionStart);
    const match = /(^|\s)([@/])([^@/\n]*)$/u.exec(before);
    if (!match) { dismissedTriggerStart.current = null; setTrigger(null); return; }
    const start = before.length - match[0].length + match[1].length;
    if (dismissedTriggerStart.current === start) { setTrigger(null); return; }
    setTrigger({ start, end: event.target.selectionStart, query: match[3], kind: trigger?.start === start && !trigger.command ? trigger.kind : null, command: match[2] === "/" });
  }
  function selectCommand(kind: "file" | "folder") {
    if (!trigger) return;
    onChange(`${value.slice(0, trigger.start)}@${value.slice(trigger.end)}`);
    setTrigger({ ...trigger, end: trigger.start + 1, command: false, kind, query: "" });
    setActive(0); setItems([]);
  }
  function choose(item: MentionCandidate) {
    if (!mentions.some((existing) => existing.node_id === item.node_id)) onMentionsChange([...mentions, item]);
    if (trigger) {
      const before = value.slice(0, trigger.start);
      onChange(`${before}${value.slice(trigger.end).replace(/^\s*/, " ")}`.trimStart());
      const caret = before.trimStart().length;
      requestAnimationFrame(() => { textareaRef.current?.focus(); textareaRef.current?.setSelectionRange(caret, caret); });
    }
    setTrigger(null); setItems([]);
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing) return;
    if (trigger) {
      const length = trigger.command ? 2 : items.length;
      if (event.key === "ArrowDown" && length) { event.preventDefault(); setActive((value) => (value + 1) % length); return; }
      if (event.key === "ArrowUp" && length) { event.preventDefault(); setActive((value) => (value - 1 + length) % length); return; }
      if (event.key === "Escape") { event.preventDefault(); dismissedTriggerStart.current = trigger.start; setTrigger(null); return; }
      if (event.key === "Enter" && length) { event.preventDefault(); if (trigger.command) selectCommand(active === 0 ? "file" : "folder"); else choose(items[active]); return; }
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); onSubmit(); }
  }
  const options = trigger?.command ? [{ kind: "file" as const, name: "Arquivo" }, { kind: "folder" as const, name: "Pasta" }] : [];
  return <div className="mention-composer">
    {mentions.length > 0 && <div className="mention-chips" aria-label="Arquivos e pastas mencionados">{mentions.map((item) => <span className="mention-chip" key={item.node_id}>{item.kind === "file" ? <FileText size={14} /> : <FolderOpen size={14} />}<span title={item.path}>{item.name}</span><button type="button" disabled={disabled} aria-label={`Remover ${item.name}`} onClick={() => onMentionsChange(mentions.filter((value) => value.node_id !== item.node_id))}><X size={14} /></button></span>)}</div>}
    <textarea ref={textareaRef} aria-label="Sua pergunta" aria-autocomplete="list" aria-controls={trigger ? "mention-options" : undefined} onCompositionStart={() => { composing.current = true; setTrigger(null); }} onCompositionEnd={(event) => { composing.current = false; update(event as unknown as ChangeEvent<HTMLTextAreaElement>); }} onKeyDown={keyDown} value={value} onChange={update} disabled={disabled} maxLength={1000} rows={2} placeholder={isMobile ? "Pergunte sobre seus documentos…" : "O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta"} className="w-full resize-none border-0 bg-transparent px-2 py-1 text-base outline-none placeholder:text-muted-foreground sm:text-sm" />
    {trigger && <div id="mention-options" className="mention-options" role="listbox" aria-label={trigger.command ? "Comandos de contexto" : "Arquivos e pastas"}>
      {trigger.command ? options.map((option, index) => <button type="button" role="option" aria-selected={active === index} disabled={disabled} key={option.kind} onClick={(event) => { const input = event.currentTarget.closest(".mention-composer")?.querySelector("textarea"); selectCommand(option.kind); requestAnimationFrame(() => { input?.focus(); input?.setSelectionRange(trigger.start + 1, trigger.start + 1); }); }}>{option.kind === "file" ? <FileText size={16} /> : <FolderOpen size={16} />}{option.name}</button>) : <>
        {!trigger.query.trim() && <p>Digite o nome de um arquivo ou pasta para pesquisar.</p>}
        {loading && <p role="status">Buscando…</p>}{error && <p role="alert">{error}</p>}
        {!loading && !error && trigger.query.trim() && items.length === 0 && <p>Nenhum item indexado nesta seleção.</p>}
        {items.map((item, index) => <button type="button" role="option" aria-selected={active === index} disabled={disabled} key={item.node_id} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(item)}>{item.kind === "file" ? <FileText size={16} /> : <FolderOpen size={16} />}<span><strong>{item.name}</strong><small>{toolLabel(item.source_provider)} · {item.path}</small></span></button>)}
      </>}
    </div>}
  </div>;
}
