# Brief-baseline — Modernização da LP Arquivio (lp-chat-modernization-20261002)

- Data: 2026-10-02 · Executor: pane-361 (builder, Missão 37) · Chamador: pane-360
- Branch: `design/lp-chat-modernization-20261002` (criada a partir de `main@a43dbdd`, antes de qualquer escrita — ver §9)
- Fase: **baseline / preparação de direção**. Nenhuma implementação, nenhuma mídia gerada. Próximo gate: **H2 — aprovação do styleboard**.

## 1. Escopo aprovado e limites

- Somente a LP / site público agora. App autenticado fica para uma fase posterior.
- Preservar: público, CTAs, conteúdo comercial, preços (não existem — ver §4), marca e botões/destinos existentes.
- Direção visual livre (tipografia, paleta, layout, motion), desde que o conteúdo e os destinos acima permaneçam.

## 2. Stack, comandos e URL

| Item | Valor |
| --- | --- |
| Frontend | React 19.2 + TypeScript 5.9, Next.js 16.2 executado pelo **Vinext 1.0.0-beta.5 / Vite 8**, Tailwind CSS 4.2, lucide-react; Node `>=22.13.0` |
| Dev (portátil) | `cd frontend && npm ci && npm run dev` → `http://localhost:5173` |
| Dev (Docker, rodando agora) | container `document-ai-frontend-1` (`run-framework.mjs dev --port 3000`) → **`http://localhost:3000/`**; API em `http://localhost:8000` (`document-ai-api-1`) |
| Build | `cd frontend && npm run build` |
| Testes | `cd frontend && node --test tests/*.test.mjs` (12 arquivos; nenhum cobre a LP) |
| Lint | `cd frontend && npm run lint` |
| Responsividade exigida (README) | 375, 768, 1024, 1440 px |

O container Docker não tem bind mount, mas os hashes conferem com a árvore de trabalho (`landing-page.tsx a7f381d1…`, `landing.css be76410f…`, `product-app.tsx c26a95cd…`), então o baseline capturado reflete o código atual.

## 3. Marca, proposta e público atuais

- **Marca:** wordmark `arquivio.` (minúsculas, ponto em verde) + ícone `Layers3` do lucide (`frontend/app/brand.tsx`, `brand.css`). Nome em texto corrido: "Arquivio". Favicon `frontend/public/favicon.svg`; `arquivio-logo-120.png`.
- **Paleta atual (landing.css):** papel `#faf9f5`, tinta `#243b35`, texto secundário `#69746e`, verde-petróleo `#1c6052` (hover `#124b3f`), linha `#dedfd5`, foco âmbar `#bb761c`, seleção `#d9e5d2`.
- **Tipografia atual:** Georgia (títulos, itálico em verde) + Arial (corpo). Sem webfonts.
- **Proposta:** perguntar aos documentos da equipe e receber uma resposta direta **com as fontes que a sustentam**; conexões somente leitura e originais preservados.
- **Público:** equipes e organizações (pt-BR) com conhecimento espalhado em Google Drive, OneDrive, Notion e SharePoint; quem conecta é Owner/Admin.
- **Metadados (`frontend/app/layout.tsx`):** title "Arquivio — O conhecimento da sua equipe, com fontes"; OG title "Arquivio — Sua equipe sabe. Encontre a resposta."; locale `pt_BR`.
- **Restrição de spec:** `specs/001-mvp-document-intelligence.md:102-103` — a identidade do app "acompanha o exemplo da landing"; a LP deve ter exemplos explicitamente ilustrativos e nunca prometer integrações não disponíveis.

## 4. Copy e preços existentes (verbatim, por seção)

**Preços / planos: não existem na LP nem no app** (busca por preço/plano/R$/pricing sem resultados). Nada a preservar além de não inventar preços.

1. **Header** — nav: Produto (`#produto`), Integrações (`#integracoes`), Como funciona (`#como-funciona`), Dúvidas (`#perguntas`); "Entrar"; "Criar conta ↗".
2. **Hero** — eyebrow "SEU CONHECIMENTO, COM CONTEXTO"; H1 "A resposta está nos arquivos. / *Agora você sabe onde.*"; "Pergunte ao Arquivio. Receba uma resposta direta e os documentos que a sustentam."; CTAs "Começar com o Arquivio →" e "Já tenho uma conta"; nota "✓ Conexões de leitura · originais preservados".
3. **Produto (`#produto`) — prévia interativa** — eyebrow "VEJA A EXPERIÊNCIA"; H2 "Converse com seus documentos. / *Confira a origem.*"; 3 casos: "Resposta com fontes", "Com menção @", "Sem evidência suficiente" (perguntas/respostas/fontes em `demoCases`, `landing-page.tsx:14-43`); empresa fictícia "Estúdio Aurora"; selo "Prévia ilustrativa"; legenda "Prévia da área de consultas do Arquivio. Exemplos fictícios."; painéis Biblioteca, conversa com composer e "Buscar arquivos".
4. **Integrações (`#integracoes`)** — "INTEGRAÇÕES DISPONÍVEIS"; "**4** fontes. / *1 lugar para perguntar.*"; "Conecte o que sua equipe já usa. Os arquivos originais permanecem nas suas ferramentas."; Google Drive, OneDrive, Notion, SharePoint (logos SVG próprios em `provider-logo.tsx`).
5. **Rotina** — "O QUE MUDA NA ROTINA"; "Da procura à resposta, / *sem perder o caminho.*"; 01 / ENCONTRE, 02 / DELIMITE, 03 / CONFIRA (títulos e textos em `landing-page.tsx:162-166`).
6. **Como funciona (`#como-funciona`)** — "Seus arquivos continuam onde estão. / *As respostas ficam mais perto.*"; 01 Conecte as fontes · 02 Aguarde a sincronização · 03 Pergunte com contexto; nota de compartilhamento ("Todos na organização podem consultar o conteúdo sincronizado…").
7. **FAQ (`#perguntas`)** — "ANTES DE COMEÇAR"; "O que você / *precisa saber.*"; 7 perguntas (`landing-page.tsx:116-124`) — contêm compromissos legais/produto (Owner/Admin, permissões SharePoint, formatos compatíveis, provedor de IA): **preservar texto literal**.
8. **Fechamento** — "COMECE PELOS SEUS DOCUMENTOS"; "Menos procura. / *Mais contexto.*"; "Criar minha conta →".
9. **Footer** — marca (âncora `#landing-main`); "Conhecimento que encontra o seu contexto."; Privacidade ↗ (`/privacidade`), Termos de uso ↗ (`/termos`).

## 5. Inventário de botões, links e destinos (verificado no navegador)

| Elemento | Local | Tipo | Destino / efeito |
| --- | --- | --- | --- |
| Pular para o conteúdo | topo | `<a>` | `#landing-main` (visível só com foco) |
| Marca | header | `<a>` | `#landing-main` |
| Produto / Integrações / Como funciona / Dúvidas | nav desktop + menu mobile | `<a>` | `#produto`, `#integracoes`, `#como-funciona`, `#perguntas` |
| Entrar | header + menu mobile | `<button>` → `onLogin` | `router.push("/login")` → tela SignIn (`/login`, verificado) |
| Criar conta | header + menu mobile | `<button>` → `onSignUp` | `beginLogin("sign-up")` → `window.location.assign(${API_BASE}/auth/login?screen_hint=sign-up)` (verificado: `http://localhost:8000/auth/login?screen_hint=sign-up`) |
| Começar com o Arquivio | hero | `<button>` → `onSignUp` | idem Criar conta |
| Já tenho uma conta | hero | `<button>` → `onLogin` | `/login` |
| Resposta com fontes / Com menção @ / Sem evidência suficiente | prévia | `<button aria-pressed>` | troca `activeCase` (estado local) |
| 7 perguntas | FAQ | `<details>/<summary>` | expande/recolhe |
| Criar minha conta | fechamento | `<button>` → `onSignUp` | idem Criar conta |
| Marca | footer | `<a>` | `#landing-main` |
| Privacidade / Termos de uso | footer | `<a>` | `/privacidade`, `/termos` (páginas legais via `legal-layout.tsx`) |
| Menu (hambúrguer) | mobile ≤820px | `<details>/<summary aria-label="Abrir navegação">` | abre nav móvel |

Contrato de wiring: `LandingPage({ onLogin, onSignUp })` é montada por `frontend/app/product-app.tsx:89` e `:91` (enquanto a sessão carrega e quando não há usuário em `/`). Usuário autenticado em `/` é redirecionado à primeira organização (`product-app.tsx:48`). **A modernização deve manter essa assinatura de props e os dois handlers.**

## 6. Interações e estados atuais

- Prévia: 3 estados por `aria-pressed`; thread com `aria-live="polite"` e `key={activeCase}` (remonta a cada troca).
- FAQ: `<details>` nativo; chevron gira 180° (`transition 180ms`).
- Hover: links sublinham em verde; botão primário escurece (`160ms`). Foco: outline âmbar 3px.
- Mobile: menu `<details>` ≤820px; breakpoints em 960, 820, 720, 520 px.
- `prefers-reduced-motion`: zera transições/animações. Não há animações de scroll, vídeo ou mídia na LP hoje.
- Sem overflow horizontal em 1440 e 390 px. Altura da página: 4939 px (desktop 1440) e 5994 px (mobile 390).

## 7. Limites de arquivos — LP versus app

| Arquivo | Classe | Pode mudar no redesign da LP? |
| --- | --- | --- |
| `frontend/app/landing-page.tsx` | **LP exclusiva** | Sim (manter props, CTAs, âncoras, copy) |
| `frontend/app/landing.css` | **LP exclusiva** (escopo `.landing-*`) | Sim |
| `frontend/app/layout.tsx` | compartilhado (metadata global + `<html>`) | Só metadata/fontes com cuidado; afeta todas as rotas |
| `frontend/app/brand.tsx`, `brand.css` | **compartilhado** (LP, telas de entrada, workspace) | Não alterar — sobrescrever dentro de `.landing-page` se necessário |
| `frontend/app/provider-logo.tsx` | compartilhado (LP + integrações do app) | Não alterar |
| `frontend/app/globals.css` | compartilhado (Tailwind/shadcn, auth-card, app) | Não alterar |
| `frontend/app/product-app.tsx` | **app** (roteador de sessão; monta a LP) | Não alterar (wiring dos CTAs vive aqui) |
| `frontend/app/product/auth-screens.tsx` (SignIn em `/login`) | app / entrada | Fora do escopo |
| `frontend/app/page.tsx`, `login/page.tsx` | rotas | Não alterar |
| `frontend/app/privacidade`, `termos`, `legal-layout.tsx`, `legal.css` | site público (legal) | Fora do escopo salvo pedido; destinos devem continuar funcionando |
| `frontend/public/*` | estáticos | Novos assets só após aprovação; nenhum gerado nesta fase |

## 8. Baseline visual (capturado sem alterar funcionalidade)

Pasta: `specs/work-items/lp-chat-modernization-20261002/baseline/` — Playwright 1.59 (chromium headless) contra `http://localhost:3000/`.

- `desktop-00-fullpage.png`, `desktop-01-fold.png` (1440×900)
- `desktop-02-demo-case-{1,2,3}.png`, `desktop-03-faq-open.png`, `desktop-05-login-destination.png`
- `mobile-00-fullpage.png`, `mobile-01-fold.png` (390×844 @2x), `mobile-02-demo-case-{1,2,3}.png`, `mobile-03-faq-open.png`, `mobile-04-menu-open.png`
- `baseline-dom.json` — inventário de `a/button/summary` visíveis por viewport + destinos de navegação dos CTAs
- `baseline-contact-sheet.pdf` — folha de contato (artefato visual independente em PDF; sem Canvas)

Leitura crítica do baseline para a fase de direção (diagnóstico, não decisão):

- Hero 100% tipográfico; a prévia do produto só aparece abaixo da dobra.
- Tipos de sistema (Georgia/Arial) e paleta papel + verde único: sóbrio, mas genérico e "editorial-luxo" para um SaaS de IA.
- Estrutura linear clássica (hero → prévia → integrações → rotina → como funciona → FAQ → CTA), com duas seções de "3 passos" quase redundantes (Rotina e Como funciona).
- O ativo mais forte é a **prévia interativa do chat com fontes** — candidato natural a centro da nova direção ("chat-first"), coerente com o nome do work-item.

## 9. Evidência Git

```
$ git status --short          # antes de criar a branch, em main@a43dbdd
?? artifacts/developer-page/
?? "graphify-out/.graph.html 2.stale"
?? "graphify-out/.graph.tmp 2.json"
?? "specs/research/integracoes-analise-2026-09-29 2.md"
$ git checkout -b design/lp-chat-modernization-20261002
Switched to a new branch 'design/lp-chat-modernization-20261002'
$ git rev-parse HEAD
a43dbdd09ae1673adc088b84a4a56b5ea8665f5f
```

- Branch não existia (`git branch -a --list '*lp-chat*'` vazio); nenhum sufixo foi necessário.
- Os 4 itens não rastreados do humano foram preservados intactos; sem stash, reset, commit ou push.
- Únicas escritas desta fase: o diretório `specs/work-items/lp-chat-modernization-20261002/`. Nenhum arquivo de código alterado.

## 10. Próximos passos (gate H2)

1. Direção/styleboard (PDF) com conceito estrutural, tipografia, paleta e motion — com base neste baseline.
2. Aprovação humana do styleboard (H2).
3. Só então: implementação restrita a `landing-page.tsx` + `landing.css` (e, se aprovado, fontes/metadata em `layout.tsx`), preservando §4–§5.
