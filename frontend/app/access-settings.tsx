"use client";

import { AlertTriangle, ExternalLink, KeyRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { MentionComposer, type MentionCandidate } from "./mention-composer";
import "./interface-motion.css";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Key = { id: string; name: string; prefix: string; scopes: string[]; last_used_at: string | null; expires_at: string | null; revoked_at: string | null };
const scopeOptions = [
  { value: "search:read", label: "Buscar documentos", hint: "Procura trechos nos documentos que a chave enxerga." },
  { value: "documents:read", label: "Ler documentos", hint: "Abre o texto completo de um documento encontrado." },
  { value: "ask:run", label: "Fazer perguntas", hint: "Responde com citações. Usa a cota de IA da organização e só funciona se o serviço permitir perguntas." },
];
const MAX_NODES = 20;
const dateLabel = (value: string | null, empty = "—") => value ? new Date(value).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : empty;
const fieldClass = "mt-1 block min-h-11 w-full rounded-lg border border-[color:var(--control-edge)] bg-paper px-3 py-2";
const docsLinkClass = "inline-flex min-h-11 items-center gap-1 font-medium text-primary underline underline-offset-4";

function Status({ revokedAt, expired }: { revokedAt: string | null; expired: boolean }) {
  if (revokedAt) return <span className="inline-block rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">Revogada</span>;
  if (expired) return <span className="inline-block rounded-full border border-line px-2 py-0.5 text-xs font-semibold text-muted-foreground">Expirada</span>;
  return <span className="inline-block rounded-full border border-line px-2 py-0.5 text-xs font-semibold text-primary">Ativa</span>;
}

function ScopeChips({ scopes }: { scopes: string[] }) {
  return <span className="flex flex-wrap gap-1">{scopes.map((scope) => <code key={scope} className="rounded bg-paper px-1.5 py-0.5 text-xs">{scope}</code>)}</span>;
}

export function AccessSettings({ organizationId, api }: { organizationId: string; api: Api }) {
  const [enabled, setEnabled] = useState(false);
  const [keys, setKeys] = useState<Key[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [selectedScopes, setSelectedScopes] = useState(["search:read", "documents:read"]);
  const [expiry, setExpiry] = useState("");
  const [nodeQuery, setNodeQuery] = useState("");
  const [nodes, setNodes] = useState<MentionCandidate[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const secretField = useRef<HTMLTextAreaElement>(null);
  const selector = useRef<HTMLTextAreaElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const base = `/organizations/${organizationId}`;
  const showError = (caught: unknown) => setError(caught instanceof Error ? caught.message : "Não foi possível atualizar o acesso.");
  const load = useCallback(async () => {
    const [settings, list] = await Promise.all([api<{ public_api_enabled: boolean }>(`${base}/access-settings`), api<Key[]>(`${base}/api-keys`)]);
    setEnabled(settings.public_api_enabled); setKeys(list); setNow(Date.now());
  }, [api, base]);
  const firstLoad = useCallback(async () => {
    setLoading(true); setLoadFailed(false); setError(null);
    try { await load(); } catch (caught) { showError(caught); setLoadFailed(true); } finally { setLoading(false); }
  }, [load]);
  useEffect(() => {
    let active = true;
    Promise.resolve().then(load).catch((caught) => { if (active) { showError(caught); setLoadFailed(true); } }).finally(() => { if (active) setLoading(false); });
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
      const created = await api<Key & { key: string }>(`${base}/api-keys`, { method: "POST", body: JSON.stringify({ name: name.trim(), scopes: selectedScopes, node_ids: nodes.length ? nodes.map((node) => node.node_id) : null, expires_at: expiry ? new Date(expiry).toISOString() : null }) });
      setSecret(created.key); setCopied(false); setName(""); setNodes([]); setNodeQuery(""); setExpiry(""); await load();
    } catch (caught) { showError(caught); } finally { setBusy(false); }
  }
  async function revoke(key: Key) {
    if (!window.confirm(`Revogar a chave ${key.name}? As automações que a usam perderão o acesso imediatamente. Esta ação não pode ser desfeita.`)) return;
    setBusy(true); setError(null);
    try { await api(`${base}/api-keys/${key.id}`, { method: "DELETE" }); await load(); }
    catch (caught) { showError(caught); } finally { setBusy(false); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(secret ?? ""); setCopied(true); }
    catch { secretField.current?.select(); setError("Não foi possível copiar automaticamente. A chave está selecionada: copie com Ctrl+C ou Cmd+C."); }
  }
  function closeSecret() {
    dialog.current?.close(); setSecret(null); setCopied(false);
    // The create button may still be disabled (busy) or gone: fall back to the section title so focus never lands on <body>.
    requestAnimationFrame(() => { const button = createButton.current; if (button && !button.disabled) button.focus(); else heading.current?.focus(); });
  }
  const noScope = selectedScopes.length === 0;
  const tooManyNodes = nodes.length > MAX_NODES;
  const formProblem = noScope ? "Selecione ao menos um escopo." : tooManyNodes ? `Selecione no máximo ${MAX_NODES} pastas ou arquivos.` : null;
  const isExpired = (key: Key) => Boolean(key.expires_at) && new Date(key.expires_at as string).getTime() < now;
  const revokeButton = (key: Key) => <button type="button" disabled={busy} onClick={() => void revoke(key)} aria-label={`Revogar a chave ${key.name}`} className="min-h-11 rounded-lg border border-rose-200 px-4 text-sm font-semibold text-rose-700 disabled:opacity-50">Revogar</button>;
  return <section className="mt-6 rounded-lg border border-line-soft bg-panel p-4 sm:p-6" aria-labelledby="api-keys-title" aria-busy={busy || loading}>
    <div className="flex items-center gap-3"><KeyRound size={22} className="text-primary" aria-hidden="true" /><h2 id="api-keys-title" ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">Chaves de API</h2></div>
    <p className="mt-2 text-sm text-muted-foreground">Crie chaves para que automações e integrações leiam os documentos desta organização pela API pública. Cada chave só funciona enquanto quem a criou tiver acesso ativo.</p>
    {error && <div role="alert" className="mt-3 text-sm text-rose-700"><p>{error}</p>{loadFailed && <button type="button" onClick={() => void firstLoad()} className="min-h-11 underline">Tentar novamente</button>}</div>}
    {loading ? <p role="status" className="mt-4">Carregando chaves…</p> : !loadFailed && <>
      <label className="mt-4 flex min-h-11 items-start gap-3"><input type="checkbox" checked={enabled} disabled={busy} onChange={() => void toggle()} className="mt-1" /><span>Habilitar API pública<span className="block text-sm text-muted-foreground">{enabled ? "As chaves ativas estão funcionando." : "Desligada: nenhuma chave desta organização funciona, mesmo as já criadas."}</span></span></label>
      <h3 className="mt-6 font-semibold">Chaves desta organização</h3>
      {keys.length === 0 ? <p className="mt-2 rounded-lg bg-paper p-4 text-sm text-muted-foreground">Nenhuma chave criada ainda. Use o formulário abaixo para criar a primeira.</p> : <>
        <div className="mt-3 hidden overflow-x-auto md:block"><table className="w-full text-left text-sm"><caption className="sr-only">Chaves desta organização</caption><thead><tr>{["Nome / prefixo", "Escopos", "Situação", "Último uso", "Expira", "Ação"].map((title) => <th key={title} scope="col" className="p-2">{title}</th>)}</tr></thead><tbody>{keys.map((key) => <tr key={key.id} className="border-t border-line-soft"><td className="p-2">{key.name}<code className="block text-xs">{key.prefix}</code></td><td className="p-2"><ScopeChips scopes={key.scopes} /></td><td className="p-2"><Status revokedAt={key.revoked_at} expired={isExpired(key)} /></td><td className="p-2">{dateLabel(key.last_used_at, "Nunca")}</td><td className="p-2">{dateLabel(key.expires_at, "Não expira")}</td><td className="p-2">{key.revoked_at ? "—" : revokeButton(key)}</td></tr>)}</tbody></table></div>
        <ul className="mt-3 space-y-3 md:hidden" aria-label="Chaves desta organização">{keys.map((key) => <li key={key.id} className="rounded-lg border border-line-soft p-3 text-sm">
          <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words font-semibold">{key.name}</p><code className="block break-all text-xs">{key.prefix}</code></div><Status revokedAt={key.revoked_at} expired={isExpired(key)} /></div>
          <div className="mt-2"><ScopeChips scopes={key.scopes} /></div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-muted-foreground"><dt>Último uso</dt><dd>{dateLabel(key.last_used_at, "Nunca")}</dd><dt>Expira</dt><dd>{dateLabel(key.expires_at, "Não expira")}</dd></dl>
          {!key.revoked_at && <div className="mt-2">{revokeButton(key)}</div>}
        </li>)}</ul>
      </>}
      <form onSubmit={(event) => void create(event)} className="mt-8 space-y-5 border-t border-line-soft pt-6" aria-describedby={formProblem ? "key-form-problem" : undefined}>
        <div className="flex flex-wrap items-center justify-between gap-x-4"><h3 className="font-semibold">Nova chave</h3><a href="/docs/api" target="_blank" rel="noopener noreferrer" className={`${docsLinkClass} text-sm`}>Como usar a chave: Documentação da API<ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (abre em nova aba)</span></a></div>
        <label className="block font-medium">Nome<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Automação de relatórios" autoComplete="off" className={`${fieldClass} font-normal`} /></label>
        <fieldset><legend className="font-medium">Escopos</legend><p className="text-sm text-muted-foreground">Escolha o que esta chave pode fazer. Prefira o mínimo necessário.</p><div className="mt-2 grid gap-2 md:grid-cols-3">{scopeOptions.map((scope) => <label key={scope.value} className="flex min-h-11 items-start gap-3 rounded-lg border border-line-soft p-3"><input type="checkbox" checked={selectedScopes.includes(scope.value)} onChange={(event) => setSelectedScopes((current) => event.target.checked ? [...current, scope.value] : current.filter((item) => item !== scope.value))} className="mt-1" /><span><span className="block font-medium">{scope.label} <code className="text-xs font-normal text-muted-foreground">{scope.value}</code></span><span className="block text-sm text-muted-foreground">{scope.hint}</span></span></label>)}</div></fieldset>
        <label className="block font-medium">Expiração (opcional)<input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} className={`${fieldClass} font-normal sm:w-auto`} /><span className="mt-1 block text-sm font-normal text-muted-foreground">Sem data, a chave não expira.</span></label>
        <fieldset><legend className="font-medium">Pastas ou arquivos (opcional)</legend><p className="mb-2 text-sm text-muted-foreground">Digite @ e o nome para escolher até {MAX_NODES}. Sem seleção, a chave acessa toda a organização.</p><div className="rounded-lg border border-[color:var(--control-edge)] bg-paper px-2 py-1"><MentionComposer organizationId={organizationId} value={nodeQuery} onChange={setNodeQuery} mentions={nodes} onMentionsChange={setNodes} all={true} providers={[]} disabled={busy} textareaRef={selector} onSubmit={() => {}} label="Pastas ou arquivos da chave" placeholder="Digite @ e o nome de uma pasta ou arquivo" /></div></fieldset>
        {formProblem && <p id="key-form-problem" role="alert" className="text-sm text-rose-700">{formProblem}</p>}
        <button ref={createButton} disabled={busy || !name.trim() || Boolean(formProblem)} className="min-h-11 rounded-lg bg-primary px-5 py-2 font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Salvando…" : "Criar chave"}</button>
      </form>
    </>}
    {secret && <dialog ref={dialog} onCancel={closeSecret} onClose={() => setSecret(null)} aria-labelledby="api-secret-title" className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg border border-line-soft bg-panel p-4 text-foreground backdrop:bg-black/40 sm:p-6" data-arquivio-motion-root=""><div data-arquivio-motion="panel">
      <h3 id="api-secret-title" className="text-xl font-semibold">Copie sua chave agora</h3>
      <p className="mt-3 flex gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"><AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden="true" /><span>Esta é a única vez que a chave aparece. Guarde-a em um local seguro (gerenciador de senhas ou variável de ambiente) e nunca a coloque em URLs ou repositórios.</span></p>
      <textarea ref={secretField} readOnly rows={3} aria-label="Chave de API" value={secret} onFocus={(event) => event.currentTarget.select()} className="mt-4 w-full break-all rounded-lg border border-[color:var(--control-edge)] bg-paper p-3 font-mono text-sm" />
      <p className="mt-2 text-sm text-muted-foreground">Envie a chave no cabeçalho <code>Authorization: Bearer</code>. <a href="/docs/api" target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline underline-offset-4">Ver documentação<span className="sr-only"> (abre em nova aba)</span></a></p>
      <div className="mt-4 flex flex-wrap gap-3"><button type="button" onClick={() => void copy()} className="min-h-11 rounded-lg bg-primary px-5 font-semibold text-primary-foreground">{copied ? "Chave copiada" : "Copiar chave"}</button><button type="button" onClick={closeSecret} className="min-h-11 rounded-lg border border-[color:var(--control-edge)] px-5 font-semibold">Já guardei, fechar</button></div>
      <p role="status" className="sr-only">{copied ? "Chave copiada para a área de transferência." : ""}</p>
    </div></dialog>}
  </section>;
}
