"use client";

import { useRef } from "react";
import { ArrowRight, Check, ShieldCheck } from "lucide-react";
import "./landing.css";
import { landingCtaMode } from "./landing-session.mjs";
import { PLANS, TRIAL_CTA, TRIAL_DAYS, businessQuote, formatBRL } from "./landing-plans.mjs";
import { FaqSection, LandingFooter, LandingHeader, PricingSection, SalesLink, useSectionReveal, type LandingActions, type LandingSession } from "./landing-shared";

const NAV = [
  { href: "#controle", label: "Controle" }, { href: "#como-comeca", label: "Como começa" }, { href: "#precos", label: "Preços" },
  { href: "#perguntas", label: "Dúvidas" },
];

const control = [
  ["Funções claras", "Owner, Admin e Membro. Só Owner/Admin conectam fontes e convidam pessoas."],
  ["Convites por link", "O time entra pelo convite e já consulta o acervo."],
  ["Escopo por pergunta", "Busque em tudo ou restrinja a uma ferramenta ou pasta."],
  ["Aviso honesto", "Sem evidência suficiente, a resposta diz isso."],
] as const;

const steps = [
  ["Comece o teste da empresa", "Crie a conta e dê um nome à sua empresa."],
  ["Conecte as fontes", "Owner ou Admin conecta Drive, OneDrive, Notion, SharePoint ou ClickUp, em leitura."],
  ["Convide o time", "Envie convites e defina quem é Admin e quem é Membro."],
  ["Pergunte com contexto", "Cada resposta mostra de qual documento veio."],
] as const;

const questions = [
  ["Como funciona o preço da empresa?", "Um valor base mensal com as primeiras pessoas incluídas (5 no Team, 20 no Scale) e um valor por pessoa extra, até o limite de cada plano. Você adiciona ou remove pessoas quando quiser."],
  ["Existe plano grátis?", `Não. Você testa por ${TRIAL_DAYS} dias, sem cartão. Depois, assina um plano para continuar adicionando arquivos e perguntando.`],
  ["O que acontece quando o teste acaba?", "A conta fica em modo de leitura: seu time continua entrando, vendo e baixando documentos, mas não adiciona arquivos, não convida pessoas e não faz novas perguntas até assinar. Nada é apagado."],
  ["Quem pode conectar as fontes?", "Somente Owner e Admin. Todos os membros consultam o que foi sincronizado."],
  ["Todos os membros veem tudo o que foi conectado?", "Todos os membros da organização podem consultar o conteúdo sincronizado, e o Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe."],
  ["O Arquivio altera meus arquivos?", "Não. Os originais continuam no Google Drive, OneDrive, Notion, SharePoint ou ClickUp. As conexões são de leitura."],
  ["Onde ficam os dados e como a IA os usa?", "Os arquivos originais ficam nas suas ferramentas. O texto necessário para busca e resposta é processado pelo provedor de IA configurado; confira se esse uso atende às políticas da sua organização. Detalhes na Política de Privacidade."],
  ["Posso migrar de uma conta pessoal?", "Sim. Uma conta pessoal pode virar conta de empresa quando você precisar convidar outras pessoas; documentos e fontes conectadas ficam onde estão."],
  ["Posso falar com alguém antes de contratar?", "Sim, use Falar com vendas."],
];

export function BusinessLandingPage({ onLogin, onSignUp, onOpenApp = onLogin, onLogout = () => undefined, session = { status: "anonymous" } }: LandingActions & { session?: LandingSession }) {
  const mode = landingCtaMode(session);
  const signedIn = session.status === "authenticated" ? session : null;
  const pageRef = useRef<HTMLDivElement>(null);
  useSectionReveal(pageRef);
  const team = PLANS.find((plan) => plan.key === "business_team")!;
  const quote = businessQuote(team, 8)!;
  const cta = (className = "landing-button") => mode === "anonymous" ? <button className={className} onClick={() => onSignUp({ tipo: "empresa" })}>{TRIAL_CTA} <ArrowRight size={18} /></button>
    : signedIn ? <button className={className} onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button>
    : <span className="landing-session-placeholder landing-session-placeholder-hero" aria-hidden="true" />;
  return (
    <div className="landing-page" ref={pageRef}>
      <a className="landing-skip-link" href="#landing-main">Pular para o conteúdo</a>
      <LandingHeader current="empresa" session={session} nav={NAV} intent={{ tipo: "empresa" }} homeHref="#landing-main" onLogin={onLogin} onSignUp={onSignUp} onOpenApp={onOpenApp} onLogout={onLogout} />

      <main id="landing-main">
        <div className="landing-biz-hero landing-container">
          <section aria-labelledby="landing-biz-title">
            <p className="landing-eyebrow"><span className="landing-status-dot" /> ARQUIVIO PARA EMPRESAS</p>
            <h1 id="landing-biz-title">O conhecimento do time, <em>em uma só pergunta.</em></h1>
            <p className="landing-hero-description">Conecte Drive, OneDrive, Notion, SharePoint e ClickUp. Seu time pergunta, o Arquivio responde e mostra de qual documento veio.</p>
            <div className="landing-hero-actions" data-session={mode}>{cta()}<SalesLink /></div>
            <ul className="landing-biz-checks" aria-label="Destaques">
              <li><Check size={14} aria-hidden="true" />{TRIAL_DAYS} dias, sem cartão</li><li><Check size={14} aria-hidden="true" />Somente leitura nas suas fontes</li><li><Check size={14} aria-hidden="true" />Você define quem entra</li><li><Check size={14} aria-hidden="true" />Fonte em toda resposta</li>
            </ul>
          </section>
          <aside className="landing-biz-card" aria-label="Como o preço funciona">
            <p className="landing-eyebrow">PREÇO BASE + PESSOA EXTRA</p>
            <strong>{team.seatsIncluded} pessoas incluídas no {team.name}</strong>
            <p>Um valor base com pessoas incluídas e um valor por pessoa extra. O limite de perguntas é da empresa toda, não de cada pessoa.</p>
            <p className="landing-biz-card-math">Time de 8 pessoas: {formatBRL(quote.base)} + {quote.extras} × {formatBRL(quote.extra)} = <b>{formatBRL(quote.total)}/mês</b></p>
          </aside>
        </div>

        <section className="landing-usecases landing-container" aria-labelledby="landing-biz-problem-title" data-reveal>
          <div className="landing-usecases-intro"><p className="landing-eyebrow">O PROBLEMA</p><h2 id="landing-biz-problem-title">Ninguém sabe onde está.<br /><em>Todo mundo pergunta no chat.</em></h2></div>
          <p className="landing-biz-lede">Política num PDF, decisão no Notion, proposta no Drive. Cada pergunta vira uma busca em cinco lugares ou um colega interrompido.</p>
        </section>

        <section id="controle" className="landing-trust landing-container" aria-labelledby="landing-biz-control-title" data-reveal>
          <div><p className="landing-eyebrow">VOCÊ NO CONTROLE</p><h2 id="landing-biz-control-title">Quem entra,<br /><em>o que está conectado.</em></h2></div>
          <ul>{control.map(([title, text]) => <li key={title}><strong>{title}.</strong><span>{text}</span></li>)}</ul>
        </section>

        <section className="landing-process landing-process-slim" aria-label="Atenção à permissão"><div className="landing-container" data-reveal>
          <p className="landing-process-note"><ShieldCheck size={18} aria-hidden="true" /> Todos os membros consultam o que foi sincronizado. Conecte materiais compartilháveis com a equipe.</p>
        </div></section>

        <section id="como-comeca" className="landing-process" aria-labelledby="landing-biz-steps-title"><div className="landing-container" data-reveal>
          <div className="landing-process-heading"><p className="landing-eyebrow">COMO O TIME COMEÇA</p><h2 id="landing-biz-steps-title">Em quatro passos,<br /><em>todo mundo perguntando.</em></h2></div>
          <ol className="landing-process-grid landing-process-grid-4">{steps.map(([title, text], index) => <li key={title}><article><span>{String(index + 1).padStart(2, "0")}</span><h3>{title}</h3><p>{text}</p></article></li>)}</ol>
        </div></section>

        <PricingSection kinds={["empresa"]} mode={mode} onSignUp={onSignUp} onOpenApp={onOpenApp} title={<>Planos para empresas.<br /><em>Comece com {TRIAL_DAYS} dias de teste.</em></>} subtitle={`Valor base com pessoas incluídas e um valor por pessoa extra. Teste grátis de ${TRIAL_DAYS} dias, sem cartão.`} />

        <FaqSection questions={questions} eyebrow="COMPRAS E SEGURANÇA" />

        <section className="landing-closing landing-container" aria-labelledby="landing-closing-title" data-reveal>
          <p className="landing-eyebrow">COMECE PELA SUA EMPRESA</p>
          <h2 id="landing-closing-title">Seu time já tem as respostas.<br /><em>Falta achá-las.</em></h2>
          <div className="landing-closing-actions">{cta()}{mode !== "loading" && <SalesLink className="landing-button" />}</div>
        </section>
      </main>

      <LandingFooter homeHref="#landing-main" links={[{ href: "/", label: "Para você" }, { href: "#precos", label: "Preços" }]} />
    </div>
  );
}
