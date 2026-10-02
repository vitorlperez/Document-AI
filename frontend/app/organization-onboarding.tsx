"use client";

import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight, HardDrive, ShieldCheck, Sparkles } from "lucide-react";
import { ReactNode, useEffect, useRef, useState } from "react";
import { Brand } from "./brand";
import { ProviderMark } from "./product/types-and-api";
import { ToolSyncBadge, useSyncStatus } from "./sync-status";
import { errorMessage, isActive, onboardingSyncPresentation, progressView, stageIndex, stageLabel, summarize, type ToolSyncState } from "./sync-status-logic";
import { providerLabel } from "./provider-labels";
import "./onboarding.css";

export type OnboardingState = {
  step: "welcome" | "integrations" | "sync" | "complete";
  required: boolean;
  tour_required: boolean;
};

export function OrganizationOnboarding({ organizationId, name, state, onAdvance, children, alert, onLogout }: {
  organizationId: string;
  name: string;
  state: OnboardingState;
  onAdvance: (step: OnboardingState["step"]) => Promise<void>;
  children: ReactNode;
  alert: ReactNode;
  onLogout: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const integrations = state.step === "integrations";
  const syncing = state.step === "sync";
  const status = useSyncStatus(organizationId, { enabled: syncing });
  const summary = summarize(status.tools);
  const syncView = onboardingSyncPresentation(summary);
  const checking = status.loading && status.tools.length === 0;
  useEffect(() => { title.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: "instant" }); }, [state.step]);
  async function advance(step: OnboardingState["step"]) {
    setBusy(true); setError(null);
    try { await onAdvance(step); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Não foi possível salvar seu progresso. Tente novamente."); }
    finally { setBusy(false); }
  }
  return <main className="onboarding-page">
    <header className="onboarding-header"><Brand /><button onClick={onLogout} className="onboarding-text-button">Sair</button></header>
    {alert}
    <section className={`onboarding-content ${integrations ? "onboarding-integrations" : syncing ? `onboarding-sync ${syncView.action === "connect" ? "onboarding-sync-connect" : ""}` : ""}`} aria-busy={busy}>
      <ol className="onboarding-progress" aria-label="Etapas de preparação">
        <li aria-current={!integrations && !syncing ? "step" : undefined}><span>1</span>Boas-vindas</li>
        <li aria-current={integrations ? "step" : undefined}><span>2</span>Conectar conhecimento</li>
        <li aria-current={syncing ? "step" : undefined}><span>3</span>Preparar sua base</li>
      </ol>
      <div className="onboarding-intro">
        <span className="onboarding-eyebrow">{name}</span>
        <h1 ref={title} tabIndex={-1}>{syncing ? (checking ? "Verificando sua base" : syncView.title) : integrations ? "Traga o conhecimento da sua equipe" : "Boas-vindas ao Arquivio"}</h1>
        <p>{syncing ? (checking ? "Buscando o andamento das suas ferramentas…" : syncView.description) : integrations ? "Conecte uma ferramenta, escolha o que compartilhar e inicie a sincronização. Você pode continuar enquanto os documentos são preparados." : "Transforme os documentos da sua equipe em respostas com fontes. Vamos preparar seu espaço em três passos rápidos."}</p>
      </div>
      {syncing ? <SyncProgress tools={status.tools} loading={status.loading} error={status.error} onRetry={status.refresh} onBack={() => { void advance("integrations"); }} /> : integrations ? <>
        <p className="onboarding-hint"><ShieldCheck size={18} aria-hidden="true" />Escolha apenas conteúdo que todas as pessoas da organização podem acessar. Os originais permanecem na ferramenta conectada.</p>
        {children}
        <p className="onboarding-hint">Sem documentos agora? Você pode conectar fontes depois em Navegar → Integrações. As respostas ficam disponíveis conforme a indexação termina.</p>
      </> : <div className="onboarding-benefits">
        <article><HardDrive aria-hidden="true" /><h2>Conecte suas fontes</h2><p>Google Drive, OneDrive, SharePoint e Notion, com o escopo que você escolher.</p></article>
        <article><Sparkles aria-hidden="true" /><h2>Pergunte à sua base</h2><p>Encontre decisões, prazos e informações nos documentos já indexados.</p></article>
        <article><ShieldCheck aria-hidden="true" /><h2>Confira as evidências</h2><p>Abra as fontes citadas e verifique o contexto de cada resposta.</p></article>
      </div>}
      {error && <p role="alert" className="onboarding-error">{error}</p>}
      <footer className="onboarding-actions">
        {(integrations || (syncing && syncView.action !== "connect")) && <button disabled={busy} onClick={() => { void advance(syncing ? "integrations" : "welcome"); }} className="onboarding-text-button"><ArrowLeft size={16} aria-hidden="true" />{syncing ? syncView.backLabel : "Voltar"}</button>}
        {!syncing && <button disabled={busy} onClick={() => { void advance("complete"); }} className="onboarding-text-button">{integrations ? "Conectar depois" : "Pular introdução"}</button>}
        {syncing ? <button disabled={busy || checking} onClick={() => { void advance(syncView.action === "connect" ? "integrations" : "complete"); }} className={syncView.action === "background" ? "onboarding-primary onboarding-primary-quiet" : "onboarding-primary"}>{busy ? "Salvando…" : checking ? "Verificando…" : syncView.cta}<ChevronRight size={18} aria-hidden="true" /></button>
          : <button disabled={busy} onClick={() => { void advance(integrations ? "complete" : "integrations"); }} className="onboarding-primary">{busy ? "Salvando…" : integrations ? "Ir para a conversa" : "Vamos começar"}<ChevronRight size={18} aria-hidden="true" /></button>}
      </footer>
    </section>
  </main>;
}

const STEPS = ["Lendo arquivos", "Preparando para o chat"];

function SyncRow({ tool, onBack }: { tool: ToolSyncState; onBack: () => void }) {
  const active = isActive(tool); const view = progressView(tool); const pct = view.percent; const index = stageIndex(tool); const issue = errorMessage(tool);
  return <li className="sync-row" data-state={tool.state}>
    <span className="sync-row-logo"><ProviderMark provider={tool.provider} /></span>
    <div className="sync-row-body">
      <div className="sync-row-head"><b>{providerLabel(tool.provider)}</b><ToolSyncBadge tool={tool} short /></div>
      {active && <><div className={`sync-track ${pct === null ? "sync-track-indeterminate" : ""}`} role="progressbar" aria-label={`Progresso de ${providerLabel(tool.provider)}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined} aria-valuetext={view.speech}><span style={pct === null ? undefined : { width: `${pct}%` }} /></div>
      <p className="sync-row-progress">{view.text}</p>
      <ol className="sync-steps" aria-hidden="true">{STEPS.map((label, i) => <li key={label} data-done={i < index || undefined} data-current={i === index || undefined}>{label}</li>)}</ol></>}
      {!active && <p className="sync-row-result">{stageLabel(tool)}</p>}
      {issue && <><p className="sync-row-issue">{issue}</p><button type="button" onClick={onBack} className="onboarding-text-button sync-row-action" aria-label={`Revisar conexão de ${providerLabel(tool.provider)}`}>Revisar conexão</button></>}
    </div>
  </li>;
}

function SyncProgress({ tools, loading, error, onRetry, onBack }: { tools: ToolSyncState[]; loading: boolean; error: string | null; onRetry: () => void; onBack: () => void }) {
  const summary = summarize(tools);
  const view = onboardingSyncPresentation(summary);
  const checking = loading && tools.length === 0;
  return <section className="sync-panel" aria-label="Andamento da sincronização" data-sync-state={checking ? "loading" : summary.state}>
    <p className="sync-callout" data-tone={view.tone} role="status" aria-live="polite">{view.tone === "warning" ? <AlertTriangle size={20} aria-hidden="true" /> : view.tone === "success" ? <CheckCircle2 size={20} aria-hidden="true" /> : <ShieldCheck size={20} aria-hidden="true" />}{checking ? "Verificando o andamento…" : view.callout}</p>
    {!checking && tools.length > 0 && <ul className="sync-list">{tools.map((tool) => <SyncRow key={tool.sourceId} tool={tool} onBack={onBack} />)}</ul>}
    {error && <p className="onboarding-error" role="alert">{error} <button type="button" onClick={onRetry} className="onboarding-link">Tentar novamente</button></p>}
  </section>;
}
