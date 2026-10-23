"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowRight, Check, ChevronDown, ChevronRight,
  ExternalLink, FileText, Folder, FolderOpen, List, MousePointer2, PanelRightClose, Pause, Play, Plus, Send, ShieldCheck, Sparkles,
} from "lucide-react";
import "./landing.css";
import { Brand } from "./brand";
import { landingCtaMode } from "./landing-session.mjs";
import { ProviderLogo, type ProviderLogoName } from "./provider-logo";
import { BUSINESS_TRIAL_CTA, TRIAL_CTA, TRIAL_DAYS } from "./landing-plans.mjs";
import { FaqSection, LandingFooter, LandingHeader, PricingSection, UpgradeBand, useSectionReveal, type LandingActions, type LandingSession } from "./landing-shared";

export type { LandingSession, SignupIntent } from "./landing-shared";
type LandingPageProps = LandingActions & { session?: LandingSession };

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
              <div className="landing-app-toolbar"><span><Plus size={14} />Nova conversa</span><PanelRightClose size={16} /></div>
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
                        <div className={`landing-answer-author${sent ? "" : " landing-stage-pending"}`}><span><Sparkles size={16} /></span><div><strong>Arquivio</strong><small>{DEMO_SCOPE}</small></div></div>
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
                  <span className="landing-composer-send"><small>{typingTurn ? `${typedLength}/1000` : "0/1000"}</small><span className="landing-send"><Send size={14} />Enviar</span></span>
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
  ["Qual a diferença entre conta pessoal e conta de empresa?", "A conta pessoal é só sua: uma pessoa, limites menores, ideal para uso individual. A conta de empresa tem membros, funções (Owner, Admin e Membro) e limites maiores, e é a forma de usar o Arquivio em equipe."],
  ["Posso começar pessoal e depois virar empresa?", "Sim. Quando precisar convidar outras pessoas, transforme sua conta pessoal em conta de empresa. Seus documentos e suas fontes conectadas ficam onde estão."],
  ["Conta pessoal pode ter mais de uma pessoa?", "Não. Para trabalhar com colegas, use a conta de empresa."],
  ["Existe plano grátis?", `Não. Você testa por ${TRIAL_DAYS} dias, sem cartão. Depois, assina um plano para continuar adicionando arquivos e perguntando.`],
  ["O que acontece quando o teste acaba?", "A conta fica em modo de leitura: você continua entrando, vendo e baixando seus documentos, mas não adiciona arquivos, não convida pessoas e não faz novas perguntas até assinar. Nada é apagado."],
  ["Como funciona o preço da empresa?", "Um valor base mensal com as primeiras pessoas incluídas (5 no Team, 20 no Scale) e um valor por pessoa extra. Você adiciona ou remove pessoas quando quiser."],
  ["Meu time vê meus documentos pessoais?", "Não. Conta pessoal e conta de empresa são separadas. Só é compartilhado o que for conectado à conta da empresa."],
  ["Quais ferramentas posso conectar?", "Google Drive, OneDrive, Notion, SharePoint e ClickUp, conforme o plano. Somente Owner/Admin da organização no Arquivio pode conectar fontes. No SharePoint, selecione bibliotecas de documentos de sites SharePoint e Teams com uma conta corporativa ou escolar do Microsoft 365; um administrador do Microsoft 365 pode precisar aprovar o acesso."],
  ["O Arquivio altera meus arquivos?", "Não. Os originais continuam no Google Drive, OneDrive, Notion, SharePoint ou ClickUp. As conexões são de leitura."],
  ["Quem pode consultar os documentos?", "Todos os membros da organização podem consultar o conteúdo sincronizado. O Arquivio não reproduz as permissões originais por documento do SharePoint. Conecte apenas materiais compartilháveis com a equipe."],
  ["E se faltar informação?", "O Arquivio informa quando não encontra evidência suficiente e mostra os documentos usados em cada resposta."],
  ["Que conteúdo é compatível?", "Documentos Google, PDFs com texto, DOCX, páginas do Notion e Markdown. Imagens escaneadas, planilhas e apresentações ainda não são indexadas."],
  ["Quando os documentos ficam disponíveis?", "Depois da sincronização e do processamento em segundo plano. Alterações nos originais exigem uma nova sincronização."],
  ["Como a IA usa o conteúdo?", "O texto necessário para busca e resposta é processado pelo provedor de IA configurado. Confira se esse uso atende às políticas da sua organização."],
];

const NAV = [
  { href: "#produto", label: "Produto" }, { href: "#para-quem", label: "Para quem" }, { href: "#precos", label: "Preços" },
  { href: "#perguntas", label: "Dúvidas" },
];

const useCases = {
  pessoal: [
    ["Estudar e pesquisar", "“Onde eu anotei aquela decisão?” Pergunte e abra o trecho exato."],
    ["Freela e consultoria", "Reúna contratos, briefings e entregas de clientes e consulte sem caçar pastas."],
    ["Vida organizada", "Notas do Notion e arquivos do Drive respondendo na mesma conversa."],
  ],
  empresa: [
    ["Onboarding", "Quem entra no time pergunta em vez de interromper alguém."],
    ["Comercial e atendimento", "Achar política, preço e proposta anterior sem pedir no chat."],
    ["Operações e jurídico", "Confirmar o que foi combinado, com o documento original à mão."],
  ],
} as const;

export function LandingPage({ onLogin, onSignUp, onOpenApp = onLogin, onLogout = () => undefined, session = { status: "anonymous" } }: LandingPageProps) {
  const mode = landingCtaMode(session);
  const signedIn = session.status === "authenticated" ? session : null;
  const pageRef = useRef<HTMLDivElement>(null);
  useSectionReveal(pageRef);
  return (
    <div className="landing-page" ref={pageRef}>
      <a className="landing-skip-link" href="#landing-main">Pular para o conteúdo</a>
      <LandingHeader current="pessoal" session={session} nav={NAV} intent={{ tipo: "pessoal" }} homeHref="#landing-main" onLogin={onLogin} onSignUp={onSignUp} onOpenApp={onOpenApp} onLogout={onLogout} />

      <main id="landing-main">
        <div className="landing-stage landing-container">
          <section className="landing-hero" aria-labelledby="landing-hero-title">
            <p className="landing-eyebrow"><span className="landing-status-dot" /> SEU CONHECIMENTO, COM CONTEXTO</p>
            <h1 id="landing-hero-title">A resposta está nos arquivos.<br /><em>Agora você sabe onde.</em></h1>
            <p className="landing-hero-description">Pergunte ao Arquivio sobre seus documentos, sozinho ou com o time inteiro. Receba uma resposta direta e os arquivos que a sustentam.</p>
            <div className="landing-hero-actions" data-session={mode}>{mode === "anonymous" && <><button className="landing-button" onClick={() => onSignUp({ tipo: "pessoal" })}>{TRIAL_CTA} <ArrowRight size={18} /></button><button className="landing-login" onClick={() => onSignUp({ tipo: "empresa" })}>{BUSINESS_TRIAL_CTA}</button></>}{mode === "loading" && <span className="landing-session-placeholder landing-session-placeholder-hero" aria-hidden="true" />}{signedIn && <button className="landing-button" onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button>}</div>
            <p className="landing-hero-note"><Check size={14} /> {TRIAL_DAYS} dias para testar, sem cartão · conexões somente leitura · originais preservados</p>
          </section>

          <section id="produto" className="landing-product-section"><ProductPreview /></section>
        </div>

        <section id="para-quem" className="landing-audience landing-container" aria-labelledby="landing-audience-title" data-reveal>
          <div className="landing-audience-intro"><p className="landing-eyebrow">PARA QUEM</p><h2 id="landing-audience-title">Do seu uso individual<br /><em>ao conhecimento do time.</em></h2></div>
          <div className="landing-audience-cards">
            <article>
              <h3>Para você</h3>
              <p>Seus documentos do Drive, Notion e outros num só lugar para perguntar. Pare de abrir arquivo por arquivo.</p>
              <ul><li><Check size={14} aria-hidden="true" />Conecte suas fontes em minutos</li><li><Check size={14} aria-hidden="true" />Respostas com a fonte ao lado</li><li><Check size={14} aria-hidden="true" />Fica só com você</li></ul>
              {mode === "app" ? <button className="landing-button" onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button> : mode === "anonymous" ? <button className="landing-button" onClick={() => onSignUp({ tipo: "pessoal" })}>{TRIAL_CTA} <ArrowRight size={18} /></button> : <span className="landing-session-placeholder" aria-hidden="true" />}
            </article>
            <article>
              <h3>Para sua equipe</h3>
              <p>Todo mundo pergunta ao mesmo acervo, com as mesmas fontes. Você controla quem entra e o que está conectado.</p>
              <ul><li><Check size={14} aria-hidden="true" />Convide membros e defina funções</li><li><Check size={14} aria-hidden="true" />Admins conectam as fontes da empresa</li><li><Check size={14} aria-hidden="true" />Limites maiores de documentos e consultas</li></ul>
              {mode === "app" ? <button className="landing-button" onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button> : mode === "anonymous" ? <button className="landing-button" onClick={() => onSignUp({ tipo: "empresa" })}>{BUSINESS_TRIAL_CTA} <ArrowRight size={18} /></button> : <span className="landing-session-placeholder" aria-hidden="true" />}
              <a className="landing-audience-link" href="/empresas">Ver página para empresas <ArrowRight size={16} /></a>
            </article>
          </div>
        </section>

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

        <section className="landing-usecases landing-container" aria-labelledby="landing-usecases-title" data-reveal>
          <div className="landing-usecases-intro"><p className="landing-eyebrow">CASOS DE USO</p><h2 id="landing-usecases-title">Do dia a dia<br /><em>à rotina do time.</em></h2></div>
          <div className="landing-usecases-cols">
            <div><h3>Para você</h3><ul>{useCases.pessoal.map(([title, text]) => <li key={title}><strong>{title}</strong><span>{text}</span></li>)}</ul></div>
            <div><h3>Para sua equipe</h3><ul>{useCases.empresa.map(([title, text]) => <li key={title}><strong>{title}</strong><span>{text}</span></li>)}</ul></div>
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
          <p className="landing-process-note"><ShieldCheck size={18} aria-hidden="true" /> Em equipe, o Owner ou Admin conecta as fontes uma vez; todos os membros consultam o que foi sincronizado.</p>
        </div></section>

        <section className="landing-trust landing-container" aria-labelledby="landing-trust-title" data-reveal>
          <div><p className="landing-eyebrow">SEGURANÇA E CONTROLE</p><h2 id="landing-trust-title">Seus arquivos<br /><em>não saem do lugar.</em></h2></div>
          <ul>
            <li><strong>Somente leitura.</strong><span>O Arquivio não altera nem apaga nada nas suas ferramentas.</span></li>
            <li><strong>Fonte em toda resposta.</strong><span>Se não houver evidência suficiente, ele diz que não achou.</span></li>
            <li><strong>Funções claras.</strong><span>Na conta da empresa, só Owner e Admin conectam fontes e convidam membros.</span></li>
          </ul>
        </section>

        <PricingSection kinds={["pessoal", "empresa"]} mode={mode} onSignUp={onSignUp} onOpenApp={onOpenApp} title={<>Teste por {TRIAL_DAYS} dias.<br /><em>Escolha o plano quando fizer sentido.</em></>} subtitle={`Todo plano começa com um teste grátis de ${TRIAL_DAYS} dias, sem cartão. Mude de plano ou de tipo de conta sem perder o que já conectou.`} />
        <UpgradeBand mode={mode} onOpenApp={onOpenApp} />

        <FaqSection questions={questions} />

        <section className="landing-closing landing-container" aria-labelledby="landing-closing-title" data-reveal>
          <p className="landing-eyebrow">COMECE PELOS SEUS DOCUMENTOS</p>
          <h2 id="landing-closing-title">Menos procura.<br /><em>Mais contexto.</em></h2>
          {mode === "anonymous" && <div className="landing-closing-actions"><button className="landing-button" onClick={() => onSignUp({ tipo: "pessoal" })}>{TRIAL_CTA} <ArrowRight size={18} /></button><button className="landing-button" onClick={() => onSignUp({ tipo: "empresa" })}>{BUSINESS_TRIAL_CTA}</button></div>}{mode === "loading" && <span className="landing-session-placeholder landing-session-placeholder-hero" aria-hidden="true" />}{signedIn && <button className="landing-button" onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button>}
        </section>
      </main>

      <LandingFooter homeHref="#landing-main" links={[{ href: "/empresas", label: "Para empresas" }, { href: "#precos", label: "Preços" }]} />
    </div>
  );
}
