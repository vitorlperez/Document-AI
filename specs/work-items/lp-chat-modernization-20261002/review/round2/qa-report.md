# Re-review final — Arquivio LP direção A / Contexto vivo

**Data:** 2026-10-03 · **Branch:** `design/lp-chat-modernization-20261002` · **Base:** `a43dbdd09ae1` · **Reviewer:** pane-366

## Parecer

**PASS técnico — P0: 0 · P1: 0 · P2 total: 2 (1 verificado, 1 residual reaberto).** F-207 foi reproduzido e verificado corrigido. F-206 melhorou e a resposta começa na dobra mobile, mas a primeira fonte continua 83 px abaixo da meta inferida y810; o mesmo ID foi reaberto como polish P2. O piloto aceita o residual e não haverá uma terceira rodada de implementação nesta revisão.

H2 direção A está aprovada conforme briefing. **H4 — aprovação humana final — continua pendente**; este parecer técnico não registra aprovação humana.

## Ambiente e preview sem mocks

A revisão reconstruiu o build atual com `VITE_API_BASE_URL=/api npm run build` (exit 0) e iniciou o servidor de produção em `http://127.0.0.1:5181/` com `API_UPSTREAM_URL=http://127.0.0.1:8000`. O build foi concluído antes da primeira visita; os screenshots e medições vêm deste build da rodada 2. O Docker `:3000` não foi usado.

A primeira visita ao `/` foi sem mocks ou interceptação. Documento e `/api/session` responderam 200; a sessão anônima foi `null`; a homepage teve zero console errors, page errors ou requests falhos. Os dois WOFF2 locais e `document-context.webp` responderam 200. O cURL fresh também confirmou `/` e `/api/session` em HTTP 200. Evidência: [`clean-preview-round2.json`](evidence/clean-preview-round2.json) e [`verdict-round2.json`](evidence/verdict-round2.json).

As quatro CTAs de cadastro foram testadas depois, isolando e abortando **somente** `/api/auth/login?screen_hint=sign-up` antes do serviço de autenticação. Isso confirma o destino do frontend, não o fluxo real de cadastro. Nenhuma credencial foi inserida; nenhuma conta ou mensagem foi criada/enviada.

**Nota de rotas secundárias:** `/login`, `/privacidade` e `/termos` responderam 200 e renderizaram os H1 esperados. Nessas rotas, a navegação real emitiu o erro de console `[vinext] RSC prefetch setup error: TypeError: te is not a function` em `link-BzKbLNQz.js:2:4491`; não houve page error e as páginas renderizaram. `/` permaneceu sem erros. Os arquivos dessas rotas e o runtime compartilhado não mudaram no diff da LP, por isso não atribuo esse aviso ao F-206/F-207 nem o conto como blocker desta entrega. Registro separado em [`route-targets-round2.json`](evidence/route-targets-round2.json) para não ocultar o resultado das CTAs/rotas.

## Lente 1 — direção A, UX e continuidade futura

- **F-207 PASS/verificado:** em 1024×900 o stage computa `386.391px 533.609px`, proporção 42/58 com gap de 40 px. A resposta começa em y494 e a primeira fonte em y594 (box termina y634), dentro da dobra de 900 px. A partir de 1024 px a composição aprovada aparece; 1440×900 também permanece 42/58, com resposta y475 e primeira fonte y575.
- **F-206 parcial/reaberto:** em 390×844 a resposta começa em y799, ganho de 74 px em relação a y873. O box tem 50 px e termina em y849, 5 px após a viewport: seu início está na dobra. A primeira fonte começa em y893 (ganho de 121 px frente a y1014), ainda 83 px além da meta DESIGN y810 e 49 px abaixo da borda da viewport. Não declaro a meta completa. A 375×667, resposta y811 e primeira fonte y905. A página rola normalmente e não corta copy.
- **Tradeoff F-206:** chat continua em 16 px, H1 em 34 px no mobile, avisos em 13 px e os três casos mantêm rótulos e alvos de 52 px. A geometria redutora que resta até y810 conflitua com esse contrato, CTA e componentes integrais. O piloto aceitou o polish residual após esta única re-review; não abro terceira rodada.
- I-01 não intersecta texto em nenhum viewport testado: 375×667 (213×159), 390×844 (222×166), 768×1024 (240×180), 1024×900 (320×240), 1440×900 (320×240). Fundo de imagem usa asset local; `aria-hidden` conforme contrato.
- As medidas independentes estão em `clean-preview-round2.json`; comparação de pixels de veredito: [`desktop 1024×900`](evidence/verdict-desktop-1024x900.png) e [`mobile 390×844`](evidence/verdict-mobile-390x844.png).

| Viewport | Grade | Resposta y | 1ª fonte y | Estado da dobra |
|---|---|---:|---:|---|
| 375×667 | 1 coluna | 811 | 905 | Nenhuma das duas cabe |
| 390×844 | 1 coluna | 799 | 893 | Início da resposta visível; fonte abaixo |
| 768×1024 | 1 coluna | 894 | 993 | Fonte começa na dobra; box termina em y1033 |
| 1024×900 | 386.391 / 533.609 px | 494 | 594 | Resposta e primeira fonte visíveis |
| 1440×900 | 517.438 / 714.562 px | 475 | 575 | Resposta e primeira fonte visíveis |

## Lente 2 — acessibilidade, responsividade e assets

- **PASS:** largura do documento igual à viewport, sem overflow horizontal nos cinco tamanhos acima. `smallTargets=[]` em todos: zero links, botões ou summaries abaixo de 44×44 px.
- **PASS:** resposta/chat medido em 16 px em todos os viewports. Avisos testados — nota do hero, selo “Prévia ilustrativa”, hint do composer, nota de escopo, limite da busca, legenda da prévia e aviso de compartilhamento — têm mínimo de 13 px. O mínimo global de fonte inclui micro-rótulos de 12 px fora desse conjunto de avisos.
- **PASS:** fontes Manrope e IBM Plex Sans são servidas localmente e foram carregadas; asset I-01 também respondeu 200. O estilo mantém fallback de sistema.
- **PASS:** reduced-motion deixou zero reveals ocultos ou transformados; duração de transição do CTA `0s`, animação do thread `none`. Sem JavaScript: H1, os três botões de caso e as sete disclosures FAQ continuam no documento.
- **PASS:** sete FAQ alternam com Enter/Espaço; menu móvel abre com Enter e fecha com Espaço, exibindo as quatro âncoras e as duas ações. `evidence/round2/after/qa-report.json` relata zero contraste abaixo de AA nas viewports e foco visível de 3 px; o CSS de foco permanece sem mudança.

## Lente 3 — conteúdo, ações, wiring e preservação

- **PASS:** os três casos renderizam as respostas esperadas com `aria-pressed`: 3 fontes no default, uma fonte no estado `@` (com `Arquivo: Escopo do projeto.pdf`), zero fontes no estado “Sem evidência suficiente”. A resposta negativa não tem bloco de fontes.
- **PASS:** as 7 FAQ e respostas completas aparecem quando abertas, incluindo Owner/Admin e a ressalva de permissões originais SharePoint. As quatro integrações são Google Drive, OneDrive, Notion e SharePoint.
- **PASS:** os 31 controles (tag, texto, href e estado `aria-pressed`) no DOM fresh correspondem à sequência validada na rodada 2. O teste de contrato passa 5/5 e cobre os 87 literais/aprovações de texto e os destinos públicos; nenhuma copy ou ação foi removida.
- **PASS:** cliques de âncora desktop para `#integracoes` e mobile para `#perguntas` chegaram ao destino existente. As demais âncoras foram conferidas contra elementos reais no DOM. Cadastro: as quatro ações apontam para `/api/auth/login?screen_hint=sign-up` (isolamento explicado acima); login: header, hero e menu carregam `/login` sem enviar dados. `/privacidade` e `/termos` carregam os destinos legais esperados.
- **PASS:** diff frente a `a43dbdd09ae1` contém apenas `frontend/app/landing-page.tsx` e `frontend/app/landing.css` entre arquivos rastreados de `frontend/backend`. `git diff --quiet` nas rotas/auth/layout/brand/globals/provider-logo/backend protegidos retornou exit 0. Assets e teste novos da LP são os esperados. Reviewer não alterou implementação; sem commit/push.

## Findings

| ID | Status final | P-level | Resultado fresh |
|---|---|---|---|
| [F-206](../../../../../TASK/items/F-206.md) | `reaberto` | P2, média | resposta começa y799; primeira fonte y893, 83 px além da meta y810. P2 residual explícito e aceito pelo piloto. |
| [F-207](../../../../../TASK/items/F-207.md) | `verificado` | P2, média | grade 42/58 desde 1024 px; fonte y594 na dobra 1024×900. |

**Contagem:** P0 0 · P1 0 · P2 total 2 (1 verificado, 1 residual reaberto) · blockers ativos 0.

## Checks e exit codes

Executados em `frontend/`, salvo quando a tabela indica o contrário.

| Comando | Resultado |
|---|---|
| `VITE_API_BASE_URL=/api npm run build` | exit 0; build usado no preview |
| `API_UPSTREAM_URL=http://127.0.0.1:8000 npm run start -- --port 5181` | servidor de produção iniciou e permaneceu ativo; URL `http://127.0.0.1:5181/` |
| Browser fresh sem mock: `/` e `/api/session` | HTTP 200/200; sessão `null`; console 0, page errors 0, request failures 0 |
| `npx tsc --noEmit -p .` | exit 0 |
| `npm run lint` | exit 0 |
| `node --test tests/landing-contract.test.mjs` | exit 0; 5/5 |
| `node --import tsx --test tests/*.test.mjs` | exit 0; 88/88 |
| `git diff --check a43dbdd -- frontend/app/landing-page.tsx frontend/app/landing.css` | exit 0 |
| diff protegido (brand/globals/layout/auth/legal/provider-logo/backend vs `a43dbdd`) | exit 0, sem mudanças |
| `curl http://127.0.0.1:5181/` e `/api/session` | exit 0; HTTP 200 em ambos; body da sessão `null` |
| `graphify query "How do the Arquivio landing-page A direction changes, geometry, implementation and earlier F-206/F-207 findings relate?"` | exit 0 |

## Evidências fresh

- [`clean-preview-round2.json`](evidence/clean-preview-round2.json) — primeira visita anônima sem mocks, API/assets, geometrias nos cinco tamanhos, casos, FAQ, menu, reduced-motion, no-JS e sequência de ações.
- [`routes-ctas-round2.json`](evidence/routes-ctas-round2.json) — âncoras, CTAs de signup abortadas antes de auth e login sem credenciais.
- [`route-targets-round2.json`](evidence/route-targets-round2.json) — resultados e logs separados por rota pública.
- [`verdict-round2.json`](evidence/verdict-round2.json) e screenshots desktop/mobile — veredito final após os demais checks.
- Fontes do round 2 do builder: `specs/work-items/lp-chat-modernization-20261002/evidence/round2/geometry.json`, `evidence/round2/after/qa-report.json`, `evidence/README.md` e `frontend/app/landing.css`.
