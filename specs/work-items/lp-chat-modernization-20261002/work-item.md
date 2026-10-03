# lp-chat-modernization-20261002 - Modernização da LP pública (chat-first)

**Status:** validating — H2 aprovado pelo humano (opção 1: direção A / Contexto vivo) em 2026-10-02. Implementação concluída por pane-361; aguarda QA independente. Sem commit/push.

## Source and outcome

- Source specification: `specs/001-mvp-document-intelligence.md` §102-103 (identidade e landing); M31 (`specs/work-items/M31-landing-integrations.md`).
- User outcome: LP pública modernizada, com direção visual nova, preservando público, CTAs, copy comercial, marca e destinos.
- Non-goals: app autenticado (fase posterior); mudança de preços (não existem); mudança de auth/rotas; mídia gerada nesta fase.
- Baseline: [brief-baseline.md](brief-baseline.md) + `baseline/`.

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |
| Escopo só LP/site público | humano | aprovado | pedido da Missão 37 |
| Preservar CTAs/destinos/copy/marca | humano | aprovado | brief-baseline §4-§5 |
| Direção visual livre | humano | aprovado | — |
| Styleboard (conceito, tipo, paleta, motion) | humano | **aprovado H2 — opção 1, A / Contexto vivo** | `direction/STYLEBOARD.pdf`, `direction/DESIGN.md` |
| Webfonts | humano | aprovado: Manrope (display) + IBM Plex Sans (UI/corpo), self-hosted via `@font-face` em `landing.css` | arquivos em `frontend/public/landing/fonts/` (OFL) |
| Mídia | humano | só imagem decorativa I-01 (`frontend/public/landing/document-context.webp`, worker de mídia paralelo); sem vídeo/áudio | `direction/assets-policy.md` |
| Limites de arquivo | humano | só `landing-page.tsx`, `landing.css`, `frontend/public/landing/`, testes e docs da missão | pedido H2 |

## Ready checklist

- [x] Acceptance criteria written in Given/When/Then form. (seção GWT abaixo)
- [x] Owning module, API/data impact and failure states identified. (frontend LP; sem API/dados)
- [x] Authorization, tenant and workspace-folder impact assessed. (nenhum: página pública; wiring de auth intocado)
- [x] Performance and observability impact assessed. (2 woff2 subset ~70 KB, `font-display: swap`; 1 imagem decorativa opcional; motion CSS/IO leve; sem rede externa)
- [x] Protected decisions approved or marked not applicable. (H2 aprovado)


## Style-lock H2 (A / Contexto vivo)

- Conceito estrutural: **Product UI Slate** — hero e `#produto` dividem a primeira dobra (≈42/58); a prova é a própria UI de chat com fontes, em texto vivo.
- Superfície clara `#F5F7F4`, tinta `#142B25`, verde da marca `#1C6052` (hover `#124B3F`), wordmark `#243B35`, painel `#FFFFFF`, fontes `#EAF2EC`, texto secundário `#51635A`, divisor `#D5DFD7`, borda de controle `#718379`, foco `#965B0D` (3 px, offset 3 px), lima `#D9F279` só como marcador gráfico.
- Tipos: Manrope 650 títulos (H1 34–56 px, tracking −0.035em); IBM Plex Sans 400/500/600 UI e corpo (16/1.55; fontes 14; avisos 13). Marca permanece Arial + Layers3 (componente `Brand`). `em` vira sans verde sem itálico.
- Motion (motion-plan.md): hover 140 ms cor/borda; FAQ chevron 180 ms; troca de caso ≤180 ms opacity; reveal inferior 240 ms / 8 px / IO once, stagger 40 ms; `prefers-reduced-motion` zera tudo. Sem autoplay, typewriter, parallax, ticker ou motion.css da referência.
- Proibido: copy nova, preço, integrações extras, chat rasterizado, gradiente roxo/azul, editar arquivos compartilhados.

## Critérios Given/When/Then (H2)

1. **Dado** visitante anônimo em `/` (1440×900), **quando** a LP carrega, **então** H1, descrição, CTAs e nota literais aparecem à esquerda e uma única ProductPreview com `Resposta com fontes` ativo mostra pergunta, resposta e a primeira fonte na dobra.
2. **Dado** 390×844, **quando** a LP carrega, **então** a prévia vem logo após o hero, sem seção intermediária, e os três casos quebram linha sem truncar.
3. **Dado** o caso default, **quando** `Resposta com fontes` está pressionado, **então** aparecem três fontes com provedor e `Ver mais 2 documentos`.
4. **Dado** `Com menção @`, **quando** acionado, **então** `Arquivo: Escopo do projeto.pdf` e o escopo `Google Drive` ficam visíveis e `aria-pressed` muda.
5. **Dado** `Sem evidência suficiente`, **quando** acionado, **então** a resposta negativa literal aparece sem `Documentos utilizados`.
6. **Dado** `Criar conta`/`Começar com o Arquivio`/`Criar minha conta`, **quando** clicados, **então** navegam para `${API_BASE}/auth/login?screen_hint=sign-up`.
7. **Dado** `Entrar`/`Já tenho uma conta`, **quando** clicados, **então** vão para `/login`.
8. **Dado** nav desktop/mobile, skip link, marcas e legal, **quando** acionados, **então** destinos `#produto #integracoes #como-funciona #perguntas #landing-main /privacidade /termos` funcionam.
9. **Dado** teclado, **quando** o usuário navega com Tab, **então** todo controle mostra foco âmbar visível; menu mobile e 7 FAQ abrem com Enter/Espaço.
10. **Dado** 375/768/1024/1440, **quando** a página é percorrida, **então** não há overflow horizontal nem copy cortada.
11. **Dado** `prefers-reduced-motion: reduce`, **quando** estados mudam, **então** nada depende de animação e todo conteúdo está visível.
12. **Dado** ausência do asset I-01, **quando** a LP carrega, **então** o layout permanece íntegro sem imagem quebrada; com o asset, ele ocupa ≤12% da área de Rotina e é `aria-hidden`.
13. **Dado** o DOM final, **quando** comparado com `copy/COPY.md`, **então** não há string comercial nova, preço ou integração adicional.

## Ownership

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | brief-baseline.md (pane-361) |
| Implementation owner (pane-361) | `frontend/app/landing-page.tsx`, `frontend/app/landing.css`, `frontend/public/landing/fonts/` | LP A implementada |
| Test engineer (pane-361) | `frontend/tests/landing-contract.test.mjs` | contrato estático de copy/wiring/escopo CSS |
| Media worker (paralelo) | `frontend/public/landing/document-context.webp`, `media/ASSETS.md` | slot I-01 decorativo |
| Feature validator | Read-only | gate independente |

## Acceptance criteria and test matrix

| Criterion | Test layer | Evidence |
| --- | --- | --- |
| Dado visitante anônimo em `/`, quando clica em Criar conta / Começar com o Arquivio / Criar minha conta, então navega para `${API_BASE}/auth/login?screen_hint=sign-up` | navegador (Playwright) | baseline-dom.json (antes) |
| Dado visitante, quando clica em Entrar / Já tenho uma conta, então vai para `/login` | navegador | idem |
| Âncoras `#produto #integracoes #como-funciona #perguntas #landing-main` e links `/privacidade` `/termos` existem e funcionam | navegador | idem |
| Copy comercial, FAQ e 4 integrações preservadas literalmente | teste estático | brief-baseline §4 |
| Prévia mantém os 3 casos ilustrativos e o selo "Prévia ilustrativa"/"Exemplos fictícios" | navegador | baseline/*demo-case* |
| Sem overflow horizontal em 375/768/1024/1440; reduced-motion respeitado | navegador | — |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `git checkout -b design/lp-chat-modernization-20261002` | ok, HEAD a43dbdd | pane-361 | — |
| Playwright baseline (`localhost:3000`, 1440 e 390) | 14 PNG + DOM json, sem overflow-x | pane-361 | — |
| `npx tsc --noEmit -p .` | exit 0 | pane-361 | pendente QA |
| `npm run lint` | exit 0 | pane-361 | pendente QA |
| `node --test tests/landing-contract.test.mjs` | exit 0, 5/5 | pane-361 | pendente QA |
| `node --experimental-strip-types --test tests/*.test.mjs` | exit 1, 79/80 — falha preexistente `answer-markdown` (Node 22.16 não importa `.tsx`) | pane-361 | pendente QA |
| `npm run build` | exit 0 | pane-361 | pendente QA |
| Playwright QA contra build próprio `http://127.0.0.1:5181` (375/390/768/1024/1440) | exit 0; 0 overflow, 0 console, 0 contraste < AA, 0 alvos < 44 px, CTAs/rotas/âncoras/casos/FAQ/menu/teclado/reduced-motion/no-JS ok | pane-361 | pendente QA |
| `graphify update .` | exit 0 | pane-361 | — |

## Implementação (pane-361)

- Arquivos: `frontend/app/landing-page.tsx`, `frontend/app/landing.css`, `frontend/public/landing/fonts/*` (woff2 subset + OFL), `frontend/tests/landing-contract.test.mjs`. Asset I-01 `frontend/public/landing/document-context.webp` entregue pelo worker de mídia e integrado (slot opcional, `aria-hidden`, renderiza só após `onload`).
- Evidência: [evidence/README.md](evidence/README.md) (matriz de preservação, exit codes, QA), `evidence/after/`, `evidence/before-after.pdf`. Migração futura: [design-to-app.md](design-to-app.md).
- Desvio de meta registrado: dobra mobile 390×844 mostra hero, casos, shell e pergunta; resposta/1ª fonte ficam logo abaixo (meta DESIGN era inferred; nenhuma copy cortada).
- Rodada 2 pós-QA: grid 42/58 desde 1024 px; mobile retunado (resposta inicia em y799 na viewport 390×844, 1ª fonte y893 vs meta y810 — tradeoff documentado); arte I-01 sem sobreposição; avisos ≥13 px. Revalidação independente final: F-207 `verificado`; F-206 `reaberto` como residual P2. Evidência: `evidence/README.md#rodada-2`, `evidence/round2/` e `review/round2/qa-report.md`.

## Validator report

- Blocking: nenhum (P0: 0, P1: 0).
- Important: um residual P2, F-206 reaberto — primeira fonte em y893, 83 px além da meta inferida y810; resposta inicia em y799. O piloto aceita o polish restante, sem terceira rodada de implementação.
- Suggestions: F-207 verificado — grade 42/58 e fonte y594 em 1024×900.
- Independent evidence: `review/round2/qa-report.md` e `review/round2/evidence/` (visita sem mocks à URL de produção após rebuild fresh).
- Gate decision: **PASS técnico** com P2 residual aceito; H4, aprovação humana final, continua pendente.

## Preview persistente (H3)

- URL: **http://127.0.0.1:5181/**, servida pelo container Docker dedicado `arquivio-lp-preview-20261002` (`Dockerfile.production`, `VITE_API_BASE_URL=/api`, `API_UPSTREAM_URL=http://host.docker.internal:8000`, `--restart unless-stopped`). Imagem original `arquivio-lp-preview:20261002`; tag atual após re-review: `arquivio-lp-preview:motion-review-20261003`. Não depende de pane nem de sessão.
- Parar: `docker stop arquivio-lp-preview-20261002`. Detalhes, ID, verificação e comparação de output em [evidence/preview-service.md](evidence/preview-service.md).
- O preview anterior (`npm run start` preso a um pane) foi substituído; os previews registrados em rodadas anteriores ficam obsoletos.

## Extensão H4 — motion LP + cinco modais existentes (aprovada pelo dono, implementada por pane-361)

- **Aprovação:** dono aprovou a extensão de motion para a LP e para os cinco modais existentes do app (M1 Sincronizações, M2 Integração ativa, M3 Tour, M4 Chave de API, M5 menu móvel). Contrato e plano: `motion-extension/{INVENTORY,MOTION-SPEC,implementation-plan}.md`. A re-review técnica independente deu PASS; **H4 (nova entrega final) ainda aguarda aprovação humana**.
- **Style-lock motion:** só visual, entrada de 180 a 220 ms (200 por padrão), delay 0, opacity inicial .92 (nunca 0 em texto) e translate curto: Y4 nos casos e no FAQ, Y−4 no menu, Y6 nos modais, X−12 no sheet. Scale .99 apenas no M2. Easing de entrada `cubic-bezier(.2,.8,.2,1)`, de saída `(.4,0,1,1)`. Saída animada só no M5 (180 ms, Presence existente); M1 a M4 fecham na hora, como antes. Hover/press ≤140 ms; reveal 240 ms + stagger de 20 a 40 ms, total ≤280 ms. Sem bounce, blur, glow, parallax, typing ou animação de dados/polling/erros. Reduced-motion zera tudo, no carregamento e em mudança dinâmica.
- **Arquivos:** `landing.css`, `landing-page.tsx` (hook de reveal), `interface-motion.css/.ts` (novos), `product/library-screen.tsx`, `product/integrations-screen.tsx`, `conversation-tour.tsx`, `access-settings.tsx`, `mobile-nav.tsx`, `components/ui/sheet.tsx` (prop opt-in) e `tests/interface-motion.test.mjs` (novo). Intocados: `globals.css`, `brand.*`, `provider-logo`, `product-app`, `modal-dismiss`, API/auth/backend, primitives sem uso e os 9 confirms nativos.

### Critérios de aceite H4 (Given/When/Then) e estado

| # | Critério | Evidência |
| --- | --- | --- |
| H4-1 | Dado um caso da LP, quando o usuário o troca (inclusive 20× rápido), então o conteúdo e o `aria-pressed` mudam na hora, a thread entra em 200 ms e só o último caso permanece | público ✔ |
| H4-2 | Dado FAQ/menu, quando abre, então o toggle nativo é imediato e o conteúdo assenta em 200 ms; ao fechar, oculta na hora; funciona sem JS | público ✔ |
| H4-3 | Dadas as seções inferiores, quando reveladas, então terminam em ≤280 ms e o foco por teclado as revela de imediato | público ✔ |
| H4-4 | Dado M1–M4, quando abrem, então abertura e foco são imediatos e só o painel interno entra em 200 ms (root sem transform); quando fecham, fecham na hora, como antes | fixture ✔ |
| H4-5 | Dado M5, quando abre ou fecha, então entra em 200 ms e sai em 180 ms via Presence; navegação e ações não esperam a saída; o default do Sheet fica intacto | fixture + source ✔ |
| H4-6 | Dado busy/pending, quando há Escape, fora, X ou clique duplo, então as regras e o número de requests ficam iguais ao baseline | fixture ✔ |
| H4-7 | Dado M5→M3, quando o tour abre a partir do menu, então o foco fica no tour | fixture ✔ |
| H4-8 | Dado reduced-motion, inicial ou dinâmico, quando há qualquer transição, então não há animação e o estado final aparece de imediato | público + fixture ✔ |
| H4-9 | Dado o segredo do M4, quando o modal fecha, então o segredo sai do DOM na hora, sem retenção para animação | fixture ✔ |
| H4-10 | Dados copy, CTAs, rotas, dobra e layout aceitos no QA, quando a página é comparada, então nada mudou além do motion (contrato LP 5/5, geometria) | source + público ✔ |

Evidência do build original: `motion-extension/evidence/build/README.md` (80/80 checks de browser, 98/98 testes, PDF `MOTION-EVIDENCE.pdf`). O README foi corrigido: os grupos brutos somam 26 públicos + 53 fixtures + 1 rede = 80, não 61 fixtures. A re-review independente acrescentou 12 checks adversariais e passou 92/92. Limites baseline M4 e M1 foram registrados separadamente em F-208/F-209; F-210 registra o limite preexistente do ModalOverlay.

### Re-review independente final — pane-374, 2026-10-03

- **Parecer:** PASS técnico da extensão; P0 0, P1 0 e P2 de motion 0. Três achados P2 preexistentes estão em F-208/F-209/F-210. No workstream completo, F-206 continua como residual P2 aceito; F-207 segue verificado. Não abrir nova rodada pela meta parcial da dobra mobile.
- **Lente de motion/design:** pass. Grid 42/58 computado em 1024×900 (fonte y594); I-01 sem interseção nos cinco tamanhos; LP e M1–M5 respeitam os ciclos/timings. Em 390×844, resposta y799 e primeira fonte y893 versus meta y810; ganho confirmado, meta ainda parcial, tradeoff de legibilidade/copy preservado.
- **Lente de acessibilidade/ciclo de vida:** pass técnico para reduzido inicial/dinâmico, no-JS, foco/restituição, teclado, dismiss, resize M5 390→1024 e alvos ≥44 px. F-210 mantém a limitação ModalOverlay separada; teste manual com leitor de tela pendente.
- **Lente funcional/conteúdo/dados:** pass. Copy literal, 3 casos, 7 FAQs, 4 integrações, CTAs/âncoras, API/busy/permissões verificados por source-contract e fixtures fail-closed. Público anônimo testado primeiro sem intercept: `/api/session` real 200 `null`.
- **H4:** aprovação humana final continua pendente. Relatório e provas: `motion-extension/review/round2/qa-report.md` e `motion-extension/review/round2/evidence/`.
- **Preview atual:** `http://127.0.0.1:5181/`, container dedicado, imagem `arquivio-lp-preview:motion-review-20261003`, `/api` same-origin e upstream local real. Detalhes da atualização em `evidence/preview-service.md`.

## Frontend principal (localhost:3000) atualizado — 2026-10-03

- `document-ai-frontend-1` recriado só com `docker compose build frontend` + `docker compose up -d --no-deps frontend` (sem down, volumes ou backend). Container `95da528d03a4`, imagem `arquivio-frontend:local` = `sha256:8b90af61…`, iniciado 2026-10-03T14:55:06Z. Código idêntico à árvore atual (153 arquivos com sha256 iguais). Navegador real em `http://localhost:3000/` 18/18. Detalhes, antes→depois e parada: [evidence/main-frontend-rebuild.md](evidence/main-frontend-rebuild.md). H4 final continua aguardando o humano.
