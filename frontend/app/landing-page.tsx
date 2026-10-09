"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import {
  ArrowRight, ArrowUpRight, Check, ChevronDown, ChevronRight,
  FileText, Folder, Menu, PanelRightClose, Plus, Search, Send, ShieldCheck, Sparkles,
} from "lucide-react";
import "./landing.css";
import { Brand } from "./brand";
import { ThemeToggle } from "./theme-toggle";
import { ProviderLogo } from "./provider-logo";

type LandingPageProps = { onLogin: () => void; onSignUp: () => void };

/** Optional decorative art for the Rotina section, delivered separately; the layout never depends on it. */
const STORY_ART_SRC = "/landing/document-context.webp";

const demoCases = [
  {
    label: "Resposta com fontes",
    scope: "Todas as ferramentas",
    question: "O que ficou definido para a primeira entrega?",
    mentions: "",
    answer: <>A primeira entrega inclui o <strong>diagnóstico de marca</strong> e a <strong>proposta de posicionamento</strong>.</>,
    sources: [["Escopo do projeto.pdf", "Google Drive"], ["Reunião de alinhamento", "Notion"], ["Cronograma de entregas", "OneDrive"]],
    extra: 2,
  },
  {
    label: "Com menção @",
    scope: "Google Drive",
    question: "Quais são os prazos previstos neste documento?",
    mentions: "Arquivo: Escopo do projeto.pdf",
    answer: <>O documento prevê o <strong>diagnóstico de marca</strong> na primeira etapa e a <strong>proposta de posicionamento</strong> na etapa seguinte.</>,
    sources: [["Escopo do projeto.pdf", "Google Drive"]],
    extra: 0,
  },
  {
    label: "Sem evidência suficiente",
    scope: "Notion",
    question: "Qual foi o orçamento aprovado para mídia?",
    mentions: "",
    answer: <>Não encontrei evidência nos documentos selecionados para confirmar o orçamento de mídia.</>,
    sources: [],
    extra: 0,
  },
];

function ProductPreview() {
  const [activeCase, setActiveCase] = useState(0);
  const demo = demoCases[activeCase];
  return (
    <figure className="landing-preview" aria-labelledby="landing-preview-caption">
      <div className="landing-preview-heading">
        <p className="landing-eyebrow">VEJA A EXPERIÊNCIA</p>
        <h2>Converse com seus documentos.<br /><em>Confira a origem.</em></h2>
      </div>
      <div className="landing-demo-options" role="group" aria-label="Escolha um exemplo da demonstração">
        {demoCases.map((item, index) => <button key={item.label} type="button" aria-pressed={activeCase === index} onClick={() => setActiveCase(index)}>{item.label}</button>)}
      </div>

      <div className="landing-app-shell">
        <div className="landing-app-bar">
          <Brand compact />
          <span className="landing-app-company">Estúdio Aurora <ChevronDown size={12} aria-hidden="true" /></span>
          <span className="landing-preview-label">Prévia ilustrativa</span>
        </div>

        <div className="landing-app-workspace">
          <section className="landing-app-chat" aria-label="Exemplo de conversa com documentos">
            <div className="landing-app-toolbar" aria-hidden="true"><span><Plus size={13} />Nova conversa</span><PanelRightClose size={16} /></div>
            <div className="landing-app-thread" aria-live="polite" key={activeCase}>
              <div className="landing-user-message">
                <small>{demo.scope}</small>
                <p>{demo.question}{demo.mentions && <span className="landing-mention-line">{demo.mentions}</span>}</p>
              </div>
              <article className="landing-answer">
                <div className="landing-answer-author"><span><Sparkles size={15} /></span><div><strong>Arquivio</strong><small>{demo.scope}</small></div></div>
                <p>{demo.answer}</p>
                {demo.sources.length > 0 && <div className="landing-answer-sources" aria-label="Documentos utilizados">
                  <strong>Documentos utilizados</strong>
                  {demo.sources.map(([name, provider], index) => <div key={name}><span>{index + 1}.</span><FileText size={14} /><b>{name}</b><small>{provider}</small></div>)}
                  {demo.extra > 0 && <p className="landing-sources-more">Ver mais {demo.extra} documentos <ChevronDown size={13} aria-hidden="true" /></p>}
                </div>}
              </article>
            </div>
            <div className="landing-composer" aria-hidden="true">
              <span className="landing-composer-input">O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta</span>
              <span className="landing-composer-actions">
                <span className="landing-scope-trigger">{demo.scope}<ChevronDown size={12} /></span>
                <span className="landing-composer-send"><small>0/1000</small><span className="landing-send"><Send size={13} />Enviar</span></span>
              </span>
            </div>
            <p className="landing-composer-hint">Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.</p>
          </section>

          <aside className="landing-app-sources" aria-label="Biblioteca ilustrativa">
            <div className="landing-panel-title"><strong>Biblioteca</strong><span>Arquivos sincronizados</span></div>
            <div className="landing-app-breadcrumb">Biblioteca</div>
            <div className="landing-source-list">
              <div className="landing-source-row"><ProviderLogo provider="google" size={20} /> <span>Google Drive</span><ChevronRight size={13} /></div>
              <div className="landing-folder-row"><Folder size={14} aria-hidden="true" /><span>Projeto Aurora</span></div>
              <div className="landing-source-row"><ProviderLogo provider="notion" size={20} /> <span>Notion</span><ChevronRight size={13} /></div>
              <div className="landing-source-row"><ProviderLogo provider="onedrive" size={20} /> <span>OneDrive</span><ChevronRight size={13} /></div>
              <div className="landing-source-row"><ProviderLogo provider="sharepoint" size={20} /> <span>SharePoint</span><ChevronRight size={13} /></div>
            </div>
            <p className="landing-scope-note"><ShieldCheck size={14} />A conversa usa somente as ferramentas e menções selecionadas na mensagem.</p>
          </aside>

          <aside className="landing-app-search" aria-label="Busca de arquivos ilustrativa">
            <div className="landing-search-copy">
              <strong>Buscar arquivos</strong>
              <p>Encontre arquivos e pastas pelo nome em todas as fontes conectadas.</p>
            </div>
            <div className="landing-search-controls"><span className="landing-search-field">Nome de arquivo ou pasta</span><span className="landing-search-button"><Search size={14} /></span></div>
            <small>A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.</small>
          </aside>
        </div>
      </div>
      <figcaption id="landing-preview-caption">Prévia da área de consultas do Arquivio. <span>Exemplos fictícios.</span></figcaption>
    </figure>
  );
}

const questions = [
  ["Quais ferramentas posso conectar?", "Google Drive, OneDrive, Notion e SharePoint. Somente Owner/Admin da organização no Arquivio pode conectar fontes. No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso."],
  ["O Arquivio altera meus arquivos?", "Não. Os originais continuam no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura."],
  ["Quem pode consultar os documentos?", "Todos os membros da organização podem consultar o conteúdo sincronizado. O Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe."],
  ["E se faltar informação?", "O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta."],
  ["Que conteúdo é compatível?", "Documentos Google, PDFs com texto, DOCX, páginas do Notion e Markdown. Imagens escaneadas, planilhas e apresentações ainda não são indexadas."],
  ["Quando os documentos ficam disponíveis?", "Depois da sincronização e do processamento em segundo plano. Alterações nos originais exigem uma nova sincronização."],
  ["Como a IA usa o conteúdo?", "O texto necessário para busca e resposta é processado pelo provedor de IA configurado. Confira se esse uso atende às políticas da sua organização."],
];

/** Below-the-fold reveal is progressive enhancement: content stays visible without JS or with reduced motion. */
function useSectionReveal(root: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const page = root.current;
    if (!page || !("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const targets = Array.from(page.querySelectorAll<HTMLElement>("[data-reveal]")).filter((el) => el.getBoundingClientRect().top > window.innerHeight);
    if (targets.length === 0) return;
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add("is-revealed"); observer.unobserve(entry.target); }
    }, { threshold: 0.15 });
    for (const el of targets) { el.classList.add("is-pending"); observer.observe(el); }
    // Reduced motion switched on mid-page: reveal everything still pending, once, without animating.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onReducedChange = (event: MediaQueryListEvent) => { if (!event.matches) return; observer.disconnect(); for (const el of targets) el.classList.add("is-revealed"); };
    reduced.addEventListener("change", onReducedChange);
    return () => { reduced.removeEventListener("change", onReducedChange); observer.disconnect(); for (const el of targets) el.classList.remove("is-pending", "is-revealed"); };
  }, [root]);
}

/** Renders the decorative slot only after the asset has loaded, so a missing file never shows a broken image. */
function useOptionalImage(src: string) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    const image = new Image();
    image.onload = () => { if (active) setReady(true); };
    image.src = src;
    return () => { active = false; image.onload = null; };
  }, [src]);
  return ready;
}

export function LandingPage({ onLogin, onSignUp }: LandingPageProps) {
  const pageRef = useRef<HTMLDivElement>(null);
  const storyArt = useOptionalImage(STORY_ART_SRC);
  useSectionReveal(pageRef);
  return (
    <div className="landing-page" ref={pageRef}>
      <a className="landing-skip-link" href="#landing-main">Pular para o conteúdo</a>
      <header className="landing-header landing-container">
        <a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, início"><Brand /></a>
        <nav className="landing-desktop-nav" aria-label="Navegação principal"><a href="#produto">Produto</a><a href="#integracoes">Integrações</a><a href="#como-funciona">Como funciona</a><a href="#perguntas">Dúvidas</a></nav>
        <div className="landing-header-actions"><ThemeToggle /><button className="landing-login" onClick={onLogin}>Entrar</button><button className="landing-button landing-button-small" onClick={onSignUp}>Criar conta <ArrowUpRight size={16} /></button></div>
        <details className="landing-mobile-menu"><summary aria-label="Abrir navegação"><Menu size={23} /></summary><nav aria-label="Navegação móvel"><a href="#produto">Produto</a><a href="#integracoes">Integrações</a><a href="#como-funciona">Como funciona</a><a href="#perguntas">Dúvidas</a><div className="landing-mobile-theme"><span>Aparência</span><ThemeToggle /></div><button onClick={onLogin}>Entrar</button><button className="landing-mobile-signup" onClick={onSignUp}>Criar conta</button></nav></details>
      </header>

      <main id="landing-main">
        <div className="landing-stage landing-container">
          <section className="landing-hero" aria-labelledby="landing-hero-title">
            <p className="landing-eyebrow"><span className="landing-status-dot" /> SEU CONHECIMENTO, COM CONTEXTO</p>
            <h1 id="landing-hero-title">A resposta está nos arquivos.<br /><em>Agora você sabe onde.</em></h1>
            <p className="landing-hero-description">Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.</p>
            <div className="landing-hero-actions"><button className="landing-button" onClick={onSignUp}>Começar com o Arquivio <ArrowRight size={18} /></button><button className="landing-login" onClick={onLogin}>Já tenho uma conta</button></div>
            <p className="landing-hero-note"><Check size={14} /> Conexões de leitura · originais preservados</p>
          </section>

          <section id="produto" className="landing-product-section"><ProductPreview /></section>
        </div>

        <section id="integracoes" className="landing-integrations landing-container" aria-labelledby="landing-integrations-title" data-reveal>
          <div className="landing-integrations-intro">
            <p className="landing-eyebrow">INTEGRAÇÕES DISPONÍVEIS</p>
            <h2 id="landing-integrations-title"><span>4</span> fontes.<br /><em>1 lugar para perguntar.</em></h2>
            <p>Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas.</p>
          </div>
          <ul className="landing-integrations-list" aria-label="Ferramentas que você pode conectar">
            <li><ProviderLogo provider="google" size={32} /><span>Google Drive</span></li>
            <li><ProviderLogo provider="onedrive" size={32} /><span>OneDrive</span></li>
            <li><ProviderLogo provider="notion" size={32} /><span>Notion</span></li>
            <li><ProviderLogo provider="sharepoint" size={32} /><span>SharePoint</span></li>
          </ul>
        </section>

        <section className="landing-story landing-container" aria-labelledby="landing-story-title" data-reveal>
          <div className="landing-story-intro">
            <p className="landing-eyebrow">O QUE MUDA NA ROTINA</p><h2 id="landing-story-title">Da procura à resposta,<br /><em>sem perder o caminho.</em></h2><p>O conhecimento da equipe já está nos documentos. O Arquivio ajuda a encontrar o trecho certo e a voltar à fonte sempre que você precisar de mais detalhes.</p>
            {storyArt && <div className="landing-story-art" aria-hidden="true" />}
          </div>
          <div className="landing-story-list">
            <article><span>01 / ENCONTRE</span><div><h3>Pergunte como você perguntaria a um colega.</h3><p>Recupere decisões, entregas e informações registradas sem abrir cada arquivo por conta própria.</p></div></article>
            <article><span>02 / DELIMITE</span><div><h3>Escolha onde buscar.</h3><p>Consulte todo o conteúdo indexado ou restrinja a pergunta a uma ferramenta ou pasta específica.</p></div></article>
            <article><span>03 / CONFIRA</span><div><h3>Volte aos documentos.</h3><p>Veja as fontes apresentadas com a resposta e abra os originais para verificar o contexto completo.</p></div></article>
          </div>
        </section>

        <section className="landing-process" id="como-funciona" aria-labelledby="landing-process-title"><div className="landing-container" data-reveal>
          <div className="landing-process-heading"><p className="landing-eyebrow">COMO FUNCIONA</p><h2 id="landing-process-title">Seus arquivos continuam onde estão.<br /><em>As respostas ficam mais perto.</em></h2></div>
          <div className="landing-process-grid">
            <article><span>01</span><h3>Conecte as fontes</h3><p>Escolha materiais compartilháveis no Google Drive, OneDrive, Notion ou SharePoint. As conexões são de leitura e preservam os originais.</p></article>
            <article><span>02</span><h3>Aguarde a sincronização</h3><p>O Arquivio processa o conteúdo selecionado em segundo plano. A consulta considera o que já foi sincronizado e indexado.</p></article>
            <article><span>03</span><h3>Pergunte com contexto</h3><p>Defina o escopo, faça sua pergunta e confira os documentos que sustentam a resposta.</p></article>
          </div>
          <p className="landing-process-note"><ShieldCheck size={18} aria-hidden="true" /> Todos na organização podem consultar o conteúdo sincronizado. Selecione apenas materiais compartilháveis com a equipe.</p>
        </div></section>

        <section className="landing-faq landing-container" id="perguntas" aria-labelledby="landing-faq-title" data-reveal>
          <div><p className="landing-eyebrow">ANTES DE COMEÇAR</p><h2 id="landing-faq-title">O que você<br /><em>precisa saber.</em></h2></div>
          <div className="landing-faq-list">{questions.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={19} /></summary><p>{answer}</p></details>)}</div>
        </section>

        <section className="landing-closing landing-container" aria-labelledby="landing-closing-title" data-reveal>
          <p className="landing-eyebrow">COMECE PELOS SEUS DOCUMENTOS</p>
          <h2 id="landing-closing-title">Menos procura.<br /><em>Mais contexto.</em></h2>
          <button className="landing-button" onClick={onSignUp}>Criar minha conta <ArrowRight size={18} /></button>
        </section>
      </main>

      <footer className="landing-footer landing-container"><a href="#landing-main" className="landing-brand-link" aria-label="Arquivio, voltar ao início"><Brand /></a><p>Conhecimento que encontra o seu contexto.</p><nav className="landing-legal-links" aria-label="Informações legais"><a href="/privacidade">Privacidade <ArrowUpRight size={14} /></a><a href="/termos">Termos de uso <ArrowUpRight size={14} /></a></nav></footer>
    </div>
  );
}
