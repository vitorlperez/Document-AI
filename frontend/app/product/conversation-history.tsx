"use client";

import { Check, MessageSquare, Pencil, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, messageFor } from "./types-and-api";

export type ConversationSummary = { id: string; title: string; last_message_at: string; created_at: string };
type ConversationPage = { items: ConversationSummary[]; page: number; page_size: number; total: number };

/** The current user's past conversations: resume, rename and delete. `refreshKey` reloads the list after a new answer. */
export function ConversationHistory({ organizationId, activeId, refreshKey, disabled, onOpen, onDeleted, onClose }: { organizationId: string; activeId: string | null; refreshKey: string | null; disabled: boolean; onOpen: (id: string) => void; onDeleted: (id: string) => void; onClose: () => void }) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);
  const base = `/organizations/${organizationId}/conversations`;
  const load = useCallback(async (page: number) => {
    try {
      const result = await api<ConversationPage>(`${base}?page=${page}&page_size=30`);
      setItems((current) => page === 1 ? result.items : [...current, ...result.items.filter((item) => !current.some((known) => known.id === item.id))]);
      setTotal(result.total); setError(null);
    } catch (caught) { setError(messageFor(caught)); }
    finally { setLoading(false); }
  }, [base]);
  useEffect(() => { void Promise.resolve().then(() => load(1)); }, [load, refreshKey]);
  // Move focus into the panel when it opens (keyboard + screen reader users, and the full-screen mobile sheet).
  useEffect(() => { closeRef.current?.focus({ preventScroll: true }); }, []);
  async function rename(id: string) {
    const title = draft.trim();
    if (!title) { setEditing(null); return; }
    try {
      const updated = await api<ConversationSummary>(`${base}/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
      setItems((current) => current.map((item) => item.id === id ? updated : item));
      setEditing(null);
    } catch (caught) { setError(messageFor(caught)); }
  }
  async function remove(item: ConversationSummary) {
    if (!window.confirm(`Apagar a conversa "${item.title}"?`)) return;
    try {
      await api(`${base}/${item.id}`, { method: "DELETE" });
      setItems((current) => current.filter((known) => known.id !== item.id));
      setTotal((count) => Math.max(count - 1, 0));
      onDeleted(item.id);
    } catch (caught) { setError(messageFor(caught)); }
  }
  return <aside aria-label="Histórico de conversas" onKeyDown={(event) => { if (event.key === "Escape" && editing === null) onClose(); }} className="conversation-history absolute inset-y-0 left-0 z-20 flex w-72 max-w-[85%] flex-col border-r border-line bg-panel shadow-lg">
    <div className="flex items-center justify-between border-b border-line-soft px-3 py-2"><h2 className="text-sm font-semibold text-ink">Conversas</h2><button ref={closeRef} type="button" onClick={onClose} aria-label="Fechar histórico" className="grid min-h-11 min-w-11 place-items-center rounded-md text-muted-foreground hover:bg-sage"><X size={16} aria-hidden="true" /></button></div>
    <div className="flex-1 overflow-y-auto p-2">
      {loading ? <p role="status" className="p-3 text-xs text-muted-foreground">Carregando…</p> : items.length === 0 && !error ? <p className="p-3 text-xs text-muted-foreground">Suas conversas aparecerão aqui.</p> : <ul className="space-y-0.5">{items.map((item) => <li key={item.id} className={`group flex items-center gap-1 rounded-md ${item.id === activeId ? "bg-sage-selected" : "hover:bg-sage"}`}>
        {editing === item.id ? <form className="flex min-w-0 flex-1 items-center gap-1 p-1" onSubmit={(event) => { event.preventDefault(); void rename(item.id); }}>
          <input autoFocus value={draft} maxLength={160} aria-label="Novo nome da conversa" onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setEditing(null); }} className="min-h-9 min-w-0 flex-1 rounded border border-line bg-panel px-2 text-xs" />
          <button type="submit" aria-label="Salvar nome" className="grid min-h-9 min-w-9 place-items-center rounded text-primary hover:bg-sage"><Check size={14} aria-hidden="true" /></button>
        </form> : <>
          <button type="button" disabled={disabled} onClick={() => onOpen(item.id)} aria-current={item.id === activeId ? "true" : undefined} className="flex min-h-11 min-w-0 flex-1 items-center gap-2 px-2 text-left text-xs text-ink disabled:opacity-50"><MessageSquare size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" /><span className="truncate">{item.title}</span></button>
          <button type="button" onClick={() => { setEditing(item.id); setDraft(item.title); }} aria-label={`Renomear ${item.title}`} className="grid min-h-9 min-w-9 place-items-center rounded text-muted-foreground hover:bg-sage"><Pencil size={13} aria-hidden="true" /></button>
          <button type="button" disabled={disabled} onClick={() => { void remove(item); }} aria-label={`Apagar ${item.title}`} className="grid min-h-9 min-w-9 place-items-center rounded text-muted-foreground hover:bg-sage disabled:opacity-40"><Trash2 size={13} aria-hidden="true" /></button>
        </>}
      </li>)}</ul>}
      {items.length < total && <button type="button" onClick={() => { void load(Math.floor(items.length / 30) + 1); }} className="mt-2 w-full rounded-md py-2 text-xs font-semibold text-primary hover:bg-sage">Ver mais</button>}
      {error && <p role="alert" className="p-3 text-xs text-rose-700">{error}</p>}
    </div>
  </aside>;
}
