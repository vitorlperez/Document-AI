"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { MentionComposer, type MentionCandidate } from "./mention-composer";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Key = { id: string; name: string; prefix: string; scopes: string[]; last_used_at: string | null; expires_at: string | null; revoked_at: string | null };
const scopes = ["search:read", "documents:read", "ask:run"];
const dateLabel = (value: string | null) => value ? new Date(value).toLocaleString("pt-BR") : "—";

export function AccessSettings({ organizationId, api }: { organizationId: string; api: Api }) {
  const [enabled, setEnabled] = useState(false);
  const [keys, setKeys] = useState<Key[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [selectedScopes, setSelectedScopes] = useState(["search:read", "documents:read"]);
  const [expiry, setExpiry] = useState("");
  const [nodeQuery, setNodeQuery] = useState("");
  const [nodes, setNodes] = useState<MentionCandidate[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const selector = useRef<HTMLTextAreaElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const base = `/organizations/${organizationId}`;
  const showError = (caught: unknown) => setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o acesso.");
  const load = useCallback(async () => {
    const [settings, list] = await Promise.all([api<{ public_api_enabled: boolean }>(`${base}/access-settings`), api<Key[]>(`${base}/api-keys`)]);
    setEnabled(settings.public_api_enabled); setKeys(list);
  }, [api, base]);
  useEffect(() => {
    let active = true;
    Promise.resolve().then(load).catch((caught) => { if (active) showError(caught); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [load]);
  useEffect(() => { if (secret && dialog.current && !dialog.current.open) dialog.current.showModal(); }, [secret]);
  async function toggle() {
    setBusy(true); setError(null);
    try { await api(`${base}/access-settings`, { method: "PUT", body: JSON.stringify({ public_api_enabled: !enabled }) }); setEnabled(!enabled); }
    catch (caught) { showError(caught); } finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await api<Key & { key: string }>(`${base}/api-keys`, { method: "POST", body: JSON.stringify({ name, scopes: selectedScopes, node_ids: nodes.length ? nodes.map((node) => node.node_id) : null, expires_at: expiry ? new Date(expiry).toISOString() : null }) });
      setSecret(created.key); setCopied(false); setName(""); setNodes([]); setNodeQuery(""); setExpiry(""); await load();
    } catch (caught) { showError(caught); } finally { setBusy(false); }
  }
  async function revoke(key: Key) {
    if (!window.confirm(`Revogar a chave ${key.name}? As automações que a usam perderão o acesso.`)) return;
    setBusy(true); setError(null);
    try { await api(`${base}/api-keys/${key.id}`, { method: "DELETE" }); await load(); }
    catch (caught) { showError(caught); } finally { setBusy(false); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(secret ?? ""); setCopied(true); }
    catch { setError("Selecione a chave e copie manualmente."); }
  }
  function closeSecret() {
    dialog.current?.close(); setSecret(null); setCopied(false);
    // The create button may still be disabled (busy) or gone: fall back to the section title so focus never lands on <body>.
    requestAnimationFrame(() => { const button = createButton.current; if (button && !button.disabled) button.focus(); else heading.current?.focus(); });
  }
  return <section className="mt-6 rounded-lg border border-line-soft bg-white p-6" aria-busy={busy || loading}>
    <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">Acesso por API e IA</h2>
    <p className="mt-2 text-sm text-muted-foreground">Conecte automações aos documentos desta organização. As chaves dependem do acesso ativo de quem as criou.</p>
    {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    {loading ? <p role="status" className="mt-4">Carregando acesso…</p> : <>
      <label className="mt-4 flex items-center gap-3"><input type="checkbox" checked={enabled} disabled={busy} onChange={() => void toggle()} />Habilitar API pública</label>
      <div className="mt-5 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Chaves desta organização</caption><thead><tr>{["Nome / prefixo", "Escopos", "Último uso", "Expira", "Ação"].map((title) => <th key={title} className="p-2">{title}</th>)}</tr></thead><tbody>{keys.map((key) => <tr key={key.id} className="border-t border-line-soft"><td className="p-2">{key.name}<code className="block text-xs">{key.prefix}</code></td><td className="p-2">{key.scopes.join(", ")}</td><td className="p-2">{dateLabel(key.last_used_at)}</td><td className="p-2">{dateLabel(key.expires_at)}</td><td className="p-2">{key.revoked_at ? "Revogada" : <button type="button" disabled={busy} onClick={() => void revoke(key)} className="min-h-11 px-3 text-rose-700 underline">Revogar {key.name}</button>}</td></tr>)}</tbody></table>{keys.length === 0 && <p className="p-2 text-sm text-muted-foreground">Nenhuma chave criada.</p>}</div>
      <form onSubmit={(event) => void create(event)} className="mt-6 space-y-4">
        <h3 className="font-semibold">Nova chave</h3>
        <label className="block">Nome<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} className="mt-1 block min-h-11 w-full rounded border border-line-soft p-2" /></label>
        <fieldset><legend>Escopos</legend><div className="flex flex-wrap gap-4">{scopes.map((scope) => <label key={scope} className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={selectedScopes.includes(scope)} onChange={(event) => setSelectedScopes((current) => event.target.checked ? [...current, scope] : current.filter((item) => item !== scope))} />{scope}</label>)}</div><p className="text-xs text-muted-foreground">ask:run permite perguntas quando habilitadas pelo serviço.</p></fieldset>
        <label className="block">Expiração opcional<input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} className="mt-1 block min-h-11 rounded border border-line-soft p-2" /></label>
        <fieldset><legend>Pastas ou arquivos opcionais</legend><p className="mb-2 text-sm text-muted-foreground">Digite @ e o nome para selecionar. Sem seleção, a chave acessa toda a organização.</p><MentionComposer organizationId={organizationId} value={nodeQuery} onChange={setNodeQuery} mentions={nodes} onMentionsChange={setNodes} all={true} providers={[]} disabled={busy} textareaRef={selector} onSubmit={() => {}} /></fieldset>
        <button ref={createButton} disabled={busy || selectedScopes.length === 0 || nodes.length > 20} className="min-h-11 rounded bg-primary px-4 py-2 font-semibold text-white">{busy ? "Salvando…" : "Criar chave"}</button>
      </form>
    </>}
    {secret && <dialog ref={dialog} onCancel={closeSecret} onClose={() => setSecret(null)} aria-labelledby="api-secret-title" className="w-full max-w-lg rounded-lg border border-line-soft bg-white p-6 backdrop:bg-black/40"><h3 id="api-secret-title" className="text-xl font-semibold">Copie sua chave agora</h3><p className="mt-2 text-sm">Ela será exibida apenas uma vez. Guarde em um local seguro.</p><textarea readOnly aria-label="Chave de API" value={secret} className="mt-4 w-full break-all rounded border p-3 font-mono text-sm" /><div className="mt-4 flex gap-3"><button type="button" onClick={() => void copy()} className="min-h-11 rounded bg-primary px-4 text-white">{copied ? "Copiada" : "Copiar chave"}</button><button type="button" onClick={closeSecret} className="min-h-11 rounded border px-4">Fechar</button></div></dialog>}
  </section>;
}
