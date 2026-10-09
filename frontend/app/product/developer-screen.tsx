"use client";

import { Code2, ExternalLink, Plug } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { AccessSettings } from "../access-settings";
import { mcpClientExamples } from "../developer-mcp-config";
import { type Company, api, messageFor } from "./types-and-api";

type McpInfo = { configured: boolean; resource_url: string | null; issuer_url: string | null; transport: string; static_key_enabled: boolean; tools: string[] };
type McpConnection = { active: boolean; node_ids?: string[] | null };
const toolDescriptions: Record<string, string> = {
  search: "Busca documentos indexados por uma consulta.",
  fetch: "Lê o texto de um documento encontrado na busca.",
  list_sources: "Lista as fontes disponíveis para consulta.",
};
const codeClass = "mt-3 overflow-x-auto rounded-lg border border-line-soft bg-paper p-4 text-xs leading-6";
const linkClass = "inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary underline";

function McpSettings({ organizationId }: { organizationId: string }) {
  const [info, setInfo] = useState<McpInfo | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [connection, setConnection] = useState<McpConnection>({ active: false });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${organizationId}`;
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try {
      const [metadata, settings, binding] = await Promise.all([
        api<McpInfo>(`${base}/mcp-info`, { signal, cache: "no-store" }),
        api<{ mcp_enabled: boolean }>(`${base}/access-settings`, { signal, cache: "no-store" }),
        api<McpConnection>(`${base}/mcp-connection`, { signal, cache: "no-store" }),
      ]);
      if (signal?.aborted) return;
      setInfo(metadata); setEnabled(settings.mcp_enabled); setConnection(binding);
    } catch (caught) { if (!signal?.aborted) setError(messageFor(caught)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [base]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => { if (!controller.signal.aborted) void load(controller.signal); });
    return () => controller.abort();
  }, [load]);
  async function toggle() {
    setBusy(true); setError(null);
    try {
      const result = await api<{ mcp_enabled: boolean }>(`${base}/mcp-settings`, { method: "PUT", body: JSON.stringify({ mcp_enabled: !enabled }) });
      setEnabled(result.mcp_enabled);
    } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); }
  }
  async function bind() {
    if (!connection.active && !window.confirm("Vincular sua conta a esta organização? O vínculo MCP anterior será substituído. Seus clientes terão acesso de leitura a toda esta organização.")) return;
    setBusy(true); setError(null);
    try {
      if (connection.active) { await api(`${base}/mcp-connection`, { method: "DELETE" }); setConnection({ active: false }); }
      else setConnection(await api<McpConnection>(`${base}/mcp-connection`, { method: "PUT", body: JSON.stringify({}) }));
    } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); }
  }
  const examples = info?.configured ? mcpClientExamples(info.resource_url) : null;
  return <section className="mt-6 rounded-lg border border-line-soft bg-panel p-4 sm:p-6" aria-labelledby="mcp-title" aria-busy={loading || busy}>
    <div className="flex items-center gap-3"><Plug size={22} className="text-primary" aria-hidden="true" /><h2 id="mcp-title" className="text-xl font-semibold">MCP</h2></div>
    <p className="mt-2 text-sm text-muted-foreground">Conecte seus clientes de IA aos documentos da organização pelo Model Context Protocol. O servidor oferece acesso somente de leitura.</p>
    {error && <div role="alert" className="mt-4 text-sm text-rose-700"><p>{error}</p>{!info && <button type="button" onClick={() => void load()} className="min-h-11 underline">Tentar novamente</button>}</div>}
    {loading ? <p role="status" className="mt-4">Carregando informações do MCP…</p> : info && <>
      <p className="mt-4 rounded-lg bg-paper p-3 text-sm">{info.configured ? "Servidor configurado para Streamable HTTP. A conexão depende da disponibilidade do serviço e da autorização no cliente." : "O servidor MCP já existe, mas a conexão ainda não está configurada neste ambiente. Os exemplos serão exibidos quando a URL e a autenticação estiverem configuradas."}</p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked={enabled} disabled={busy || !info.configured} onChange={() => void toggle()} />Habilitar MCP para a organização</label>
        <button type="button" disabled={busy || (!connection.active && (!enabled || !info.configured))} onClick={() => void bind()} className="min-h-11 rounded-lg border border-line px-4 text-sm font-semibold disabled:opacity-50">{connection.active ? "Desvincular minha conta" : "Vincular minha conta"}</button>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{connection.active ? `Sua conta está vinculada${connection.node_ids?.length ? " às pastas e arquivos selecionados" : " a toda esta organização"}.${!enabled ? " O acesso está suspenso enquanto o MCP estiver desabilitado." : ""}` : "Para autenticar por OAuth, habilite o MCP e vincule sua conta. Cada conta pode ter uma organização vinculada por vez."}</p>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div><h3 className="font-semibold">Autenticação</h3><p className="mt-2 text-sm text-muted-foreground">Use OAuth no cliente e entre com a mesma conta do Arquivio. O servidor valida o token Bearer, a organização vinculada e sua participação ativa.</p>{info.static_key_enabled && <p className="mt-2 text-sm text-muted-foreground">Este ambiente também aceita uma chave de API no cabeçalho Authorization: Bearer. Habilite a API pública e o MCP; use os escopos search:read e documents:read.</p>}{info.issuer_url && <p className="mt-3 break-all text-sm"><span className="font-semibold">Emissor OAuth: </span><code>{info.issuer_url}</code></p>}</div>
        <div><h3 className="font-semibold">Ferramentas do servidor</h3><ul className="mt-2 space-y-3">{info.tools.map((tool) => <li key={tool} className="text-sm"><code className="font-semibold text-primary">{tool}</code><p className="mt-1 text-muted-foreground">{toolDescriptions[tool] ?? "Ferramenta disponibilizada pelo servidor."}</p></li>)}</ul></div>
      </div>
      {examples && <div className="mt-6 border-t border-line-soft pt-6">
        <h3 className="font-semibold">Conectar um cliente</h3><p className="mt-2 text-sm">URL do servidor</p><pre className={`${codeClass} whitespace-pre-wrap break-all`}><code>{info.resource_url}</code></pre>
        <div className="mt-6 grid min-w-0 gap-6 lg:grid-cols-2">
          <div className="min-w-0"><h4 className="font-semibold">Claude Code</h4><pre className={codeClass}><code>{examples.claudeCode}</code></pre><p className="mt-2 text-sm text-muted-foreground">Depois, abra /mcp no Claude Code para autenticar.</p><a href="https://code.claude.com/docs/en/mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação do Claude Code<ExternalLink size={14} aria-hidden="true" /></a></div>
          <div className="min-w-0"><h4 className="font-semibold">Cursor</h4><p className="mt-2 text-sm text-muted-foreground">Adicione ao arquivo .cursor/mcp.json do projeto e conclua a autenticação OAuth no Cursor.</p><pre className={codeClass}><code>{examples.cursor}</code></pre><a href="https://cursor.com/docs/mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação do Cursor<ExternalLink size={14} aria-hidden="true" /></a></div>
          <div className="lg:col-span-2"><h4 className="font-semibold">Claude Desktop</h4><p className="mt-2 text-sm text-muted-foreground">Em Personalizar → Conectores, adicione um conector personalizado chamado Arquivio com a URL acima. Conecte e autorize sua conta. O servidor precisa estar acessível pela internet para esse cliente.</p><a href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação de conectores do Claude<ExternalLink size={14} aria-hidden="true" /></a></div>
        </div>
      </div>}
    </>}
  </section>;
}

export function DeveloperScreen({ company }: { company: Company }) {
  return <div>
    <div className="flex items-center gap-3"><Code2 size={22} className="text-primary" aria-hidden="true" /><div><h1 className="text-xl font-semibold text-ink">Desenvolvedor</h1><p className="mt-1 text-sm text-muted-foreground">Chaves de API e conexão de clientes de IA para sua organização.</p></div></div>
    <AccessSettings organizationId={company.id} api={api} />
    <McpSettings organizationId={company.id} />
  </div>;
}
