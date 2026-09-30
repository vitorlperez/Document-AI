"use client";

import { ArrowLeft, ChevronRight, HardDrive, ShieldCheck, Sparkles } from "lucide-react";
import { ReactNode, useEffect, useRef, useState } from "react";
import { Brand } from "./brand";
import "./onboarding.css";

export type OnboardingState = {
  step: "welcome" | "integrations" | "complete";
  required: boolean;
  tour_required: boolean;
};

export function OrganizationOnboarding({ name, state, onAdvance, children, alert, onLogout }: {
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
  useEffect(() => { title.current?.focus(); }, [state.step]);
  async function advance(step: OnboardingState["step"]) {
    setBusy(true); setError(null);
    try { await onAdvance(step); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Não foi possível salvar seu progresso. Tente novamente."); }
    finally { setBusy(false); }
  }
  return <main className="onboarding-page">
    <header className="onboarding-header"><Brand /><button onClick={onLogout} className="onboarding-text-button">Sair</button></header>
    {alert}
    <section className={`onboarding-content ${integrations ? "onboarding-integrations" : ""}`} aria-busy={busy}>
      <ol className="onboarding-progress" aria-label="Etapas de preparação">
        <li aria-current={!integrations ? "step" : undefined}><span>1</span>Boas-vindas</li>
        <li aria-current={integrations ? "step" : undefined}><span>2</span>Conectar conhecimento</li>
      </ol>
      <div className="onboarding-intro">
        <span className="onboarding-eyebrow">{name}</span>
        <h1 ref={title} tabIndex={-1}>{integrations ? "Traga o conhecimento da sua equipe" : "Boas-vindas ao Arquivio"}</h1>
        <p>{integrations ? "Conecte uma ferramenta, escolha o que compartilhar e inicie a sincronização. Você pode continuar enquanto os documentos são preparados." : "Transforme os documentos da sua equipe em respostas com fontes. Vamos preparar seu espaço em dois passos rápidos."}</p>
      </div>
      {integrations ? <>
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
        {integrations && <button disabled={busy} onClick={() => { void advance("welcome"); }} className="onboarding-text-button"><ArrowLeft size={16} aria-hidden="true" />Voltar</button>}
        <button disabled={busy} onClick={() => { void advance("complete"); }} className="onboarding-text-button">{integrations ? "Conectar depois" : "Pular introdução"}</button>
        <button disabled={busy} onClick={() => { void advance(integrations ? "complete" : "integrations"); }} className="onboarding-primary">{busy ? "Salvando…" : integrations ? "Ir para a conversa" : "Vamos começar"}<ChevronRight size={18} aria-hidden="true" /></button>
      </footer>
    </section>
  </main>;
}
