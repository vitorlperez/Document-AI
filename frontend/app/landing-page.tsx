"use client";

import { useState } from "react";
import {
  ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown,
  FileText, Folder, FolderOpen, Layers3, Link2, Menu, Search,
  ShieldCheck, Sparkles,
} from "lucide-react";
import "./landing.css";
import { Brand } from "./brand";
import { ProviderLogo } from "./provider-logo";

type LandingPageProps = { onLogin: () => void; onSignUp: () => void };

const demoCases = [
  {
    label: "Entrega do projeto",
    scope: "Todas as ferramentas",
    question: "O que ficou definido para a primeira entrega?",
    answer: <>A primeira entrega reúne o <strong>diagnóstico de marca</strong> e a <strong>proposta de posicionamento</strong>. O alinhamento também confirmou a apresentação dos conceitos visuais nesta etapa.</>,
    sources: [["Escopo do projeto.pdf", "Google Drive"], ["Reunião de alinhamento", "Notion"]],
  },
  {
    label: "Só nesta pasta",
    scope: "Pasta · Projeto Aurora",
    question: "Qual é o prazo da apresentação?",
    answer: <>A apresentação dos conceitos visuais está prevista para <strong>18 de outubro</strong>, após a revisão do diagnóstico pela equipe.</>,
    sources: [["Cronograma Aurora.docx", "Google Drive"]],
  },
  {
    label: "Sem evidência",
    scope: "Pasta · Projeto Aurora",
    question: "Qual foi o orçamento aprovado para mídia?",
    answer: <>Não encontrei evidência suficiente nos documentos desta pasta para confirmar um orçamento de mídia. Confira a fonte original ou amplie o contexto da consulta.</>,
    sources: [],
  },
];

function ProductPreview() {
  const [activeCase, setActiveCase] = useState(0);
  const demo = demoCases[activeCase];
  return (
    <figure className="landing-preview" aria-labelledby="landing-preview-caption">
      <div className="landing-demo-guide">
        <div><span className="landing-demo-kicker">VEJA NA PRÁTICA</span><h2>Uma pergunta. <em>Uma resposta com origem.</em></h2></div>
        <div className="landing-demo-options" role="group" aria-label="Escolha um exemplo da demonstração">{demoCases.map((item, index) => <button key={item.label} type="button" className={index === activeCase ? "is-active" : ""} aria-pressed={index === activeCase} onClick={() => setActiveCase(index)}>{item.label}</button>)}</div>
      </div>
      <div className="landing-preview-top"><span><Layers3 size={17} aria-hidden="true" /> arquivio. <span className="landing-preview-organization">/ Estúdio Aurora</span></span><span className="landing-preview-label">Prévia ilustrativa</span></div>
      <div className="landing-product">
        <aside className="landing-product-sources" aria-label="Biblioteca ilustrativa">
          <div className="landing-product-sidebar-heading"><div><strong>Biblioteca</strong><span>Arquivos e pastas sincronizados</span></div></div>
          <div className="landing-product-breadcrumb">Biblioteca</div>
          <div className="landing-product-source"><ProviderLogo provider="google" size={22} className="landing-provider-logo" /> Google Drive</div>
          <div className="landing-product-folder"><Folder size={14} aria-hidden="true" /> Projeto Aurora</div>
          <div className="landing-product-source"><ProviderLogo provider="notion" size={22} className="landing-provider-logo" /> Notion</div>
          <div className="landing-product-source"><ProviderLogo provider="onedrive" size={22} className="landing-provider-logo" /> OneDrive</div>
        </aside>
        <section className="landing-product-chat" aria-label="Conversa demonstrativa" aria-live="polite" key={activeCase}>
          <div className="landing-product-context"><div><strong>Consultar em</strong><span>{demo.scope}</span></div></div>
          <div className="landing-product-thread" aria-label={`Pergunta e resposta do exemplo: ${demo.label}`}>
            <div className="landing-product-question-wrap"><p className="landing-product-question">{demo.question}</p></div>
            <div className="landing-product-answer"><span className="landing-product-avatar"><Sparkles size={16} aria-hidden="true" /></span><div><p className="landing-product-answer-name">Arquivio</p><p>{demo.answer}</p>
              <div className="landing-product-references" aria-label="Documentos utilizados"><strong>DOCUMENTOS UTILIZADOS</strong>{demo.sources.length > 0 ? demo.sources.map(([name, provider], index) => <div key={name}><span>{index + 1}</span><FileText size={13} aria-hidden="true" /> {name} <small>{provider}</small></div>) : <p className="landing-no-sources">Nenhum documento sustenta esta resposta.</p>}</div>
            </div></div>
          </div>
          <div className="landing-product-composer" aria-hidden="true"><span>O que você gostaria de saber?</span><span className="landing-product-send"><ArrowRight size={14} /></span></div>
        </section>
        <aside className="landing-product-library" aria-label="Busca de arquivos ilustrativa"><div className="landing-product-library-heading">Buscar arquivos</div><p>Encontre arquivos e pastas pelo nome.</p><div className="landing-product-library-search"><span>Nome do arquivo ou pasta</span><Search size={14} aria-hidden="true" /></div><div className="landing-product-document"><FileText size={16} aria-hidden="true" /><div><p>Escopo do projeto.pdf</p><span>Google Drive</span></div></div><div className="landing-product-document"><FileText size={16} aria-hidden="true" /><div><p>Cronograma Aurora.docx</p><span>Google Drive</span></div></div></aside>
      </div>
      <figcaption id="landing-preview-caption">A resposta muda com o contexto e as evidências disponíveis. <span>Exemplos fictícios.</span></figcaption>
    </figure>
  );
}

const questions = [
  ["O Arquivio substitui minhas ferramentas?", "Não. Seus arquivos e páginas originais continuam no Google Drive, OneDrive ou Notion. O Arquivio usa conexões de leitura para criar uma base de consulta com o conteúdo selecionado, sem editar os originais."],
  ["Que conteúdo posso consultar?", "Documentos Google, PDFs com texto, arquivos DOCX, páginas do Notion e Markdown dentro do escopo conectado. Imagens escaneadas, planilhas e apresentações não são indexadas nesta versão. Não há upload direto de arquivos."],
  ["Quem pode acessar o conteúdo conectado?", "Todos os membros da sua organização no Arquivio podem consultar o conteúdo sincronizado. As permissões individuais das ferramentas não são reproduzidas. Conecte somente materiais que possam ser compartilhados com toda a equipe; áreas restritas de RH ou financeiro não são adequadas."],
  ["E se não houver informação suficiente para responder?", "O Arquivio indica que não encontrou evidência suficiente no contexto selecionado. As respostas são geradas por IA e devem ser conferidas na lista de documentos utilizados e nos originais antes de embasar uma decisão."],
  ["Os documentos ficam disponíveis imediatamente?", "A sincronização e a extração de texto acontecem em segundo plano. Você pode acompanhar o estado de processamento e as falhas por documento. Alterações nos arquivos precisam passar por uma nova sincronização para aparecer nas consultas."],
  ["Como o conteúdo é usado pela IA?", "O conteúdo extraído necessário para busca e resposta é processado pelo provedor de IA configurado. Os originais permanecem nas ferramentas conectadas. Antes de conectar uma fonte, confirme que esse uso é adequado às políticas da sua organização."],
];

export function LandingPage({ onLogin, onSignUp }: LandingPageProps) {
  return (
    <div className="landing-page">
      <a className="landing-skip-link" href="#landing-main">Pular para o conteúdo</a>
      <header className="landing-header landing-container">
        <a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, início"><Brand /></a>
        <nav className="landing-desktop-nav" aria-label="Navegação principal"><a href="#demonstracao">Demonstração</a><a href="#como-funciona">Como funciona</a><a href="#perguntas">Dúvidas</a></nav>
        <div className="landing-header-actions"><button className="landing-login" onClick={onLogin}>Entrar</button><button className="landing-button landing-button-small" onClick={onSignUp}>Criar conta <ArrowUpRight size={16} aria-hidden="true" /></button></div>
        <details className="landing-mobile-menu"><summary aria-label="Abrir navegação"><Menu size={23} aria-hidden="true" /></summary><nav aria-label="Navegação móvel"><a href="#demonstracao">Demonstração</a><a href="#como-funciona">Como funciona</a><a href="#perguntas">Dúvidas</a><button onClick={onLogin}>Entrar na minha conta</button><button className="landing-mobile-signup" onClick={onSignUp}>Criar conta</button></nav></details>
      </header>

      <main id="landing-main">
        <section className="landing-hero landing-container" aria-labelledby="landing-hero-title">
          <p className="landing-eyebrow"><span className="landing-status-dot" /> SEU CONHECIMENTO, COM CONTEXTO</p>
          <h1 id="landing-hero-title">A resposta está nos arquivos.<br /><em>Agora você sabe onde.</em></h1>
          <p className="landing-hero-description">Briefings, decisões e escopos no Google Drive, OneDrive e Notion. Pergunte ao Arquivio e confira os documentos por trás da resposta.</p>
          <div className="landing-hero-actions"><button className="landing-button" onClick={onSignUp}>Começar com o Arquivio <ArrowRight size={19} aria-hidden="true" /></button><a className="landing-text-link" href="#demonstracao">Testar a demonstração <ArrowDown size={16} aria-hidden="true" /></a></div>
          <p className="landing-hero-note"><Check size={14} aria-hidden="true" /> Conexões de leitura · originais preservados</p>
          <div id="demonstracao"><ProductPreview /></div>
        </section>

        <section className="landing-benefits landing-container" aria-labelledby="landing-benefits-title">
          <div className="landing-section-intro"><p className="landing-eyebrow">O ESSENCIAL</p><h2 id="landing-benefits-title">Menos procura.<br /><em>Mais contexto.</em></h2></div>
          <div className="landing-benefit-grid">
            <article><span className="landing-feature-icon"><Sparkles size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>Pergunte naturalmente</h3><p>Retome o que foi documentado sem procurar em arquivo por arquivo.</p></article>
            <article><span className="landing-feature-icon"><Link2 size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>Confira a origem</h3><p>Veja os documentos utilizados e abra os originais para conferir detalhes.</p></article>
            <article><span className="landing-feature-icon"><FolderOpen size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>Escolha o contexto</h3><p>Consulte toda a organização, uma ferramenta ou uma pasta específica.</p></article>
          </div>
        </section>

        <section className="landing-workflow" id="como-funciona" aria-labelledby="landing-workflow-title"><div className="landing-container">
          <div className="landing-workflow-heading"><div><p className="landing-eyebrow">COMO FUNCIONA</p><h2 id="landing-workflow-title">Dos documentos <em>à resposta.</em></h2></div></div>
          <ol className="landing-steps">
            <li><span className="landing-step-number">01</span><h3>Conecte</h3><p>Escolha o conteúdo compartilhável no Google Drive, OneDrive ou Notion.</p></li>
            <li><span className="landing-step-number">02</span><h3>Prepare</h3><p>Acompanhe a sincronização e o processamento dos documentos.</p></li>
            <li><span className="landing-step-number">03</span><h3>Pergunte</h3><p>Defina o escopo, receba a resposta e confira as fontes.</p></li>
          </ol>
          <div className="landing-permission-note"><ShieldCheck size={21} aria-hidden="true" /><p>Todos na organização podem consultar o conteúdo sincronizado. Selecione apenas materiais compartilháveis com a equipe.</p></div>
        </div></section>

        <section className="landing-audiences landing-container" id="para-equipes" aria-labelledby="landing-audiences-title"><div className="landing-section-intro"><p className="landing-eyebrow">NO DIA A DIA</p><h2 id="landing-audiences-title">De uma dúvida solta<br /><em>à próxima decisão.</em></h2><p>Um ponto de partida para equipes que trabalham com informação espalhada entre projetos.</p></div><div className="landing-audience-list"><article><span className="landing-audience-index">01 /</span><div><h3>Projetos e atendimento</h3><p>Retome escopos, prazos e decisões registradas.</p></div><blockquote>“O que ficou combinado na última reunião?”</blockquote><ArrowUpRight size={23} aria-hidden="true" /></article><article><span className="landing-audience-index">02 /</span><div><h3>Consultoria e operações</h3><p>Localize recomendações e responsabilidades nos documentos.</p></div><blockquote>“Qual é o próximo passo deste projeto?”</blockquote><ArrowUpRight size={23} aria-hidden="true" /></article></div><p className="landing-audience-note">Perguntas ilustrativas. As respostas dependem dos documentos conectados.</p></section>

        <section className="landing-faq landing-container" id="perguntas" aria-labelledby="landing-faq-title"><div><p className="landing-eyebrow">ANTES DE COMEÇAR</p><h2 id="landing-faq-title">Perguntas<br /><em>frequentes.</em></h2></div><div className="landing-faq-list">{questions.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={19} aria-hidden="true" /></summary><p>{answer}</p></details>)}</div></section>

        <section className="landing-closing landing-container" aria-labelledby="landing-closing-title"><p className="landing-eyebrow">PRONTO PARA ENCONTRAR?</p><h2 id="landing-closing-title">O que sua equipe sabe<br /><em>está mais perto do que parece.</em></h2><button className="landing-button" onClick={onSignUp}>Criar minha conta <ArrowRight size={19} aria-hidden="true" /></button><p>Já tem um espaço de trabalho? <button className="landing-inline-button" onClick={onLogin}>Entrar no Arquivio</button></p></section>
      </main>

      <footer className="landing-footer landing-container"><a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, voltar ao início"><Brand /></a><p>Conhecimento que encontra o seu contexto.</p><a href="#perguntas">Sobre acesso e privacidade <ArrowUpRight size={14} aria-hidden="true" /></a></footer>
    </div>
  );
}
