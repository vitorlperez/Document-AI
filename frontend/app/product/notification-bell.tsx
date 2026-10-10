"use client";

import { Bell, CalendarClock, ExternalLink } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { type Company, api, messageFor } from "./types-and-api";

type Citation = { document_name: string; source_url: string | null };
type NotificationItem = { id: string; kind: string; title: string; body: string; created_at: string; read: boolean; data: { citations?: Citation[]; sections?: { name: string; summary: string; citations: Citation[] }[] } };
type NotificationList = { unread: number; items: NotificationItem[] };
type Digest = { sections: { workspace_folder_id: string; name: string; summary: string; citations: Citation[] }[] };

const POLL_MS = 60_000;
const safeHref = (url: string | null) => url && /^https?:\/\//i.test(url) ? url : null;

function Sources({ citations }: { citations?: Citation[] }) {
  if (!citations?.length) return null;
  return <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">{citations.slice(0, 4).map((item, index) => { const href = safeHref(item.source_url); return <li key={`${item.document_name}-${index}`}>{href ? <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline">{item.document_name}<ExternalLink size={11} aria-hidden="true" /></a> : item.document_name}</li>; })}</ul>;
}

export function NotificationBell({ company }: { company: Company }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<NotificationList>({ unread: 0, items: [] });
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const base = `/organizations/${company.id}`;
  const load = useCallback(async (signal?: AbortSignal) => {
    try { setData(await api<NotificationList>(`${base}/notifications`, { signal, cache: "no-store" })); } catch { /* the bell is secondary UI: stay quiet when polling fails */ }
  }, [base]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => { if (!controller.signal.aborted) void load(controller.signal); });
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(controller.signal); }, POLL_MS);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load]);
  useEffect(() => {
    if (!open) return;
    api<{ email_enabled: boolean }>(`${base}/notification-preferences`, { cache: "no-store" }).then((value) => setEmailEnabled(value.email_enabled)).catch(() => undefined);
    const close = (event: MouseEvent | KeyboardEvent) => { if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open, base]);
  async function markAllRead() {
    try { await api(`${base}/notifications/read`, { method: "POST", body: JSON.stringify({ ids: null }) }); setData((current) => ({ unread: 0, items: current.items.map((item) => ({ ...item, read: true })) })); } catch (caught) { setError(messageFor(caught)); }
  }
  async function toggleEmail() {
    const next = !emailEnabled; setEmailEnabled(next);
    try { await api(`${base}/notification-preferences`, { method: "PUT", body: JSON.stringify({ email_enabled: next }) }); } catch (caught) { setEmailEnabled(!next); setError(messageFor(caught)); }
  }
  async function loadDigest() {
    setBusy(true); setError(null);
    try { setDigest(await api<Digest>(`${base}/digest/weekly`, { method: "POST" })); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); }
  }
  return <div ref={root} className="relative">
    <button type="button" onClick={() => setOpen((value) => !value)} aria-haspopup="dialog" aria-expanded={open} aria-label={data.unread ? `Notificações, ${data.unread} não lidas` : "Notificações"} title="Notificações" className="relative rounded-lg p-2 text-muted-foreground hover:bg-sage"><Bell size={18} aria-hidden="true" />{data.unread > 0 && <span className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] font-semibold leading-4 text-primary-foreground">{data.unread > 9 ? "9+" : data.unread}</span>}</button>
    {open && <div role="dialog" aria-label="Notificações" className="absolute right-0 top-full z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-line bg-panel p-3 shadow-xl">
      <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">Notificações</h2><button type="button" onClick={() => void markAllRead()} disabled={!data.unread} className="min-h-8 text-xs font-semibold text-primary underline disabled:opacity-50">Marcar todas como lidas</button></div>
      {error && <p role="alert" className="mt-2 text-xs text-rose-700">{error}</p>}
      <ul className="mt-2 max-h-80 space-y-2 overflow-y-auto">
        {data.items.length === 0 && <li className="py-4 text-center text-sm text-muted-foreground">Nenhuma notificação por enquanto. Siga uma pergunta salva para ser avisado quando a resposta mudar.</li>}
        {data.items.map((item) => <li key={item.id} className={`rounded-lg p-2.5 text-sm ${item.read ? "" : "bg-sage"}`}><p className="font-semibold">{item.title}</p>{item.kind === "weekly_digest" ? item.data.sections?.map((section) => <div key={section.name} className="mt-1"><p className="text-xs font-semibold">{section.name}</p><p className="line-clamp-3 text-xs text-muted-foreground">{section.summary}</p><Sources citations={section.citations} /></div>) : <><p className="mt-0.5 line-clamp-4 text-xs text-muted-foreground">{item.body}</p><Sources citations={item.data.citations} /></>}<time dateTime={item.created_at} className="mt-1 block text-[11px] text-muted-foreground">{new Date(item.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</time></li>)}
      </ul>
      <div className="mt-3 border-t border-line-soft pt-3">
        <button type="button" onClick={() => void loadDigest()} disabled={busy} className="inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold text-primary underline disabled:opacity-50"><CalendarClock size={14} aria-hidden="true" />{busy ? "Gerando resumo…" : "Resumo da semana agora"}</button>
        {digest && (digest.sections.length === 0 ? <p className="mt-2 text-xs text-muted-foreground">Nada mudou nos seus documentos esta semana.</p> : <ul className="mt-2 space-y-2">{digest.sections.map((section) => <li key={section.workspace_folder_id} className="text-xs"><p className="font-semibold">{section.name}</p><p className="text-muted-foreground">{section.summary}</p><Sources citations={section.citations} /></li>)}</ul>)}
        <label className="mt-3 flex min-h-9 items-center gap-2 text-xs"><input type="checkbox" checked={emailEnabled} onChange={() => void toggleEmail()} />Receber também por e-mail</label>
      </div>
    </div>}
  </div>;
}
