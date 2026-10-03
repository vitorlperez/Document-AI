# Plano de implementação restrita — motion H4

Data: 2026-10-03 · branch `design/lp-chat-modernization-20261002`. **Documento de handoff; nenhuma tarefa abaixo executada no produto.** Ler INVENTORY.md e MOTION-SPEC.md junto de brief-baseline, copy/COPY.md e MICROCOPY-QA.md, direction/DESIGN.md, design-to-app.md e spec do produto. H4 autoriza motion de LP + modais existentes; não autoriza redesenho completo, novos fluxos, tokens globais ou dados reais.

## 1. Sequência e mapa de arquivos para o executor

| Ordem | Arquivos/símbolos existentes ou seam proposto | Trabalho limitado e aceite |
| --- | --- | --- |
| 0 | INVENTORY §§3–5; `frontend/tests/landing-contract.test.mjs`; harness `artifacts/onboarding/tool-cards-check.cjs:22–53` | Registrar DOM/copy/handlers/estados current antes do diff, com contexto seguro. Executar matriz de comportamentos atuais primeiro; diferenças busy/X, secret outside e foco são baseline, não “uniformizar” |
| 1 | novos **propostos** `frontend/app/interface-motion.css`, `.ts` | Apenas tokens escopados, keyframes/helper visual cancelável. Unit tests úteis: cancel anterior, cleanup, reduce inicial/change e ausência de callbacks de negócio. Nenhum estado open, focus, secret, API, router ou retensão para saída |
| 2 | `frontend/app/landing.css:111–112,208–214,234–240,285–293,356–358`; `landing-page.tsx:47–85,133–146,172,226` | Caso200ms+Y4, FAQ/menu200ms entrada progressiva, reveal240ms+stagger≤40 total280; hover/press escopado. Preservar props/aria-pressed/aria-live, todas strings e destinos. Wrapper visual opcional sem duplicate transcript; preferir CSS para details, closed imediato. Não remodelar layout/dobra F-206 |
| 3 | `frontend/app/product/library-screen.tsx:26–41,261` | M1 section opt-in, entrada200 acionada pelo open. `useDialogBackdropClose` e state/busy/polling intactos; dialog continua montado fechado, sem exit timer. Testar showModal após rapid re-open |
| 4 | `frontend/app/product/integrations-screen.tsx:44,59–73` | M2 section opt-in, mount200; não alterar `modal-dismiss.tsx`/closeTool, fetch/order/cota/OAuth. Entrada não recomeça loading→catálogo, re-sync, status/erros. Root overlay não move nem reduz opacity dos filhos; se backdrop sem nó independente, usar entrada panel apenas em vez de criar segunda camada funcional |
| 5 | `frontend/app/conversation-tour.tsx:25–30,60–88` | M3 interior visual da card, enter200/index200. Highlight e inline top/left não interpolam; não keyar dialog/focusable button; onComplete/foco/handlers originais. Erro/submitpending sem replay |
| 6 | `frontend/app/access-settings.tsx:39,45–66,83` | M4 visual entry180–200, close imediato. Helper não recebe secret/string, só ref. Copiar/erro/fallback foco sem mudanças; não criar máscara, novo passo, alert ou storage |
| 7 | `frontend/components/ui/sheet.tsx:47–78`; `frontend/app/mobile-nav.tsx:59–69,84–85`; `mobile-chat.css:27–32,108–109` | Seam prop `motionProfile="arquivio"` **opt-in** apenas M5, Overlay+Content. Defaults dos demais preservados. Ramo profile evita utility animations conflitantes, mede animation **e** transition. In200/out180 via Presence existente, shortX12, reduce em ambos portalnodes. Props/eventos/accessibility/side/refs intactos |
| 8 | testes existentes `frontend/tests/`; script browser **temporário em /tmp** e evidências somente no work-item | QA independente source+fixtures abaixo; nenhum secret real; diff/copy/API parity, build/lint, browser com timings. Limite de change-scope verificável |

Esse é o mapa candidato para a **próxima fase**. Este worker escreveu só motion-extension. `modal-dismiss.tsx`, globals.css, brand.tsx/css, provider-logo, product-app, API/auth/backend/graph e scripts de outros workers **não precisam ser editados** para o motion visual proposto. Se qualquer item exigir mudar regras nesses arquivos, parar no componente e explicar ao piloto a decisão; não ampliar escopo por conveniência.

Native M1/M2/M3/M4: saída imediata conforme contrato; não implantar presence universal. Nenhuma nova dependência Framer/GSAP necessária. UI Dialog/AlertDialog/Drawer/Command/Sidebar sem uso ficam intactos; confirms nativos permanecem.

## 2. Construir evidência segura usando harness já existente

Hoje há source evidence de todas as superfícies e runtime público fresh em5181; **não há prova auth fresh**. O acesso autenticado real não é necessário nem autorizado para a QA desta extensão.

Base existente: `artifacts/onboarding/tool-cards-check.cjs:29–51`, user/org/catalog **sintéticos**, route.fulfill. Copiar lógica necessária para `/tmp/oc-browser-arquivio-motion-qa.cjs`; não editar script de outro worker, não executar versão as-is com fallback desconhecido. Não usar `artifacts/onboarding/review-check.cjs` (create account/org, route.fetch, context.request) nem iniciar qa-server.py nesta fase.

Requisitos do script seguro antes de navegar:

1. Playwright contexto fresh sem storageState/persistent profile/cookies, `serviceWorkers:"block"`; nunca carregar perfil pessoal. Somente host explicitamente5181 ou frontend local isolado do executor, com build atual verificado. Static assets/rotas de página GET permitidos; demais hosts, OAuth/login callbacks e endpoints não listados bloqueados.
2. Rota **fail-closed** de TODA API (`/api/*`, origem API absoluta de API_BASE, backend/proxy/endpoints conhecidos) instalada antes de page.goto. Fake `/session`/`/me` e `/organizations` só via `route.fulfill`; demais respostas listed fixtures ou abort+erro de teste. **Sem `route.fetch`, continue para APIs ou request do contexto.** CORS headers se fixtures usam origem absoluta; OPTIONS local. Bloquear websocket/eventsource se vierem a existir, registrar inesperados como gap.
3. Verificar transport: zero chamadas reais de dados/modificação; só respostas locais, não usar login/cadastro/clique OAuth. Ir diretamente à rota existente `/companies/11111111-1111-4111-8111-111111111111/...` com fake user/org autorizados pelo mock; isso é runtime de app **em fixture**, nunca auth real.
4. Fixtures cobrem contratos **atuais**, consultando os tipos em `frontend/app/product/types-and-api.tsx`, `sync-status-logic.ts`, `organization-onboarding.tsx`; usar IDs sintéticos e nomes `.example`/example.com. Nenhum conteúdo, origem, nome ou e-mail real. PUT/POST/PATCH/DELETE respondidos localmente e contados, zero efeito em API/custo.
5. Mocks de pending controlados por Promise/gate e resoluções explícitas, nunca waitForTimeout para esperar rede. Erros simulados com status/body real do contrato, sem inventar UI. Cada caso limpa contexto/handlers; sem aproveitar output persistente de outra organização.
6. Se runtime exigir server-side API que não passa por route, **não prosseguir via API real**: usar instancia local existente test harness isolada ou pedir ao piloto caminho de fixture server com zero dados externos. Não habilitar auth bypass de produto, não criar rota/modal de demonstração no produto.

| Modal | Respostas locais e rota existente para fixtures | Cenários essenciais |
| --- | --- | --- |
| M1 | company Library; `/library`, `/library/contexts`, `/library/syncs`, sync status usado por `useSyncStatus`, `/workspace-folders`, `/library/sync-history`, children/jobs/failures conforme chamadas reais; reprocess/delete fulfilled local | Nada registrado, foldersLoading, histórico cheio, todos5status, totalnull/0/>0, falhas/skips/tasks, erros histórico/folders/details/action; owner/admin/member; job ativo/pendingSync/pendingDelete; longnames/muitosregistros |
| M2 | integrações/onboarding existentes; `/data-sources`, workspace folders, source/scope-catalog, fontes sync status/history; selections/sync/reprocess/disconnect locais; Não navegar OAuth | loading catálogo, catálogo vazio, pages/root/all/grupos, seleção inválida/válida+uniform, sobreposição/cota/permissãoSharePoint, pending,403/409reauth, erro genérico/retry, sync success feedback/route/onboarding, error sync, re-sync/confirmcancel/accept, disconnectcancel/accept |
| M3 | company chat; onboarding requiredfalse + tour_requiredfalse/true; library/contexts/syncs e restore vazio locais; POST tour/complete local | 5steps, firsttime/replay, Voltar/Próximo, Pular/Escape/fora, pending completar, error mantém, sucesso; targets visíveis/ausentes/mobile, scroll/resize; nenhuma pergunta enviada |
| M4 | developer; public-access settings, api-keys, mcp-info/connection/endpoints que tela realmente pede, mentions synthetic; POST api-keys responde key **falsa e obviamente de teste** | Form antes de modal untouched/dirtyvalid/invalid/pending/error, secret abre no sucesso enquanto load ainda pending; copy resolvido/rejeitado local sem clipboard real, Copiada, fechar/reabrir, createbuttondisabled→fallbackheading; não usar chave nem chamar serviço externo |
| M5 | qualquer company screen com mock role e membership; library roots/status locais; companies synthetic | closed/open, list/toolsloading/empty/status; owner/admin/member/staff, rotas existentes/organização/toolbar/newconversation/tour/logout; larguras móveis e resize; mocks de logout locais sem conta real |

Não tratar esta tabela como listagem final de endpoints: setup deve registrar chamadas exatas do source e falhar para endpoint omitido, preenchendo fixture com contrato existente **antes de executar caso**. Não relaxar allowlist para conseguir screenshot. Em secrets, não incluir string nem formulário completo nos logs, DOM snapshots ou imagens; evidência pode focar título/botões e valores booleanos/retificação sintética. Clipboard é stub local em fixture (sucesso/erro), não clipboard do humano.

`tool-cards-check.cjs` é a base de mock de M2, não cobertura já existente de M1/M3/M4/M5. Novos **cenários de QA** para interfaces existentes são necessários; novos modais/funcionalidades não. Evidências antigas `artifacts/onboarding/qa/fixed/*` não substituem captura fresh.

## 3. Matriz de aceitação por interação

Cada teste compara comportamento baseline source/fixture e resultado proposto, sem exigir comportamento inexistente. Fonte de estados completos: INVENTORY §4; nenhum estado vazio/loading/form é criado no modal para preencher checklist genérico da skill.

| Teste | Given / When / Then obrigatório |
| --- | --- |
| K1 foco abrir | Abrir M1–M5 por trigger existente; trap/foco inicial correspondente disponível durante200ms, não após. Nativedialog top layer/ModalOverlayendpoint/SheetFocusScope separados; heading/nome/aria intactos |
| K2 Tab | Tab/ShiftTab atravessam controles ativos/disabled/scrolllong no mecanismo atual; no body indevido. Se baseline source tiver gap de trap (C2), registrar/escalar ao piloto; motion não adiciona foco global silencioso |
| K3 Escape/fora/X | Idle: fechar por caminhos presentes. Busy: M1/M2 Escape/fora bloqueados mas X atual fecha; tour todos finish bloqueados; M4 close continua permitido. Secret clickoutside sem handler não deve passar a fechar. M1/C2 drag seleção de texto + soltura fora não fecha; tour mantém regra atual de click |
| K4 pending | Clique sync/remove/finish/create duas vezes: calls e disabled iguais baseline. Loading/error/success/aria atualizam no mesmo tick de resultado; nenhuma espera de200ms, nenhum duplicate POST por animationend |
| K5 restoration | M1 trigger UA; M2 trigger conectado; M3 finishedfirsttime→composer, dismissed/replay→trigger/menu/composer; M4 createbutton ou headingfallback; M5 menuButton. Timing não atrasa restoration já imediata nos mecanismos nativos/overlay |
| K6 rápido | M1 open→close→open em<180ms; M2 mount→unmount→mount; M3step1→2→back rapidamente; M4copy→close→reopenfake; M5 open→closed→open durante Presence. Só último ciclo vivo, sem callback stale/foco em nó desconectado, estilos finais e nenhum vazamento listener |
| K7 intermodal | M5 Conhecer app → M3 mesmo clique; M3 recebe foco e Sheet tardio não o rouba. M2sync→Biblioteca não pausa router; M1/M2→nativeconfirm cancela/aceita, dialog correto continua/fecha. **Se corrida já existe, escalar ajuste de foco ao piloto**, sem timeout de200ms |
| K8 fonte/tenant | Em fixture, trocar source/organização/rota durante efeito, resolver Promise antiga: motion cancelado/sem dados duplicados; comportamento do fetch continua baseline. Race de source prévia não é consertada por presença e precisa decisão separada se demonstrada |
| K9 reduce | Redução true antes load; depois durante ingresso/saída/openStep, e volta a no-preference: anim só próximas ações, nunca replay infinito; durations/delays0/opacity1/transformnone/backdropfinal, nenhum effect rodando. Content **e** overlay do Sheet; open/close/focus/aria/idênticos |
| K10 LP | 3casos/7FAQ/menu e todos links/copy baseline; 20 cliques rápidos entre3cases: somente último thread/source/list avisos. Focus fica no caso, aria-live polite sem mensagem duplicada/typing; FAQ Enter/Espaço/toggle e multi-open nativo, completos sem JS. Menu mesma navegação, closedsemfocusdescendente |
| K11 reveal | Scrollnormal/focusanchor/teclado, ≥375/390/768/1024/1440, JSoff/reduce inicial+change: conteúdo sempre alcançável, foco revela imediatamente sem esperarmotion, lastchild≤280ms total, IOonce. Não reabrir discussão de dobra mobile aceita |
| K12 visual/performance | Snapshot e frames por component200ms; onset Y4/Y6/X12 e escala .99 só quando previsto; no blur/per-token/perpoll; comparar animationDuration vs transitionDuration paraSheet. Zerooverflow horizontal, nada cortado por wrappers/transform, targets44, contraste e foco atuais intactos |

Captura motion: preferir `getAnimations()`/computed styles + `Animation.currentTime` em0/50/100% para prova determinística de keyframes **do fixture**; não usar fixed wait para rede. Freeze/animação não prova comportamento fora da fixture; registrar ambos. SVGchevron e card devem mudar propriedades; render final também em reduce. LP announcements precisam teste manual com leitor de tela local em dados públicos/sintéticos; Playwright não prova fala efetiva. Inventory não afirma essa validação.

## 4. Comandos e gates futuros

1. Confirmar branch e diff antes/depois, `git diff --check`, lista de paths explicitamente autorizados. Não stage/commit artefatos ou alterações de outro worker.
2. `cd frontend && node --experimental-strip-types --test tests/landing-contract.test.mjs` e testes novos de helper/dados preservados. Rodar suite existente apropriada uma vez; Node22.16 tem gap conhecido `.tsx` em suite histórica, reportar versão/erro sem atribuir a motion por suposição.
3. `cd frontend && npm run lint` e `npm run build`; dependências atuais. Testes browser precisam build fresh da fase de implementação, não presumir que container5181 já incorporou diff. Rebuild/recriação do serviço é tarefa do executor com wiring documentado em evidence/preview-service.md; inventário não a executou.
4. Localizar servidor antes de localhost (`lsof`), executar script /tmp com `QA_APP_URL` explícita e allowlist de rede. Scripts temporários não vão ao produto/repo. Evidências novas dentro work-item da extensão, distinguindo **public runtime / auth fixture / source**.
5. Revisor independente valida copy/handlers/API parity e profile opt-in/portals, matriz completa e gaps. Human gate/piloto para alterações de comportamento real, credencial/dados humanos, retensão secret, custos/cota ou auth. Não pedir permissão novamente para entradas/feedback já autorizados em H4.

Não executar graph update nesta missão. Quando futuro executor modificar código, seguir as instruções aplicáveis dele; este handoff não concede autorização de escrita agora. Nenhum vídeo/áudio/imagem IA foi planejado/gerado: contrato é CSS/DOM legível e documentos.

## 5. Evidência entregue nesta fase e limite do done

- `INVENTORY.md`: busca/source de5interfaces+9confirms+5primitives/consumers sem uso, flows, todos estados existentes, foco/portals/CSS e gaps.
- `MOTION-SPEC.md`: tokens com confidence e origem,180–220ms, easing/efeitos, exits compatíveis, minimaloptinlayer, LP disclosures/aria-live/reduce.
- `implementation-plan.md`: caminhos/ordem, fixtures failclosed e matriz QA. É conclusão de inventário/contrato, **não implementação testada**.
- `MOTION-OVERVIEW.pdf`: três páginas vetoriais/capturas públicas, renderizadas e inspecionadas; distingue proposta de motion e evidência source/runtime.
- `evidence/public-runtime.json`, três screenshots públicas: freshLP5181 real em1440/390;3cases/7FAQ/menu, zeroerrors/overflow e zeroanimationsreduce. Sem authscreenshots nem privadaAPI.
- `evidence/source-preservation.json` e `preservation-report.json`: hashes do corpus antes/depois. Gate documental verifica paths/linhas e saídas locais; graph, produto, baseline, direction e copy permanecem sem escrita deste worker.

Limites: fonte do code≠runtimeauth; precisamfixturefresh M1–M5, timingsSheet reais e foco concorrente M5→M3. Exits animadas universais não prometidas. Correções de trap/inert/foco/regras busy são decisões separadas se requeridas. Nenhum bloqueio para concluir o inventário; necessidade futura de auth/dados reais interrompe o teste e escala ao piloto.
