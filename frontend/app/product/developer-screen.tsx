"use client";

import { BookOpen, Check, Code2, Copy, Download, ExternalLink, Plug } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Enter, ErrorState, LoadingBlock, SkeletonCard, Spinner, StaggerItem } from "../ui";
import { AccessSettings } from "../access-settings";
import { mcpClientExamples } from "../developer-mcp-config";
import { API_BASE } from "../docs/api/api-docs-logic";
import { type Company, api, messageFor } from "./types-and-api";

type McpInfo = { configured: boolean; resource_url: string | null; issuer_url: string | null; transport: string; static_key_enabled: boolean; tools: string[] };
type McpConnection = { active: boolean; node_ids?: string[] | null };
const toolDescriptions: Record<string, string> = {
  search: "Busca documentos indexados por uma consulta.",
  fetch: "Lê o texto de um documento encontrado na busca.",
  list_sources: "Lista as fontes disponíveis para consulta.",
};
const codeClass = "min-w-0 overflow-x-auto rounded-lg border border-line-soft bg-paper p-4 text-xs leading-6";
const linkClass = "mo-interactive mo-focus inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary underline";
const buttonClass = "mo-interactive mo-focus inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-semibold";

/** Code block with a copy button; `wrap` breaks long single-line commands instead of scrolling sideways. */
function CodeBlock({ code, label, wrap = false }: { code: string; label: string; wrap?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code); setCopied(true); setCopyError(false);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch { setCopied(false); setCopyError(true); }
  }
  return <div className="mt-2 flex flex-col gap-2">
    <pre tabIndex={0} aria-label={label} className={`${codeClass} ${wrap ? "whitespace-pre-wrap break-all" : ""}`}><code>{code}</code></pre>
    <button type="button" onClick={() => void copy()} aria-label={`Copiar: ${label}`} className={`${buttonClass} min-w-28 shrink-0 self-start border border-[color:var(--control-edge)]`}>{copied ? <Check size={16} className="mo-check-pop" aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? "Copiado" : "Copiar"}</button>
    <span role="status" className="min-h-4 text-xs text-muted-foreground">{copyError ? "Não foi possível copiar. Selecione o código e copie com Ctrl+C ou Cmd+C." : copied ? "Copiado para a área de transferência." : ""}</span>
  </div>;
}

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
    <div className="flex items-center gap-3"><Plug size={22} className="text-primary" aria-hidden="true" /><h2 id="mcp-title" className="text-xl font-semibold">Conexão MCP</h2></div>
    <p className="mt-2 text-sm text-muted-foreground">Conecte clientes de IA (Claude Code, Cursor, Claude Desktop) aos documentos da organização pelo Model Context Protocol (MCP). O acesso é somente de leitura.</p>
    {error && <ErrorState className="mt-4" title="Não foi possível atualizar a conexão" description={error} actions={!info && <button type="button" onClick={() => void load()} className="mo-interactive min-h-11 underline">Tentar novamente</button>} />}
    {loading ? <LoadingBlock label="Carregando informações do MCP…" className="mt-4 grid gap-4 sm:grid-cols-2"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></LoadingBlock> : info && <>
      <p className="mt-4 rounded-lg bg-paper p-3 text-sm">{info.configured ? "Conexão configurada neste ambiente (Streamable HTTP). Isso indica que a URL e a autenticação existem, não que o serviço esteja no ar." : "A conexão MCP ainda não está configurada neste ambiente. Os exemplos aparecem quando a URL e a autenticação forem configuradas."}</p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked={enabled} disabled={busy || !info.configured} onChange={() => void toggle()} />Habilitar MCP para a organização</label>
        <button type="button" disabled={busy || (!connection.active && (!enabled || !info.configured))} onClick={() => void bind()} className="mo-interactive inline-flex items-center gap-2 min-h-11 rounded-lg border border-line px-4 text-sm font-semibold disabled:opacity-50">{busy && <Spinner size={16} />}{connection.active ? "Desvincular minha conta" : "Vincular minha conta"}</button>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{connection.active ? `Sua conta está vinculada${connection.node_ids?.length ? " às pastas e arquivos selecionados" : " a toda esta organização"}.${!enabled ? " O acesso está suspenso enquanto o MCP estiver desabilitado." : ""}` : "Para autenticar por OAuth, habilite o MCP e vincule sua conta. Cada conta pode ter uma organização vinculada por vez."}</p>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div><h3 className="font-semibold">Autenticação</h3><p className="mt-2 text-sm text-muted-foreground">O cliente abre o login (OAuth) do Arquivio: entre com a sua conta. O servidor confere o token, a organização vinculada e se a sua participação continua ativa.</p>{info.static_key_enabled && <p className="mt-2 text-sm text-muted-foreground">Alternativa: use uma chave de API, enviada no cabeçalho <code>Authorization: Bearer</code>. Exige a API pública e o MCP habilitados e a chave com os escopos search:read e documents:read.</p>}{info.issuer_url && <p className="mt-3 break-all text-sm"><span className="font-semibold">Servidor de autorização (OAuth): </span><code>{info.issuer_url}</code></p>}</div>
        <div><h3 className="font-semibold">Ferramentas do servidor</h3><ul className="mt-2 space-y-3">{info.tools.map((tool, index) => <StaggerItem as="li" index={index} key={tool} className="text-sm"><code className="font-semibold text-primary">{tool}</code><p className="mt-1 text-muted-foreground">{toolDescriptions[tool] ?? "Ferramenta disponibilizada pelo servidor."}</p></StaggerItem>)}</ul></div>
      </div>
      {examples && <div className="mt-6 border-t border-line-soft pt-6">
        <h3 className="font-semibold">Conectar um cliente</h3><p className="mt-2 text-sm">URL do servidor MCP</p><CodeBlock code={info.resource_url ?? ""} label="URL do servidor MCP" wrap />
        <div className="mt-6 grid min-w-0 gap-6 lg:grid-cols-2">
          <div className="min-w-0"><h4 className="font-semibold">Claude Code</h4><CodeBlock code={examples.claudeCode} label="Comando do Claude Code" wrap /><p className="mt-2 text-sm text-muted-foreground">Depois, abra /mcp no Claude Code para autenticar.</p>{info.static_key_enabled && <><p className="mt-3 text-sm text-muted-foreground">Ou, com uma chave de API (guarde-a na variável ARQUIVIO_API_KEY):</p><CodeBlock code={examples.claudeCodeKey} label="Comando do Claude Code com chave de API" wrap /></>}<a href="https://code.claude.com/docs/en/mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação do Claude Code<ExternalLink size={14} aria-hidden="true" /></a></div>
          <div className="min-w-0"><h4 className="font-semibold">Cursor</h4><p className="mt-2 text-sm text-muted-foreground">Adicione ao arquivo .cursor/mcp.json do projeto e conclua a autenticação OAuth no Cursor.</p><CodeBlock code={examples.cursor} label="Configuração do Cursor" /><a href="https://cursor.com/docs/mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação do Cursor<ExternalLink size={14} aria-hidden="true" /></a></div>
          <div className="lg:col-span-2"><h4 className="font-semibold">Claude Desktop</h4><p className="mt-2 text-sm text-muted-foreground">Em Personalizar → Conectores, adicione um conector personalizado chamado Arquivio com a URL do servidor acima, conecte e autorize sua conta. Esse cliente precisa alcançar o servidor pela internet.</p><a href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp" target="_blank" rel="noreferrer" className={linkClass}>Documentação de conectores do Claude<ExternalLink size={14} aria-hidden="true" /></a></div>
        </div>
      </div>}
    </>}
  </section>;
}

function ApiDocsCard() {
  return <section aria-labelledby="api-docs-title" className="mt-6 flex flex-col gap-4 rounded-lg border border-line-soft bg-panel p-4 sm:p-6 lg:flex-row lg:items-center lg:justify-between">
    <div className="flex min-w-0 gap-3"><BookOpen size={22} className="mt-0.5 shrink-0 text-primary" aria-hidden="true" /><div className="min-w-0"><h2 id="api-docs-title" className="text-xl font-semibold">Documentação da API</h2><p className="mt-2 text-sm text-muted-foreground">Guia de autenticação, escopos, limites e erros, com exemplos em curl, JavaScript e Python.</p><p className="mt-2 break-all text-sm">URL base: <code>{API_BASE}</code></p></div></div>
    <div className="flex flex-col gap-3 sm:flex-row lg:shrink-0">
      <a href="/docs/api" target="_blank" rel="noopener noreferrer" aria-label="Abrir a documentação da API em nova aba" className={`${buttonClass} justify-center bg-primary text-primary-foreground`}>Abrir documentação<ExternalLink size={16} aria-hidden="true" /></a>
      <a href="/api/v1/openapi.json" download="openapi-v1.json" className={`${buttonClass} justify-center border border-[color:var(--control-edge)]`}><Download size={16} aria-hidden="true" />Baixar openapi-v1.json</a>
    </div>
  </section>;
}

export function DeveloperScreen({ company }: { company: Company }) {
  return <Enter variant="fade">
    <div className="flex items-center gap-3"><Code2 size={24} className="text-primary" aria-hidden="true" /><div><h1 className="developer-title text-2xl font-semibold text-ink">Desenvolvedor</h1><p className="mt-1 text-sm text-muted-foreground">Chaves de API e conexão de clientes de IA para a organização {company.name}.</p></div></div>
    <ApiDocsCard />
    <AccessSettings organizationId={company.id} api={api} />
    <McpSettings organizationId={company.id} />
  </Enter>;
}
