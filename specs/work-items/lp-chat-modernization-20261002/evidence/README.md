# Evidência — implementação LP direção A (pane-361, 2026-10-02)

Branch `design/lp-chat-modernization-20261002` (base `main@a43dbdd`). Sem commit/push. Alterações humanas preexistentes intocadas.

## Preview

- **Persistente (build de produção, servidor próprio):** `http://127.0.0.1:5181/` — `cd frontend && npm run build && npm start -- --port 5181` (Wrangler/workerd, `nohup`, log em `preview-5181.log`). Snapshot do build; após nova edição, rebuild + restart.
- O Docker `:3000` (baseline) não tem bind mount → **não** reflete este código. Havia outro `vinext dev` alheio em `:3100` (PID 34573, iniciado 11:11, não é desta missão, não foi tocado; usado só para iteração visual rápida).
- A API local só libera CORS para `http://localhost:3000`. No QA em `:5181` a chamada `GET http://localhost:8000/me` foi interceptada no Playwright com `200 null` (visitante anônimo, o mesmo efeito do `401` que a API devolve em `:3000`). Sem isso, o app mostra o alerta de sessão do `product-app.tsx` (fora do escopo da LP).

## Comandos e exit codes

| Comando (em `frontend/`) | Exit | Log |
| --- | --- | --- |
| `npx tsc --noEmit -p .` | 0 | `tsc.log` |
| `npm run lint` | 0 | `lint.log` |
| `npx eslint app/landing-page.tsx` | 0 | `eslint-landing.log` |
| `node --test tests/landing-contract.test.mjs` | 0 (5/5) | — |
| `node --experimental-strip-types --test tests/*.test.mjs` | 1 (79/80) | `node-test.log` |
| `node --test tests/*.test.mjs` (sem flag) | 1 | `node-test-plain.log` |
| `npm run build` | 0 | `build.log` |
| Playwright QA `qa.cjs` contra `:5181` | 0 | `after/qa-report.json` |
| `graphify update .` (raiz) | 0 (6697 nós, 19379 arestas) | — |

A única falha da suíte é `tests/answer-markdown.test.mjs`: `ERR_UNKNOWN_FILE_EXTENSION ".tsx"` ao importar `app/answer-markdown.tsx` com Node 22.16 local — limitação de ambiente preexistente, arquivo não tocado. Sem a flag, todos os testes que importam `.ts` falham pelo mesmo motivo (Node < 22.18).

## Resultados do navegador (`after/qa-report.json`)

| Verificação | 375 | 390 | 768 | 1024 | 1440 |
| --- | --- | --- | --- | --- | --- |
| Overflow horizontal | não | não | não | não | não |
| Fontes self-hosted carregadas | sim | sim | sim | sim | sim |
| Contraste < AA (texto renderizado) | 0 | 0 | 0 | 0 | 0 |
| Alvos < 44 px | 0 | 0 | 0 | 0 | 0 |
| Texto da prévia oculto | 0 | 0 | 0 | 0 | 0 |
| FAQ aberto por teclado (Enter/Espaço) | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 |
| Botões de caso truncados | 0 | 0 | 0 | 0 | 0 |
| Pergunta / 1ª fonte (y px) | 791 / 1014 | 791 / 1014 | 793 / 993 | 828 / 1003 | **375 / 575** |
| Arte I-01 (área da seção) | 8,9% | 9,2% | 4,1% | 2,9% | 8,2% (320×240) |

- Dobra desktop 1440×900: hero + prévia única; pergunta (y375), resposta (y475) e 1ª fonte (y575) visíveis — meta DESIGN (≤y620) atingida. Mobile 390×844: hero completo + título/casos + shell + pergunta na dobra; resposta e fontes logo abaixo (meta "inferred" parcialmente atingida; nenhuma copy foi cortada ou reduzida para caber).
- Casos: `aria-pressed` [t,f,f]→[f,t,f]→[f,f,t]; 3 fontes + "Ver mais 2 documentos" / 1 fonte / 0 fontes sem bloco; `aria-live="polite"`.
- CTAs: Criar conta (header), Começar com o Arquivio, Criar minha conta e Criar conta (menu móvel) → `http://localhost:8000/auth/login?screen_hint=sign-up`. Entrar (header e menu) e Já tenho uma conta → `/login`. Privacidade → `/privacidade` (h1 "Política de Privacidade"); Termos → `/termos` ("Termos de Uso").
- Âncoras: `#produto #integracoes #como-funciona #perguntas` com alvo no topo (≤16 px); `#landing-main` existe; menu móvel → `#perguntas`.
- Teclado: ordem skip link → marca → nav → Entrar → Criar conta → CTAs → casos…; foco `solid 3px rgb(150,91,13)` em todos.
- Menu móvel abre por Enter, 6 itens (4 âncoras + Entrar + Criar conta).
- `prefers-reduced-motion: reduce`: 0 `.is-pending`, animação do thread `none`, transição `0s`, 0 seções ocultas. Sem JS: H1 presente, 0 seções ocultas.
- Console: 0 erros/avisos; 0 requests falhos (excluída a API :8000).
- Sem asset (`document-context.webp` → 404 forçado): slot não renderiza, 0 `<img>`, sem overflow (`after/after-1440-story-without-asset.png`).

## Artefatos

- `after/` — 36 PNG: fold/fullpage/casos/FAQ por viewport, menu, foco, skip link, destino login, fallback sem asset.
- `before-after.pdf` — antes (baseline) × depois, sem Canvas.
- Baseline: `../baseline/` (+ `baseline-contact-sheet.pdf`).

## Matriz de preservação

| Contrato | Antes | Depois | Prova |
| --- | --- | --- | --- |
| Assinatura `LandingPage({ onLogin, onSignUp })` | ✓ | ✓ idêntica | teste `landing-contract` |
| `product-app.tsx` wiring (linhas 89/91) | ✓ | intocado | `git diff main` vazio |
| Entrar ×2 + Já tenho uma conta → onLogin → `/login` | ✓ | ✓ | QA login/mobileLogin |
| Criar conta ×2 + Começar + Criar minha conta → onSignUp → `/auth/login?screen_hint=sign-up` | ✓ | ✓ | QA signup/mobileSignup |
| Skip link + 2 marcas → `#landing-main` | ✓ | ✓ | QA controls/focus |
| Nav desktop e móvel → 4 âncoras | ✓ | ✓ | QA anchors |
| Legal → `/privacidade`, `/termos` | ✓ | ✓ | QA legal |
| 3 casos, ordem, default, `aria-pressed`, `aria-live` | ✓ | ✓ | QA cases + screenshots |
| Estúdio Aurora, Prévia ilustrativa, Exemplos fictícios | ✓ | ✓ visíveis em todo viewport | QA cases |
| Biblioteca/Busca/composer/hints (texto integral) | ocultos ≤960 px no baseline | **visíveis em todos** | QA hiddenPreviewText = 0 |
| 4 integrações + "4 fontes" | ✓ | ✓ | teste + screenshot |
| Rotina e Como funciona distintas, nota de compartilhamento visível | ✓ | ✓ (nota com destaque maior) | screenshot |
| FAQ 7 `<details>` literais | ✓ | ✓ | teste + QA faqOpen |
| Copy comercial literal, sem preço/plano/integração nova | ✓ | ✓ | teste `landing-contract` (87 literais + 12 nomes acessíveis) |
| Arquivos protegidos (layout, globals, brand, provider-logo, product-app, auth, legal, backend) | — | intocados | `git diff --quiet main -- …` = 0 |
| CSS escopado `.landing-*` (exceto `.arquivio-brand` herdado) | parcial | ✓ | teste `landing-contract` |

## Rodada 2 — acabamento pós-QA (F-206, F-207), pane-361

Única rodada. Alterado só `frontend/app/landing.css`; `landing-page.tsx` está inalterado desde a rodada 1. Preview na configuração documentada pelo reviewer, **sem mocks nem intercept de sessão**: `VITE_API_BASE_URL=/api npm run build` e depois `API_UPSTREAM_URL=http://127.0.0.1:8000 npm run start -- --port 5181`. Resultado: `http://127.0.0.1:5181/` 200 e `/api/session` 200 `null`.

| Comando (em `frontend/`) | Exit | Log |
| --- | --- | --- |
| `npx tsc --noEmit -p .` | 0 | `round2/tsc.log` |
| `npm run lint` | 0 | `round2/lint.log` |
| `node --test tests/landing-contract.test.mjs` | 0 (5/5) | `round2/landing-contract.log` |
| `node --import tsx --test tests/*.test.mjs` | 0 (88/88) | `round2/node-test.log` |
| `git diff --check` (LP) | 0 | — |
| `VITE_API_BASE_URL=/api npm run build` | 0 | `round2/build.log` |
| QA Playwright `qa2.cjs` (sem mock; só o destino `/api/auth/login` é abortado para registrar a navegação) | 0 | `round2/after/qa-report.json` |
| Geometria `geo.cjs` (375×667, 390×844, 768, 1024×900, 1024×768, 1280, 1440) | 0 | `round2/geometry.json` |
| `graphify update .` | 0 | — |

| Viewport | Grade | Resposta y (antes→depois) | 1ª fonte y (antes→depois) | Arte × texto |
| --- | --- | --- | --- | --- |
| 375×667 | 1 col | 873→811 | 1014→905 | 0 |
| 390×844 | 1 col | 873→**799** (na dobra) | 1014→**893** | 0 |
| 768×1024 | 1 col | 894 | 993 (na dobra) | 0 (arte abaixo do texto) |
| 1024×900 | **42/58 (386/534)** | 887→494 | 1003→**594** | 0 |
| 1440×900 | 42/58 (517/715) | 475 | 575 | 0 |

Em todos os viewports: sem overflow, sem texto cortado ou fora da viewport, chat ≥16 px, avisos ≥13 px ("Prévia ilustrativa", nota de escopo e limite da busca subiram de 12 para 13 px), alvos ≥44 px, contraste AA, 7/7 FAQ por teclado, menu móvel, foco de 3 px em toda a sequência, três casos (`aria-pressed`, 3/1/0 fontes), reduced-motion e no-JS com tudo visível, console e requests sem falhas. Os 31 controles são idênticos ao baseline (tag, texto e href). Cadastro → `/api/auth/login?screen_hint=sign-up` (API_BASE `/api`); login → `/login`; legal e âncoras ok. Sem o asset, o slot não renderiza.

Tradeoff F-206: a 1ª fonte em 390×844 ficou em y893, contra a meta inferida y810 (−121 px ganhos, 83 px restantes). Ir além exigiria H1 < 34 px, chat < 16 px ou esconder ou reordenar controles e copy, o que o contrato proíbe.

`before-after.pdf` foi regenerado: o "depois" agora é a rodada 2, com a dobra 1024, a dobra 390 da rodada 1 como comparação e a seção Rotina em 768/1024.

## Revalidação final independente (pane-366, 2026-10-03)

- Rebuild fresh `VITE_API_BASE_URL=/api npm run build` (exit 0) e servidor de produção em `:5181` com `API_UPSTREAM_URL=http://127.0.0.1:8000`. A primeira visita independente a `/` foi sem mocks/intercept: document e `/api/session` 200, `null` anônimo, console/page/request errors vazios; fontes WOFF2 e I-01 200.
- Geometria Playwright independente: 1024×900 grid 386.391/533.609 (42/58), fonte y594; F-207 `verificado`. A 390×844 resposta começa em y799 e primeira fonte y893, 83 px além da meta y810; ganho de 121 px em relação à rodada 1, com chat 16 px, avisos 13 px e todos os alvos ≥44 px. F-206 `reaberto` no mesmo ID como P2 residual. O piloto aceita esse polish e não prevê terceira rodada.
- I-01 não intercepta texto em 375/390/768/1024/1440; não há overflow. Fontes locais carregam; reduced-motion e conteúdo sem JS permanecem disponíveis. Os 31 controles correspondem à sequência Round 2; casos, menu, FAQ, âncoras, CTAs e rotas públicas foram revalidados.
- Checks fresh: TSC 0, lint 0, `landing-contract` 5/5, suíte correta `node --import tsx --test tests/*.test.mjs` 88/88, `git diff --check` 0; protected app/backend diff 0. Nenhuma implementação foi alterada pelo reviewer.
- Navegações reais para `/login`, `/privacidade` e `/termos` responderam 200 com os H1s esperados. Nessas páginas públicas secundárias surgiu console error de prefetch RSC (`link-BzKbLNQz.js`, `TypeError: te is not a function`); `/` permaneceu limpo. Os arquivos dessas rotas não mudaram neste branch e o erro não impediu renderização/destino. Registrado como observação de runtime fora do escopo LP, sem novo finding.
- H2 A segue aprovado; **H4 — aprovação humana final — pendente**. Ver [re-review final](../review/round2/qa-report.md) e evidências fresh em `../review/round2/evidence/`.
