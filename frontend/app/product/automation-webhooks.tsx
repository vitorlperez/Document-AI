"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Webhook } from "lucide-react";
import { EmptyState, LoadingBlock, SkeletonCard, SkeletonList, StaggerItem } from "../ui";
import { automationButton } from "./automation-editor";
import { automationDate } from "./automation-history";
import { validateWebhookUrl } from "./automation-delivery-model";
import { api, webhookPath, webhookError, webhookStatusLabel, webhookDeliveryError, type WebhookEndpoint, type WebhookDelivery } from "./automations-api";

export function AutomationWebhooks({ organizationId }: { organizationId: string }) {
  const base = webhookPath(organizationId);
  const [items, setItems] = useState<WebhookEndpoint[]>([]);
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [eventSelected, setEventSelected] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [historyId, setHistoryId] = useState<string | null>(null);
  const secretHeading = useRef<HTMLHeadingElement>(null);
  const urlInput = useRef<HTMLInputElement>(null);
  const lock = useRef(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    if (signal?.aborted) return;
    setLoading(true);
    try {
      const data = await api<{ items: WebhookEndpoint[]; limit: number }>(base, { signal, cache: "no-store" });
      if (!signal?.aborted) { setItems(data.items); setLimit(data.limit); setError(null); }
    } catch (caught) { if (!signal?.aborted) setError(webhookError(caught)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [base]);
  useEffect(() => { const controller = new AbortController(); void Promise.resolve().then(() => { if (!controller.signal.aborted) void load(controller.signal); }); return () => controller.abort(); }, [load]);
  useEffect(() => { if (secret) secretHeading.current?.focus(); }, [secret]);
  async function create() {
    if (lock.current || secret) return;
    const invalid = validateWebhookUrl(url);
    if (invalid || !eventSelected) { setError(invalid ?? "Escolha o evento que deseja receber."); return; }
    lock.current = true; setBusy("create"); setError(null); setNotice(null);
    try {
      const { secret: value, ...item } = await api<WebhookEndpoint & { secret: string }>(base, { method: "POST", body: JSON.stringify({ url: url.trim(), events: ["automation.completed"], enabled: true }) });
      setItems((current) => [item, ...current]); setSecret(value); setCopied(false); setUrl(""); setNotice("Webhook cadastrado.");
    } catch (caught) { setError(webhookError(caught)); }
    finally { lock.current = false; setBusy(null); }
  }
  async function change(item: WebhookEndpoint, revoke = false) {
    if (lock.current) return;
    lock.current = true; setBusy(item.id); setError(null); setNotice(null);
    try {
      if (revoke) {
        await api<void>(`${base}/${item.id}`, { method: "DELETE" });
        setItems((current) => current.map((existing) => existing.id === item.id ? { ...existing, enabled: false, revoked_at: new Date().toISOString() } : existing));
        setConfirmId(null); setNotice("Webhook revogado. As entregas pendentes foram canceladas.");
      } else {
        const updated = await api<WebhookEndpoint>(`${base}/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled }) });
        setItems((current) => current.map((existing) => existing.id === item.id ? updated : existing));
        setNotice(updated.enabled ? "Webhook ativado." : "Webhook desativado.");
      }
    } catch (caught) { setError(webhookError(caught)); }
    finally { lock.current = false; setBusy(null); }
  }
  async function copySecret() {
    if (!secret) return;
    try { await navigator.clipboard.writeText(secret); setCopied(true); }
    catch { setNotice("Não foi possível copiar automaticamente. Selecione o secret abaixo e copie manualmente."); }
  }
  const activeCount = items.filter((item) => !item.revoked_at).length;
  return <section aria-labelledby="webhooks-title" data-variant="slide" className="mo-enter mt-8 min-w-0 rounded-lg border border-line bg-panel p-4 sm:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="webhooks-title" className="text-xl font-semibold">Webhooks</h2><button className={automationButton} disabled={loading || busy !== null} onClick={() => void load()}>Atualizar webhooks</button></div>
    <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Envie os resultados das automações para n8n, Zapier ou seu sistema. O evento inclui a resposta e as fontes; use um destino autorizado pela organização.</p>
    {notice && <p role="status" className="mt-4 rounded-lg bg-sage p-3 text-sm">{notice}</p>}
    {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}
    {secret && <div className="mo-enter mt-4 rounded-lg border border-amber-200 p-4" data-variant="slide">
      <h3 ref={secretHeading} tabIndex={-1} className="font-semibold focus-visible:outline-2 focus-visible:outline-primary">Guarde seu secret agora</h3>
      <p id="webhook-secret-help" className="mt-2 text-sm">Ele só aparece nesta criação. Copie e guarde em um local seguro antes de fechar.</p>
      <label className="mt-3 block text-sm">Secret do webhook<textarea readOnly aria-describedby="webhook-secret-help" value={secret} className="mt-2 min-h-20 w-full break-all rounded-lg border border-line bg-panel p-3 font-mono focus-visible:outline-2 focus-visible:outline-primary" /></label>
      <div className="mt-3 flex flex-wrap gap-2"><button className={automationButton} onClick={() => void copySecret()}>{copied ? <span className="inline-flex items-center gap-2"><Check aria-hidden="true" size={14} className="mo-check-pop" />Copiado</span> : "Copiar secret"}</button><button className={automationButton} onClick={() => { setSecret(null); setCopied(false); urlInput.current?.focus(); }}>Já guardei, fechar secret</button></div>
      {copied && <p role="status" className="mt-2 text-sm">Secret copiado.</p>}
    </div>}
    <form className="mt-5 max-w-2xl space-y-3" onSubmit={(event) => { event.preventDefault(); void create(); }}>
      <label className="block text-sm font-semibold">URL de destino HTTPS<input ref={urlInput} type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://seu-sistema.com/webhook" aria-describedby="webhook-url-help" className="mt-2 min-h-11 w-full rounded-lg border border-line bg-panel px-3 py-2 focus-visible:outline-2 focus-visible:outline-primary" /></label>
      <p id="webhook-url-help" className="text-sm text-muted-foreground">Use um endereço público na porta 443, sem usuário ou senha.</p>
      <fieldset><legend className="text-sm font-semibold">Eventos</legend><label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={eventSelected} onChange={(event) => setEventSelected(event.target.checked)} /><span>Automação finalizada <span className="break-all text-muted-foreground">(automation.completed)</span></span></label><p className="text-sm text-muted-foreground">Inclui execuções concluídas, sem alertas, com cota atingida ou com erro.</p></fieldset>
      <button type="submit" disabled={loading || busy !== null || secret !== null || activeCount >= limit} className={`${automationButton} bg-primary text-primary-foreground`}>{busy === "create" ? "Cadastrando…" : "Cadastrar webhook"}</button>
      <p className="text-sm text-muted-foreground">{activeCount} de {limit} webhooks ativos. {activeCount >= limit ? "Revogue um webhook para cadastrar outro." : "Webhooks desativados também contam para o limite."}</p>
    </form>
    {loading ? <LoadingBlock label="Carregando webhooks…" className="mt-5"><div className="space-y-3"><SkeletonCard lines={2} /><SkeletonCard lines={2} /></div></LoadingBlock> : !items.length ? <EmptyState className="mt-5" icon={<Webhook size={28} />} title="Nenhum webhook cadastrado" description="Cadastre um endereço HTTPS acima para receber os resultados das automações." /> : <ul aria-label="Webhooks cadastrados" className="mt-5 space-y-3">{items.map((item, index) => <StaggerItem as="li" key={item.id} index={index} className="min-w-0 rounded-lg border border-line p-4">
      <h3 className="break-all font-semibold">{item.url}</h3><p className="mt-2 text-sm">{item.revoked_at ? "Revogado" : item.enabled ? "Ativo" : "Desativado"} · {item.events.join(", ")}</p>
      <p className="mt-2 text-sm text-muted-foreground">Última entrega: {item.last_delivery ? `${webhookStatusLabel(item.last_delivery.status)} · ${automationDate(item.last_delivery.created_at)}` : "Nenhuma entrega"}</p>
      <div className="mt-3 flex flex-wrap gap-2">{!item.revoked_at && <><button className={automationButton} disabled={loading || busy !== null} aria-label={`${item.enabled ? "Desativar" : "Ativar"} webhook ${item.url}`} onClick={() => void change(item)}>{item.enabled ? "Desativar" : "Ativar"}</button><button className={automationButton} disabled={loading || busy !== null} aria-label={`Revogar webhook ${item.url}`} onClick={() => setConfirmId(item.id)}>Revogar</button></>}<button className={automationButton} aria-label={`Ver entregas do webhook ${item.url}`} aria-expanded={historyId === item.id} onClick={() => setHistoryId(historyId === item.id ? null : item.id)}>Últimas entregas</button></div>
      {confirmId === item.id && <div className="mt-3 rounded-lg border border-rose-200 p-3"><p className="text-sm">Revogar este webhook é permanente e cancela as entregas pendentes. Para voltar a receber eventos, cadastre outro.</p><div className="mt-3 flex flex-wrap gap-2"><button disabled={loading || busy !== null} className={automationButton} onClick={() => void change(item, true)}>Confirmar revogação</button><button disabled={loading || busy !== null} className={automationButton} onClick={() => setConfirmId(null)}>Cancelar revogação</button></div></div>}
      {historyId === item.id && <WebhookDeliveries key={item.id} organizationId={organizationId} endpointId={item.id} />}
    </StaggerItem>)}</ul>}
  </section>;
}

function WebhookDeliveries({ organizationId, endpointId }: { organizationId: string; endpointId: string }) {
  const [items, setItems] = useState<WebhookDelivery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted) return;
      setLoading(true);
      try { const data = await api<{ items: WebhookDelivery[] }>(`${webhookPath(organizationId, endpointId)}/deliveries?limit=20`, { signal: controller.signal, cache: "no-store" }); if (!controller.signal.aborted) { setItems(data.items); setError(null); } }
      catch (caught) { if (!controller.signal.aborted) setError(webhookError(caught)); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    });
    return () => controller.abort();
  }, [organizationId, endpointId, revision]);
  return <section aria-label="Últimas 20 entregas" className="mt-4 border-t border-line pt-4"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">Últimas 20 entregas</h4><button disabled={loading} className={automationButton} onClick={() => setRevision((value) => value + 1)}>Atualizar entregas</button></div>
    {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    {loading ? <LoadingBlock label="Carregando entregas…" className="mt-3"><SkeletonList rows={3} avatar={false} /></LoadingBlock> : !items.length && !error ? <EmptyState className="mt-3" title="Nenhuma entrega registrada" /> : <ol className="mt-3 space-y-3">{items.map((item, index) => <StaggerItem as="li" key={item.id} index={index} className="rounded-lg bg-paper p-3 text-sm"><p className="font-semibold">{webhookStatusLabel(item.status)} · {automationDate(item.created_at)}</p><p className="mt-1">{item.attempts} tentativa(s){item.last_status_code ? ` · HTTP ${item.last_status_code}` : ""}</p>{item.last_error && <p className="mt-1 text-rose-700">{webhookDeliveryError(item.last_error)}</p>}<p className="mt-1 break-all text-muted-foreground">Execução: {item.run_id}</p>{item.delivered_at && <p className="mt-1 text-muted-foreground">Entregue em {automationDate(item.delivered_at)}</p>}</StaggerItem>)}</ol>}
  </section>;
}
