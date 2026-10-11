"use client";

import { Check, Copy, Download } from "lucide-react";
import { useEffect, useState } from "react";
import { LANGUAGES, SPEC_URL, codeSample, endpointsFrom, type Endpoint, type Field, type Language } from "./api-docs-logic";

type State = { status: "loading" } | { status: "error" } | { status: "ready"; endpoints: Endpoint[] };

export function ApiReference() {
  const [state, setState] = useState<State>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    fetch(SPEC_URL, { signal: controller.signal, headers: { accept: "application/json" } })
      .then((response) => { if (!response.ok) throw new Error(String(response.status)); return response.json() as Promise<Record<string, unknown>>; })
      .then((spec) => { const endpoints = endpointsFrom(spec); setState(endpoints.length ? { status: "ready", endpoints } : { status: "error" }); })
      .catch((error: unknown) => { if ((error as Error).name !== "AbortError") setState({ status: "error" }); });
    return () => controller.abort();
  }, []);
  if (state.status === "loading") return <p role="status" className="apidoc-note">Carregando a referência…</p>;
  if (state.status === "error") return <p role="alert" className="apidoc-note">Não foi possível carregar a referência agora. <a href={SPEC_URL} download="openapi-v1.json">Baixe o contrato OpenAPI</a> ou tente novamente em instantes.</p>;
  return <div className="apidoc-endpoints">{state.endpoints.map((endpoint) => <EndpointCard key={endpoint.id} endpoint={endpoint} />)}</div>;
}

export function DownloadSpec() {
  return <a className="apidoc-button" href={SPEC_URL} download="openapi-v1.json"><Download size={16} aria-hidden="true" />Baixar openapi-v1.json</a>;
}

const STATUS_LABELS: Record<string, string> = { "Successful Response": "Sucesso", "Validation Error": "Erro de validação" };

/** The contract text marks code with backticks; render them as <code> instead of showing the raw characters. */
function inlineCode(text: string) {
  return text.split("`").map((part, index) => index % 2 ? <code key={index}>{part}</code> : part);
}

function FieldTable({ title, fields }: { title: string; fields: Field[] }) {
  if (!fields.length) return null;
  return <div className="apidoc-table-wrap" tabIndex={0} role="region" aria-label={title}>
    <table><caption>{title}</caption><thead><tr><th scope="col">Campo</th><th scope="col">Tipo</th><th scope="col">Regras</th></tr></thead>
      <tbody>{fields.map((field) => <tr key={`${field.location}-${field.name}`}>
        <th scope="row"><code>{field.name}</code>{field.location && <span className="apidoc-tag">{field.location === "path" ? "caminho" : field.location}</span>}{field.required && <span className="apidoc-tag apidoc-required">obrigatório</span>}</th>
        <td><code>{field.type}</code></td><td>{field.constraints || "—"}</td></tr>)}</tbody></table>
  </div>;
}

function EndpointCard({ endpoint }: { endpoint: Endpoint }) {
  const [language, setLanguage] = useState<Language>("curl");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const sample = codeSample(endpoint, language);
  async function copy() {
    try { await navigator.clipboard.writeText(sample); setCopied(true); setCopyError(false); setTimeout(() => setCopied(false), 2000); }
    catch { setCopyError(true); }
  }
  const labelId = `${endpoint.id}-title`;
  return <article className="apidoc-endpoint" id={endpoint.id} aria-labelledby={labelId}>
    <header>
      <h3 id={labelId}><span className={`apidoc-method apidoc-${endpoint.method.toLowerCase()}`}>{endpoint.method}</span><code>{endpoint.path}</code></h3>
      <p className="apidoc-summary">{endpoint.summary}{endpoint.scope ? <> · escopo <code>{endpoint.scope}</code></> : <> · qualquer chave válida</>}</p>
    </header>
    {endpoint.description && <p>{inlineCode(endpoint.description.replace(/\s*Escopo: `[^`]+`\.?$/, ""))}</p>}
    <FieldTable title="Parâmetros" fields={endpoint.params} />
    <FieldTable title="Corpo da requisição (JSON)" fields={endpoint.body} />
    <div className="apidoc-table-wrap" tabIndex={0} role="region" aria-label="Respostas"><table><caption>Respostas</caption><thead><tr><th scope="col">Status</th><th scope="col">Significado</th></tr></thead>
      <tbody>{endpoint.responses.map((r) => <tr key={r.status}><th scope="row"><code>{r.status}</code></th><td>{STATUS_LABELS[r.description] ?? r.description}</td></tr>)}</tbody></table></div>
    <p className="apidoc-note-small">Falhas de autenticação, escopo e limite de uso (401, 403, 429, 503) valem para todas as rotas: veja <a href="#erros">Erros</a>.</p>
    <div className="apidoc-code">
      <div className="apidoc-code-bar">
        <div role="tablist" aria-label={`Linguagem do exemplo de ${endpoint.path}`}>
          {LANGUAGES.map((item) => <button key={item.id} type="button" role="tab" id={`${endpoint.id}-${item.id}`} aria-selected={language === item.id} aria-controls={`${endpoint.id}-panel`} tabIndex={language === item.id ? 0 : -1} onClick={() => setLanguage(item.id)}
            onKeyDown={(event) => { const i = LANGUAGES.findIndex((l) => l.id === language); const next = event.key === "ArrowRight" ? i + 1 : event.key === "ArrowLeft" ? i - 1 : null; if (next === null) return; event.preventDefault(); const target = LANGUAGES[(next + LANGUAGES.length) % LANGUAGES.length]; setLanguage(target.id); document.getElementById(`${endpoint.id}-${target.id}`)?.focus(); }}>{item.label}</button>)}
        </div>
        <button type="button" className="apidoc-copy" onClick={() => void copy()}>{copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}{copied ? "Copiado" : "Copiar"}<span className="sr-only"> exemplo {endpoint.method} {endpoint.path}</span></button>
      </div>
      <pre id={`${endpoint.id}-panel`} role="tabpanel" aria-labelledby={`${endpoint.id}-${language}`} tabIndex={0}><code>{sample}</code></pre>
      {copyError && <p role="alert" className="apidoc-copy-error">Não foi possível copiar; selecione o código manualmente.</p>}
    </div>
  </article>;
}
