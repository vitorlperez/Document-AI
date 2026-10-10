"use client";

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import {
  ArrowRight, ArrowUpRight, Check, ChevronDown, ChevronRight,
  ExternalLink, FileText, Folder, FolderOpen, List, Menu, MousePointer2, PanelRightClose, Pause, Play, Plus, Send, ShieldCheck, Sparkles,
} from "lucide-react";
import "./landing.css";
import { Brand } from "./brand";
import { ThemeToggle } from "./theme-toggle";
import { ProviderLogo, type ProviderLogoName } from "./provider-logo";

type LandingPageProps = { onLogin: () => void; onSignUp: () => void };

/** Optional decorative art for the Rotina section, delivered separately; the layout never depends on it. */
const STORY_ART_SRC = "/landing/document-context.webp";

type AnswerSegments = [string, boolean][];
type Turn = {
  question: string;
  /** Answer as [text, bold] segments so the streaming effect can reveal it word by word. */
  answer: AnswerSegments;
  providers: ProviderLogoName[];
  sources: [string, string][];
  /** ms from the start of the run. */
  at: { typeStart: number; typeEnd: number; send: number; streamStart: number; streamEnd: number; sources: number };
};

const DEMO_SCOPE = "Todas as ferramentas";
const CITED_FILE = "Escopo do projeto.pdf";
const CITED_EXCERPT = "Prazos: o diagnóstico de marca será entregue em 14 de março e a proposta de posicionamento em 28 de março.";

/**
 * One continuous story, one clock (ms): ask → sourced answer → follow-up that reuses the context →
 * cursor opens Biblioteca → picks the cited file → the cited passage is highlighted → fade → loop.
 */
const turns: Turn[] = [
  {
    question: "O que ficou definido para a primeira entrega?",
    answer: [["A primeira entrega inclui o ", false], ["diagnóstico de marca", true], [" e a ", false], ["proposta de posicionamento", true], [".", false]],
    providers: ["google", "onedrive", "notion", "clickup"],
    sources: [[CITED_FILE, "Google Drive"], ["Reunião de alinhamento", "Notion"], ["Cronograma de entregas", "OneDrive"]],
    at: { typeStart: 500, typeEnd: 2100, send: 2400, streamStart: 3600, streamEnd: 5400, sources: 5600 },
  },
  {
    question: "E qual o prazo disso?",
    answer: [["O ", false], ["diagnóstico de marca", true], [" está previsto para ", false], ["14 de março", true], [" e a ", false], ["proposta de posicionamento", true], [" para ", false], ["28 de março", true], [", conforme o escopo e o cronograma.", false]],
    providers: ["google", "onedrive"],
    sources: [[CITED_FILE, "Google Drive"], ["Cronograma de entregas", "OneDrive"]],
    at: { typeStart: 7900, typeEnd: 9000, send: 9400, streamStart: 10400, streamEnd: 12400, sources: 12600 },
  },
];
const T_CURSOR_TAB = 13800;
const T_TAB_CLICK = 14800;
const T_SCENE_LIBRARY = 15200;
const T_CURSOR_ROW = 17400;
const T_ROW_CLICK = 18500;
const T_VIEWER = 18800;
const T_HIGHLIGHT = 20400;
const T_CURSOR_HIDE = 19800;
const T_FADE_OUT = 27400;
const DEMO_LOOP_MS = 28400;
const T_FADE_IN = 450;
/** Server render, hydration and reduced motion all show this frame: the finished conversation. */
const T_STATIC = 13600;
const DEMO_TICK_MS = 50;

const LIBRARY_ROWS: { name: string; provider: ProviderLogoName; label: string; kind: string }[] = [
  { name: "Briefing de campanha", provider: "clickup", label: "ClickUp", kind: "Documento" },
  { name: "Cronograma de entregas", provider: "onedrive", label: "OneDrive", kind: "DOCX" },
  { name: CITED_FILE, provider: "google", label: "Google Drive", kind: "PDF" },
  { name: "Reunião de alinhamento", provider: "notion", label: "Notion", kind: "Página" },
  { name: "Identidade visual.pdf", provider: "google", label: "Google Drive", kind: "PDF" },
  { name: "Atas de março", provider: "notion", label: "Notion", kind: "Página" },
];
const CITED_ROW = LIBRARY_ROWS.findIndex((row) => row.name === CITED_FILE);
const LIBRARY_TOOLS: { provider: ProviderLogoName; label: string }[] = [
  { provider: "google", label: "Google Drive" }, { provider: "onedrive", label: "OneDrive" },
  { provider: "notion", label: "Notion" }, { provider: "clickup", label: "ClickUp" },
];

const progress = (t: number, from: number, to: number) => Math.min(1, Math.max(0, (t - from) / (to - from)));
const segmentWords = (text: string) => text.split(/(?<=\s)/);
const countWords = (segments: AnswerSegments) => segments.reduce((total, [text]) => total + segmentWords(text).length, 0);
const answerPlain = (segments: AnswerSegments) => segments.map(([text]) => text).join("");

function AnswerWords({ segments, shown }: { segments: AnswerSegments; shown: number }) {
  let index = 0;
  return <>{segments.map(([text, bold], segment) => {
    const words = segmentWords(text).map((word) => {
      const pending = index++ >= shown;
      return <span key={index} className={pending ? "landing-word-pending" : undefined}>{word}</span>;
    });
    return bold ? <strong key={segment}>{words}</strong> : <span key={segment}>{words}</span>;
  })}</>;
}

type CursorTarget = "park" | "tab" | "row";

function ProductPreview() {
  const figureRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const tabRef = useRef<HTMLSpanElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);
  const [elapsed, setElapsed] = useState(T_STATIC);
  const [reducedMotion, setReducedMotion] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [inView, setInView] = useState(false);
  const [userPaused, setUserPaused] = useState(false);
  const [scrollMax, setScrollMax] = useState(0);
  const [layoutTick, setLayoutTick] = useState(0);
  const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
  const running = !reducedMotion && !hidden && inView && !userPaused;
  const t = reducedMotion ? T_STATIC : elapsed;

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(query.matches);
    const syncVisibility = () => setHidden(document.visibilityState === "hidden");
    sync();
    syncVisibility();
    query.addEventListener("change", sync);
    document.addEventListener("visibilitychange", syncVisibility);
    const figure = figureRef.current;
    const observer = figure && "IntersectionObserver" in window ? new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.25 }) : null;
    if (observer && figure) observer.observe(figure);
    return () => {
      query.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", syncVisibility);
      observer?.disconnect();
    };
  }, []);

  // Single clock: ticks only while visible, on screen, not paused and motion is allowed; pausing keeps the position so resuming continues.
  useEffect(() => {
    if (!running) return;
    if (!startedRef.current) { startedRef.current = true; setElapsed(0); }
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = now - last;
      last = now;
      setElapsed((current) => (current + delta >= DEMO_LOOP_MS ? 0 : current + delta));
    }, DEMO_TICK_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  // The stage has a fixed box; these measurements only move things inside it (scroll offset, cursor target), so nothing shifts the page.
  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage || !("ResizeObserver" in window)) return;
    const observer = new ResizeObserver(() => setLayoutTick((tick) => tick + 1));
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const inner = innerRef.current;
    if (viewport && inner) setScrollMax(Math.max(0, inner.offsetHeight - viewport.clientHeight));
  }, [layoutTick]);

  const target: CursorTarget = t >= T_CURSOR_ROW ? "row" : t >= T_CURSOR_TAB ? "tab" : "park";
  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const box = stage.getBoundingClientRect();
    const element = target === "tab" ? tabRef.current : target === "row" ? rowRef.current : null;
    if (!element) { setCursorPos({ x: box.width * 0.72, y: box.height * 0.86 }); return; }
    const rect = element.getBoundingClientRect();
    setCursorPos({ x: rect.left - box.left + rect.width * (target === "tab" ? 0.5 : 0.42), y: rect.top - box.top + rect.height * 0.55 });
  }, [target, layoutTick]);

  const scene = t >= T_SCENE_LIBRARY ? "library" : "chat";
  const fading = !reducedMotion && (t < T_FADE_IN || t >= T_FADE_OUT);
  const resetting = !reducedMotion && t < T_FADE_IN + 150;
  const turnIndexTyping = turns.findIndex((turn) => t >= turn.at.typeStart && t < turn.at.send);
  const typingTurn = turnIndexTyping >= 0 ? turns[turnIndexTyping] : null;
  const typedLength = typingTurn ? Math.round(progress(t, typingTurn.at.typeStart, typingTurn.at.typeEnd) * typingTurn.question.length) : 0;
  const scrolled = t >= turns[1].at.send;
  const tabActive = t >= T_TAB_CLICK + 200;
  const viewerOpen = t >= T_VIEWER;

  return (
    <figure
      ref={figureRef}
      className="landing-preview"
      aria-labelledby="landing-preview-caption"
    >
      <div className="landing-preview-heading">
        <p className="landing-eyebrow">VEJA A EXPERIÊNCIA</p>
        <h2>Converse com seus documentos.<br /><em>Confira a origem.</em></h2>
      </div>
      <div className="landing-demo-steps">
        <ol aria-hidden="true">
          <li className={scene === "chat" ? "is-current" : undefined}><span>1</span>Pergunte e receba fontes</li>
          <li className={scene === "library" ? "is-current" : undefined}><span>2</span>Confira na Biblioteca</li>
        </ol>
        <button type="button" className={`landing-demo-pause${reducedMotion ? " is-off" : ""}`} aria-pressed={userPaused} disabled={reducedMotion} tabIndex={reducedMotion ? -1 : undefined} onClick={() => setUserPaused((value) => !value)}>
          {userPaused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}{userPaused ? "Retomar demonstração" : "Pausar demonstração"}
        </button>
        {!reducedMotion && <span className="landing-demo-progress" aria-hidden="true" style={{ transform: `scaleX(${Math.min(1, t / DEMO_LOOP_MS)})` }} />}
      </div>

      <div className="landing-app-shell">
        <div className="landing-app-bar" aria-hidden="true">
          <Brand compact />
          <span className="landing-app-company">Estúdio Aurora <ChevronDown size={12} /></span>
          <span className="landing-app-tabs">
            <span className={`landing-app-tab${tabActive ? "" : " is-active"}`}><Sparkles size={14} />Consultas</span>
            <span ref={tabRef} className={`landing-app-tab${tabActive ? " is-active" : ""}${t >= T_TAB_CLICK && t < T_TAB_CLICK + 400 ? " is-pressed" : ""}`}><FolderOpen size={14} />Biblioteca</span>
          </span>
          <span className="landing-preview-label">Prévia ilustrativa</span>
        </div>

        {/* The staged run is decoration: assistive tech reads the finished story below instead. */}
        <div className="landing-sr-only" role="group" aria-label="Descrição da demonstração">
          <p>Pergunta ({DEMO_SCOPE}): {turns[0].question}</p>
          <p>Resposta do Arquivio: {answerPlain(turns[0].answer)}</p>
          <div aria-label="Documentos utilizados" role="group">
            <p>Documentos utilizados:</p>
            <ol>{turns[0].sources.map(([name, provider]) => <li key={name}>{name}, {provider}</li>)}</ol>
          </div>
          <p>Pergunta de acompanhamento: {turns[1].question}</p>
          <p>Resposta do Arquivio: {answerPlain(turns[1].answer)}</p>
          <p>Em seguida, a Biblioteca lista arquivos do Google Drive, OneDrive, Notion e ClickUp. Ao abrir {CITED_FILE}, o trecho citado na resposta aparece destacado: {CITED_EXCERPT}</p>
        </div>

        <div ref={stageRef} className={`landing-demo-stage${fading ? " is-fading" : ""}`} aria-hidden="true">
          <div className={`landing-demo-content${resetting ? " is-resetting" : ""}`}>
            <section className={`landing-scene landing-scene-chat${scene === "chat" ? " is-on" : ""}`}>
              <div className="landing-app-toolbar"><span><Plus size={13} />Nova conversa</span><PanelRightClose size={16} /></div>
              <div className="landing-thread-viewport" ref={viewportRef}>
                <div className="landing-app-thread" ref={innerRef} style={{ transform: `translateY(${scrolled ? -scrollMax : 0}px)` }}>
                  {turns.map((turn, turnIndex) => {
                    const sent = t >= turn.at.send;
                    const searching = sent && t < turn.at.streamStart;
                    const totalWords = countWords(turn.answer);
                    const shownWords = Math.floor(progress(t, turn.at.streamStart, turn.at.streamEnd) * totalWords + (t >= turn.at.streamEnd ? 1 : 0));
                    const activeProvider = searching ? Math.floor((t - turn.at.send) / 280) % turn.providers.length : -1;
                    return <div key={turn.question} className="landing-turn">
                      <div className={`landing-user-message${sent ? "" : " landing-stage-pending"}`}>
                        {turnIndex === 0 && <small>{DEMO_SCOPE}</small>}
                        <p>{turn.question}</p>
                      </div>
                      <article className="landing-answer">
                        <div className={`landing-answer-author${sent ? "" : " landing-stage-pending"}`}><span><Sparkles size={15} /></span><div><strong>Arquivio</strong><small>{DEMO_SCOPE}</small></div></div>
                        <div className={`landing-search-status${sent ? "" : " landing-stage-pending"}${searching ? " is-searching" : ""}`}>
                          <span className="landing-search-logos">{turn.providers.map((provider, index) => <span key={provider} className={index === activeProvider ? "is-active" : undefined}><ProviderLogo provider={provider} size={16} /></span>)}</span>
                          <span>{searching ? "Buscando nas fontes…" : "Busca concluída"}</span>
                        </div>
                        <p><AnswerWords segments={turn.answer} shown={shownWords} /></p>
                        <div className={`landing-answer-sources${t >= turn.at.sources ? " is-shown" : ""}`}>
                          <strong>Documentos utilizados</strong>
                          {turn.sources.map(([name, provider], index) => <div key={name} style={{ animationDelay: `${index * 140}ms` }}><span>{index + 1}.</span><FileText size={14} /><b>{name}</b><small>{provider}</small></div>)}
                        </div>
                      </article>
                    </div>;
                  })}
                </div>
              </div>
              <div className="landing-composer">
                <span className="landing-composer-input">
                  <span className={typingTurn ? "landing-stage-pending" : undefined}>O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta</span>
                  {typingTurn && <span className="landing-composer-typed">{typingTurn.question.slice(0, typedLength)}<i className="landing-caret" /></span>}
                </span>
                <span className="landing-composer-actions">
                  <span className="landing-scope-trigger"><span>{DEMO_SCOPE}</span><ChevronDown size={12} /></span>
                  <span className="landing-composer-send"><small>{typingTurn ? `${typedLength}/1000` : "0/1000"}</small><span className="landing-send"><Send size={13} />Enviar</span></span>
                </span>
              </div>
              <p className="landing-composer-hint">Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.</p>
            </section>

            <section className={`landing-scene landing-scene-library${scene === "library" ? " is-on" : ""}`}>
              <aside className="landing-lib-tools">
                <div className="landing-panel-title"><strong>Biblioteca</strong><span>Arquivos sincronizados</span></div>
                <div className="landing-lib-tool is-selected"><Folder size={16} /><span>Todas as fontes</span></div>
                {LIBRARY_TOOLS.map((tool) => <div key={tool.provider} className="landing-lib-tool"><ProviderLogo provider={tool.provider} size={18} /><span>{tool.label}</span><i className="landing-lib-dot" /></div>)}
              </aside>
              <div className="landing-lib-main">
                <div className="landing-lib-head">
                  <div><strong>Arquivos</strong><span className="landing-lib-crumb">Biblioteca <ChevronRight size={12} /> Projeto Aurora</span></div>
                  <span className="landing-lib-seg"><List size={14} />Lista</span>
                </div>
                <div className="landing-lib-list">
                  {LIBRARY_ROWS.map((row, index) => (
                    <div key={row.name} ref={index === CITED_ROW ? rowRef : undefined} style={{ animationDelay: `${index * 90}ms` }} className={`landing-lib-row${index === CITED_ROW && t >= T_ROW_CLICK ? " is-clicked" : ""}`}>
                      <FileText size={16} /><b>{row.name}</b><span className="landing-lib-provider"><ProviderLogo provider={row.provider} size={16} /><span>{row.label}</span></span><small>{row.kind}</small><em>Indexado</em>
                    </div>
                  ))}
                </div>
              </div>
              <aside className={`landing-viewer${viewerOpen ? " is-open" : ""}`}>
                <div className="landing-viewer-head"><FileText size={16} /><b>{CITED_FILE}</b><span className="landing-lib-provider"><ProviderLogo provider="google" size={16} /><span>Google Drive</span></span><ExternalLink size={14} /></div>
                <div className="landing-viewer-body">
                  <h4>Escopo do projeto — Estúdio Aurora</h4>
                  <span className="landing-viewer-bar" style={{ width: "92%" }} /><span className="landing-viewer-bar" style={{ width: "78%" }} />
                  <p className="landing-viewer-kicker">Trecho citado na resposta · página 2</p>
                  <p className={`landing-cited${t >= T_HIGHLIGHT ? " is-lit" : ""}`}><mark>{CITED_EXCERPT}</mark></p>
                  <span className="landing-viewer-bar" style={{ width: "86%" }} /><span className="landing-viewer-bar" style={{ width: "64%" }} />
                </div>
              </aside>
            </section>

            <MousePointer2 className={`landing-demo-cursor${t >= T_CURSOR_TAB && t < T_CURSOR_HIDE ? " is-visible" : ""}${(t >= T_TAB_CLICK && t < T_TAB_CLICK + 300) || (t >= T_ROW_CLICK && t < T_ROW_CLICK + 300) ? " is-clicking" : ""}`} size={24} style={{ transform: `translate(${cursorPos.x}px, ${cursorPos.y}px)` }} />
          </div>
        </div>
      </div>
      <figcaption id="landing-preview-caption">Prévia das áreas de consultas e Biblioteca do Arquivio. <span>Exemplos fictícios.</span></figcaption>
    </figure>
  );
}

const questions = [
  ["Quais ferramentas posso conectar?", "Google Drive, OneDrive, Notion, SharePoint e ClickUp. Somente Owner/Admin da organização no Arquivio pode conectar fontes. No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso."],
  ["O Arquivio altera meus arquivos?", "Não. Os originais continuam no Google Drive, OneDrive, Notion, SharePoint ou ClickUp. As conexões são de leitura."],
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
    // Repeats on every entry: the reveal observer adds .is-revealed; a second observer with no margin and threshold 0
    // removes it only once the section is fully outside the viewport (hysteresis against flicker at the edge).
    const reveal = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) entry.target.classList.add("is-revealed");
    }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
    const reset = new IntersectionObserver((entries) => {
      for (const entry of entries) if (!entry.isIntersecting) entry.target.classList.remove("is-revealed");
    }, { threshold: 0 });
    for (const el of targets) { el.classList.add("is-pending"); reveal.observe(el); reset.observe(el); }
    // Reduced motion switched on mid-page: reveal everything and stop observing, without animating.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onReducedChange = (event: MediaQueryListEvent) => { if (!event.matches) return; reveal.disconnect(); reset.disconnect(); for (const el of targets) el.classList.add("is-revealed"); };
    reduced.addEventListener("change", onReducedChange);
    return () => { reduced.removeEventListener("change", onReducedChange); reveal.disconnect(); reset.disconnect(); for (const el of targets) el.classList.remove("is-pending", "is-revealed"); };
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
            <h2 id="landing-integrations-title"><span>5</span> fontes.<br /><em>1 lugar para perguntar.</em></h2>
            <p>Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas.</p>
          </div>
          <ul className="landing-integrations-list" aria-label="Ferramentas que você pode conectar">
            <li><ProviderLogo provider="google" size={32} /><span>Google Drive</span></li>
            <li><ProviderLogo provider="onedrive" size={32} /><span>OneDrive</span></li>
            <li><ProviderLogo provider="notion" size={32} /><span>Notion</span></li>
            <li><ProviderLogo provider="sharepoint" size={32} /><span>SharePoint</span></li>
            <li><ProviderLogo provider="clickup" size={32} /><span>ClickUp</span></li>
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
            <article><span>01</span><h3>Conecte as fontes</h3><p>Escolha materiais compartilháveis no Google Drive, OneDrive, Notion, SharePoint ou ClickUp. As conexões são de leitura e preservam os originais.</p></article>
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
