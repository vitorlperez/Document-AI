import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/landing-page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/landing.css", import.meta.url), "utf8");

// Literal copy approved in specs/work-items/lp-chat-modernization-20261002/copy/COPY.md.
const literals = [
  "Pular para o conteúdo", "Produto", "Integrações", "Como funciona", "Dúvidas", "Entrar", "Criar conta",
  "SEU CONHECIMENTO, COM CONTEXTO", "A resposta está nos arquivos.", "Agora você sabe onde.",
  "Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam.",
  "Começar com o Arquivio", "Já tenho uma conta", "Conexões de leitura · originais preservados",
  "VEJA A EXPERIÊNCIA", "Converse com seus documentos.", "Confira a origem.",
  "Estúdio Aurora", "Prévia ilustrativa",
  "Arquivos sincronizados", "Projeto Aurora", "Nova conversa", "Documentos utilizados", "O que você gostaria de saber? Digite @ para mencionar um arquivo ou pasta",
  "0/1000", "Enviar", "Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos.",
  "Prévia das áreas de consultas e Biblioteca do Arquivio.", "Exemplos fictícios.",
  "E qual o prazo disso?", "Pergunte e receba fontes", "Confira na Biblioteca", "Pausar demonstração", "Retomar demonstração", "Indexado", "Briefing de campanha",
  "Todas as ferramentas", "O que ficou definido para a primeira entrega?", "Escopo do projeto.pdf", "Reunião de alinhamento", "Cronograma de entregas",
  "INTEGRAÇÕES DISPONÍVEIS", "1 lugar para perguntar.", "Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas.",
  "O QUE MUDA NA ROTINA", "Da procura à resposta,", "sem perder o caminho.",
  "O conhecimento da equipe já está nos documentos. O Arquivio ajuda a encontrar o trecho certo e a voltar à fonte sempre que você precisar de mais detalhes.",
  "01 / ENCONTRE", "Pergunte como você perguntaria a um colega.", "Recupere decisões, entregas e informações registradas sem abrir cada arquivo por conta própria.",
  "02 / DELIMITE", "Escolha onde buscar.", "Consulte todo o conteúdo indexado ou restrinja a pergunta a uma ferramenta ou pasta específica.",
  "03 / CONFIRA", "Volte aos documentos.", "Veja as fontes apresentadas com a resposta e abra os originais para verificar o contexto completo.",
  "COMO FUNCIONA", "Seus arquivos continuam onde estão.", "As respostas ficam mais perto.",
  "Conecte as fontes", "Escolha materiais compartilháveis no Google Drive, OneDrive, Notion, SharePoint ou ClickUp. As conexões são de leitura e preservam os originais.",
  "Aguarde a sincronização", "O Arquivio processa o conteúdo selecionado em segundo plano. A consulta considera o que já foi sincronizado e indexado.",
  "Pergunte com contexto", "Defina o escopo, faça sua pergunta e confira os documentos que sustentam a resposta.",
  "Todos na organização podem consultar o conteúdo sincronizado. Selecione apenas materiais compartilháveis com a equipe.",
  "ANTES DE COMEÇAR", "O que você", "precisa saber.",
  "Somente Owner/Admin da organização no Arquivio pode conectar fontes.",
  "O Arquivio não reproduz as permissões originais por documento do SharePoint.",
  "Imagens escaneadas, planilhas e apresentações ainda não são indexadas.",
  "Alterações nos originais exigem uma nova sincronização.",
  "Confira se esse uso atende às políticas da sua organização.",
  "COMECE PELOS SEUS DOCUMENTOS", "Menos procura.", "Mais contexto.", "Criar minha conta",
  "Conhecimento que encontra o seu contexto.", "Privacidade", "Termos de uso",
];

const accessibleNames = [
  "Arquivio, início", "Navegação principal", "Abrir navegação", "Navegação móvel", "Descrição da demonstração",
  "Documentos utilizados",
  "Ferramentas que você pode conectar", "Arquivio, voltar ao início", "Informações legais",
];

test("landing keeps every approved literal and accessible name", () => {
  for (const text of [...literals, ...accessibleNames]) assert.ok(source.includes(text), `missing: ${text}`);
  assert.equal((source.match(/^\s*\["[^"]+\?", "/gm) ?? []).length, 7, "seven FAQ entries");
});

test("landing keeps the onLogin/onSignUp contract and every destination", () => {
  assert.match(source, /export function LandingPage\(\{ onLogin, onSignUp \}: LandingPageProps\)/);
  assert.match(source, /type LandingPageProps = \{ onLogin: \(\) => void; onSignUp: \(\) => void \};/);
  assert.equal((source.match(/onClick=\{onLogin\}/g) ?? []).length, 3, "Entrar (header + menu) and Já tenho uma conta");
  assert.equal((source.match(/onClick=\{onSignUp\}/g) ?? []).length, 4, "Criar conta (header + menu), hero and closing CTAs");
  for (const href of ["#landing-main", "#produto", "#integracoes", "#como-funciona", "#perguntas", "/privacidade", "/termos"]) assert.ok(source.includes(`href="${href}"`), `missing href ${href}`);
  for (const id of ["landing-main", "produto", "integracoes", "como-funciona", "perguntas"]) assert.ok(source.includes(`id="${id}"`), `missing id ${id}`);
  assert.match(source, /aria-pressed=\{userPaused\}/, "viewers can pause the moving demo");
  assert.doesNotMatch(source, /activeCase|demoCases|DEMO_ROTATE_MS/, "the three-case selector and rotation are gone");
  assert.match(source, /const DEMO_LOOP_MS = 28400;/, "25-35s loop");
  assert.match(source, /const T_STATIC = 13600;/);
  assert.doesNotMatch(source, /onPointerEnter|onPointerLeave|setHovered|setFocused/, "demo must not pause on hover or focus");
  assert.match(source, /prefers-reduced-motion: reduce/);
  assert.match(source, /visibilitychange/);
  assert.match(source, /window\.clearInterval\(timer\)/);
  assert.match(source, /new IntersectionObserver/, "demo pauses off-screen");
  assert.match(source, /const running = !reducedMotion && !hidden && inView && !userPaused;/);
  assert.match(source, /useState\(T_STATIC\)/, "server render and reduced motion show the finished conversation");
  assert.match(source, /removeEventListener\("visibilitychange"/);
  assert.match(css, /\.landing-demo-progress[^}]*will-change: transform/);
  assert.match(source, /scaleX\(\$\{Math\.min\(1, t \/ DEMO_LOOP_MS\)\}\)/, "progress follows the demo clock");
  assert.equal((source.match(/<ProductPreview \/>/g) ?? []).length, 1, "a single ProductPreview");
});

test("landing adds no pricing, plans or extra integrations", () => {
  for (const banned of [/R\$/, /preço/i, /\bplanos\b/i, /\/mês/, /gratuit/i, /\btrial\b/i, /provider="github"/, /provider="teams"/, /tempo real/i]) assert.doesNotMatch(source, banned);
});

function splitTopLevel(group) {
  const parts = []; let depth = 0, current = "";
  for (const char of group) { if (char === "(") depth++; if (char === ")") depth--; if (char === "," && depth === 0) { parts.push(current.trim()); current = ""; } else current += char; }
  return [...parts, current.trim()];
}

test("landing styles stay scoped and self-hosted", () => {
  const body = css.replace(/\/\*[\s\S]*?\*\//g, "").replace(/@font-face\s*\{[^}]*\}/g, "").replace(/@keyframes[^{]+\{(?:[^{}]*\{[^}]*\})*\s*\}/g, "").replace(/@(?:media|container)[^{]+\{/g, "");
  const selectors = [...body.matchAll(/(^|\})\s*([^@{}][^{}]*)\{/g)].map((match) => match[2].trim()).filter((selector) => !/^(from|to|\d+%)$/.test(selector));
  for (const group of selectors) for (const selector of splitTopLevel(group)) {
    assert.match(selector, /^\.(landing-|arquivio-brand)/, `unscoped selector: ${selector}`);
  }
  assert.doesNotMatch(css, /https?:\/\//, "no remote fonts or assets");
  assert.doesNotMatch(css, /:root/, "no global tokens");
  for (const font of ["manrope-latin-var.woff2", "ibm-plex-sans-latin-var.woff2"]) {
    assert.ok(css.includes(`/landing/fonts/${font}`));
    assert.ok(existsSync(new URL(`../public/landing/fonts/${font}`, import.meta.url)), `font file ${font}`);
  }
});

test("decorative story art is optional and hidden from assistive tech", () => {
  assert.match(source, /\{storyArt && <div className="landing-story-art" aria-hidden="true" \/>\}/);
  assert.match(source, /image\.onload = \(\) => \{ if \(active\) setReady\(true\); \};/);
});

test("scripted demo is one decorative, shift-free story with a textual equivalent", () => {
  assert.match(source, /className=\{`landing-demo-stage[^`]*`\} aria-hidden="true"/, "staged run hidden from assistive tech");
  assert.match(source, /className="landing-sr-only" role="group" aria-label="Descrição da demonstração"/, "full story as text");
  assert.match(source, /aria-label="Documentos utilizados" role="group"/);
  for (const text of ["Buscando nas fontes…", "Busca concluída", "landing-composer-typed", "landing-demo-cursor", "AnswerWords", "landing-viewer", "landing-cited", "landing-lib-row"]) assert.ok(source.includes(text), `missing: ${text}`);
  // Narrative order: question → follow-up → cursor to Biblioteca → cited file → highlighted passage → fade → loop.
  const order = ["typeStart: 500", "typeStart: 7900", "T_CURSOR_TAB = ", "T_SCENE_LIBRARY = ", "T_CURSOR_ROW = ", "T_VIEWER = ", "T_HIGHLIGHT = ", "T_FADE_OUT = ", "DEMO_LOOP_MS = "].map((needle) => source.indexOf(needle));
  assert.ok(order.every((index, position) => index >= 0 && (position === 0 || index > order[position - 1])), "timeline keeps the story order");
  const value = (name) => Number(source.match(new RegExp(`const ${name} = (\\d+);`))?.[1]);
  assert.ok(value("T_CURSOR_TAB") < value("T_TAB_CLICK") && value("T_TAB_CLICK") < value("T_SCENE_LIBRARY") && value("T_SCENE_LIBRARY") < value("T_CURSOR_ROW") && value("T_CURSOR_ROW") < value("T_ROW_CLICK") && value("T_ROW_CLICK") < value("T_VIEWER") && value("T_VIEWER") < value("T_HIGHLIGHT") && value("T_HIGHLIGHT") < value("T_FADE_OUT") && value("T_FADE_OUT") < value("DEMO_LOOP_MS"));
  assert.match(source, /sources: \[\[CITED_FILE, "Google Drive"\]/, "the follow-up cites the same file the Biblioteca opens");
  assert.match(css, /\.landing-demo-stage \{ position: relative; height: 580px;/, "fixed stage box: no layout shift");
  assert.doesNotMatch(source, /autoFocus|\.focus\(/, "demo never steals focus");
  assert.match(css, /\.landing-stage-pending, \.landing-word-pending \{ visibility: hidden; \}/, "hidden steps keep their box (no layout shift)");
  assert.match(css, /\.landing-sr-only \{/);
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*animation: none !important/);
  assert.doesNotMatch(source, /framer-motion|<video/, "no animation lib or video");
});
