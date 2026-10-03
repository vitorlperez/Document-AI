# Inventário de motion — extensão H4

Data: 2026-10-03 · branch `design/lp-chat-modernization-20261002` · URL pública `http://127.0.0.1:5181/`.

H4 **provided**: direção A mantida; mais modernidade por transições; incluir motion nas interfaces modais existentes do app. Este documento é inventário, não implementação. A autorização nova supera somente a exclusão anterior de motion em modais; não autoriza migração global de cores/tipos, novas interfaces, copy, CTAs, regras de fechamento, APIs ou acesso a dados.

## 1. Evidência, método e cobertura

Skills: **inline [oc-design-dna, oc-browser]**, arquivos completos consultados em `/Users/vitorperez/.codex/skills/{oc-design-dna,oc-browser}/SKILL.md`. Retomado DNA h-ed autoral, sem transportar keyframes/assets Dust. Aplicação nesta extensão: proveniência de cada decisão, inventário de estados reais, timings concretos, redução, gaps honestos. Não é emissão de um segundo design-system completo; o linter de ~12 artefatos da skill pertence ao DNA anterior e não atesta estes três documentos.

Antes das relações de código: AGENTS.md e skill graphify lidos; `graphify query 'Modal Dialog Sheet Drawer FocusTrap useDismissableLayer workspace settings integrations conversation organization members confirmation overlay' --budget 6000` e `graphify query 'ModalOverlay modal-dismiss useModalDismiss useModalFocus' --budget 7000`, ambos exit 0. Segunda consulta retornou 92 nós/308 relações. `graphify-out/wiki/index.md` não existe. Grafo usado para localizar relações, não como prova de linha atual; call sites corroborados na árvore atual. Nenhum graph update executado.

Busca transversal de `<dialog>`, `showModal`, `ModalOverlay`, `useDialogBackdropClose`, `aria-modal`, `role=dialog/alertdialog`, `Dialog/AlertDialog/Sheet/Drawer/CommandDialog`, imports das primitives, `createPortal`, `fixed inset`, backdrop e `window.confirm/prompt/alert` em `frontend/app`, `frontend/components` e testes. Inspeção de componentes, CSS, consumidores, callbacks e dependência Radix instalada.

**Cobertura na árvore atual: 5 superfícies usadas (3 dialogs nativos, 1 overlay próprio, 1 Sheet), 9 call sites de confirmação nativa do navegador, 5 consumidores/primitives potenciais sem montagem no produto (Dialog, AlertDialog, Drawer, CommandDialog, Sidebar genérico).** Sheet é usado pelo menu móvel e pelo Sidebar genérico, este sem consumidor no app. Nada encontrado justifica criar outro modal. Menus/listboxes não modais classificados na §6.

| Evidência | Confiança | Limite |
| --- | --- | --- |
| H4 e plano 180–220 ms fornecidos pelo dono | provided | substituem status H4 pendente de work-item antigo |
| Baseline §§4–7, direction/DESIGN.md, motion-plan.md, tokens.css, copy/COPY.md, MICROCOPY-QA.md, CLAIMS-AUDIT.md, design-to-app.md | provided | preservar; metas antigas não são métricas atuais |
| Paths/símbolos abaixo | observed — source | código lido; não valida runtime autenticado |
| `evidence/public-runtime.json` | observed — runtime público | contexto novo sem cookies; somente GET público e `/api/session`; demais APIs/métodos bloqueados |
| `evidence/public-{1440,390}-faq.png`, `public-390-menu.png` | observed — runtime público | estado estático real; não prova coreografia intermediária ou auth |
| `artifacts/onboarding/tool-cards-check.cjs:29–51` | observed — source de fixture | mocks sintéticos existentes; fallback `route.continue()` precisa ser fechado para QA futura |
| Valores/camada propostos em MOTION-SPEC.md | inferred | autorais e compatíveis; ainda não implementados |

Documentos de produto lidos: `specs/001-mvp-document-intelligence.md:94,102–104,151–189,215–217`; F-024 (gestão de conexão/permissões), F-048 (Gerenciar), F-054 (foco autorizado), `library-ux-folder-actions.md` e work-item da LP. Specs históricas apontam para product-app monolítico; paths atuais abaixo prevalecem para localizar implementação. Não reinterpretar mensagens existentes de OCR/cota por causa desta fase.

Runtime público medido em 1440×900 e 390×900: três botões/casos, sete FAQs, nenhuma página error e nenhum overflow horizontal. Thread atualmente `lp-case-in` 180 ms, só opacity .35→1; FAQ chevron 180 ms; menu sem animação própria; reveal 240 ms com atrasos até 120 ms. Reduced-motion após atualização de mídia/estilo: thread `animation:none`, durations/delays 0, opacity1/transformnone, zero animações em execução. Ver JSON por viewport para DOM, estados e timings. Captura não equivale à QA futura das mudanças propostas.

## 2. Camadas de comportamento existentes

### C1 — dialog nativo / top layer

`frontend/app/modal-dismiss.tsx:11` **useDialogBackdropClose**: mede retângulo; fecha só quando press **e** release começam/terminam no backdrop fora da caixa (`:16–22`). Escape gera cancel; bloqueado apenas se `busy` (`:24`). Registra/remove listeners por effect (`:25–29`). Consumidor único: LibraryScreen `:41`. Não presumir que o comentário “every modal” deste módulo se aplica aos outros dialogs.

Dialogs abertos por `showModal()` recebem comportamento modal/top layer/foco do navegador, sem React portal. A restauração exata e o foco inicial devem ser provados no browser de fixture. Tour e chave API possuem handlers próprios, não usam C1.

### C2 — overlay próprio

`frontend/app/modal-dismiss.tsx:33` **ModalOverlay**: div `role=dialog`, `aria-modal`, `aria-labelledby`, `aria-busy`, tabIndex−1 (`:53`). Captura elemento ativo, foca primeiro candidato ou root e restaura trigger conectado no unmount (`:38–43`). Tab/ShiftTab fazem wrap só nos endpoints (`:46–51`). Escape bloqueia propagação, fecha se não busy (`:45`); mouse press/release exigidos no overlay e bloqueados por busyRef (`:54–55`). Refs do callback/busy atualizadas por effect (`:36–37`).

**Limites source:** sem portal, inert/aria-hidden de irmãos, body-scroll lock ou listener global de focusin explícitos. Lista de foco não filtra visibility/retângulos e ramo sem candidatos não prende Tab. Não certificar “trap completo” apenas pela existência de aria-modal. Consumidor único: IntegrationScreen. Motion não corrige essas políticas nem aumenta alcance dos seletores.

### C3 — Radix Sheet

`frontend/components/ui/sheet.tsx:5,9,28,58–60`: Dialog primitive Radix, Portal → Overlay → Content, z50 ambos; defaults de entrada 500 ms/saída 300 ms (`:63`) e slides por side (`:64–75`). Não há guard reduced-motion no wrapper. `.mobile-drawer.mobile-drawer` (`mobile-chat.css:27–32`) declara **transition-duration 220 ms**, que não necessariamente substitui **animation-duration** das utilities 500/300; medir ambas em fixture. Redução local em `:108–109` reduz transition/animation para .01 ms no content; não cobre explicitamente overlay portal.

Dependência instalada como evidência source: `frontend/node_modules/@radix-ui/react-dialog/dist/index.mjs:91–102,142–168,216–234`: Presence, portal, hideOthers, FocusScope e DismissableLayer; trapFocus/disableOutsidePointerEvents dependem de context.open; restauração custom via onCloseAutoFocus. Presence observa animationend/cancel (`@radix-ui/react-presence/dist/index.mjs:65–114`), pode conservar nó durante saída. Estas são garantias de mecanismo lidas, não screenshot/validação auth.

## 3. Superfícies usadas — abertura, fechamento, foco e camadas

| ID / superfície | Abrir / símbolo e linhas | Fechar / regras reais | Foco / camada |
| --- | --- | --- | --- |
| M1 Sincronizações | `frontend/app/product/library-screen.tsx:19` LibraryScreen; spacesPanelOpen `:26`, ref `:28`, effect showModal/close `:35–38`; botão aria-label Sincronizações na linha `:251`; reprocessFolderNode abre após confirmar job em `:230` | X na `:261` seta false mesmo busy; `onClose` sincroniza false; Escape/backdrop usam C1 e busyNodeId ou busyFolderId `:41`; backdrop exige press+release. Ref dialog permanece montada quando closed | UA top layer/foco. Sem restauração custom no componente. CSS `chat-workspace.css:104–105`, overflow próprio, 800 px máximo, backdrop45%. Sem z-index numérico necessário no top layer |
| M2 Integração ativa | `frontend/app/product/integrations-screen.tsx:24` IntegrationScreen; loadCatalog `:44` reseta seleção/catálogo e seta toolModalOpen=true antes do fetch; Gerenciar por IntegrationCatalog/ToolsCatalog `:66,76–109`; pós-OAuth connected `:45–56` também abre | closeTool `:65` apaga source/catalog/errors e desmonta `source && toolModalOpen` `:67`. Escape/backdrop bloqueados se busy em C2; **X :67 chama closeTool sem guard busy**. Sucesso sync pode fechar/navegar em finishSync `:59`. Desconectar `:62` também limpa source e fecha; reconnect é navegação OAuth, não outro modal | C2 focus primeiro X/restauração do trigger no unmount; retorno pós-OAuth pode ter body como elemento prévio. Inline fixed z50, section max90vh/max3xl/scroll. Sem portal/inert/lock comprovados |
| M3 Tour da conversa | `frontend/app/conversation-tour.tsx:16` ConversationTour; effect showModal `:25–30`. `frontend/app/product/chat-workspace.tsx:17–32` CompanyDashboard monta por tour_required ou replayTour; botão Rever tour em `:195` | finish `tour:69–75`: busy bloqueia chamadas, await onComplete, erro mantém aberto. Escape preventDefault e finish; click fora de .tour-card finish quando !busy (`:76`), **sem requisito press+release**. Pular/último CTA usam finish. Voltar/Próximo mudam index no mesmo dialog (`:84–86`) | UA top layer; effect memoriza foco e restaura no cleanup `:26–30`; por etapa rAF foca primary (`:60`). Callback pai rAF `chat-workspace:26–30` escolhe composer ao concluir primeiro tour; ao dispensar/replay, trigger visível → menu → composer. CSS `onboarding.css:29–37`: dialog fullscreen, backdrop transparente, highlight com sombra gigante, card fixed top/left medidos |
| M4 Chave de API, uma vez | `frontend/app/access-settings.tsx:11` AccessSettings; create `:45–51` POST real define secret e aguarda load; effect `:39` showModal quando secret; JSX condicional `:83`; usado em `developer-screen.tsx:91` | closeSecret `:62–66` close imediato, secret=null, copied=false; Escape onCancel=closeSecret, onClose também limpa secret (`:83`). Fechar usa mesmo callback. **Sem handler de clique fora**; não presumir light-dismiss | UA top layer; foco inicial não é definido explicitamente; closeSecret rAF devolve createButton se habilitado, senão heading (`:65–66`). Não duplicar/reter o secret para exit. Backdrop black40%, max-lg e textarea readonly na `:83` |
| M5 Menu móvel autenticado | `frontend/app/mobile-nav.tsx:44` MobileShellHeader; state open `:45`, botão Abrir menu `:80`, Sheet controlled `:84–85`; shell usa useIsMobileShell <768 | SheetClose `:88`, Escape/outside/onOpenChange por C3. go/newConversation/showTour `:59–69` setOpen(false) **antes** da ação. Select organização `:95` fecha antes onCompanyChange; Sair `:108` fecha antes logout. Não adicionar espera | C3 portal body, z50 content+overlay. onCloseAutoFocus custom `:85` preventDefault e ref menu.focus. drawer não descendente .product-app; css próprio `mobile-chat.css:27–52` + redução `:108–109`. Breakpoint ≥768 esconde via CSS (`:105`) |

## 4. Estados reais dentro e ao redor das superfícies

Não preencher uma matriz abstrata criando estados/copy. “Não existe” significa ausência de UI naquele modal, não algo a implementar. Estado de dados/pending muda imediatamente; motion não reinicia no polling.

| ID | Loading / empty | Populated / sucesso | Error / edge / pending / formulário |
| --- | --- | --- | --- |
| M1 | Histórico começa array vazio sem indicador de carregamento exclusivo (`:29,261`); “Nenhuma sincronização registrada.”. Espaços: LoadingIndicator se foldersLoading e lista vazia, depois “Nenhum espaço sincronizado.” | Histórico run.operation sync/resync; queued/syncing/ready/failed/partial_failure; nome/autor/datas; progress só total>0. Espaços last_synced_at/status, avisos queue/background | syncHistoryError role alert; total=null aviso contagem indisponível; total0+syncing “Descobrindo arquivos…”; failures/skipped/tasks detalhes; partial_failure carrega detalhes, lista vazia ou failureLoadError; folderActionErrors role alert; busyFolderAction sync/remove muda labels Iniciando/Excluindo, aria-busy/disabled. Member sem gestão. Poll histórico/espaços3s `:213–218`, jobs3s `:192`. Não há formulário com untouched/dirty separado |
| M2 | !catalog sem catalogError LoadingIndicator `:72`; foldersLoading+lista vazia `:70`; nenhum espaço sincronizado; availableFolders0 → indisponível/tudo já sincronizado `:71` | Conexão ativa/account_email opcional `:68`; catálogo pastas/pages/database/data_source com grupos não selecionáveis; syncedForSource status; syncFeedback status/live `:69` quando branch não navega, Dispensar existente | catalogError role alert+retry :72; 403/409 → reauth_required + erro global :44; syncError role alert/scrollIntoView :71; untouched selectedIds=[],uniform=false,mode selected; dirty seleção/root/all+uniform; pending busy e botão disabled Sincronizando; notas existingSpace/coveredBy/cota/permissão; fonte reconectável, catálogo stale/fetch tardio. Modificar timing não é cancelar fetch, resolver race ou redefinir busy |
| M3 | Não existe estado empty/loading de dados inicial: 5 passos estáticos `tour:6–12`; target invisível → highlight fallback/posição medida `:32–57` | index0–4; Voltar a partir do segundo; último Começar a conversar; sucesso do onComplete desmonta no pai | error role alert :82; busy Salvando… e todos botões disabled :84–86; finish em andamento mantém dialog; alvo móvel tool-sidebar vira navigation :33. Resize/scroll/ResizeObserver atualizam posição imediatamente; primeiro/replay/pular/finished variam foco. Não existe formulário dirty |
| M4 | Loading/empty pertencem **à seção anterior**, não modal: loading acesso :72, keys0 :74. Secret modal só existe depois de sucesso create | secret readonly; copied=false/true muda Copiar chave/Copiada :83; criação limpa campos no fundo :49 | Falha copy usa setError na seção **fora** do dialog :58–60; não há alert dentro. Create busy pode continuar durante load após secret abrir; close continua disponível. Form prévio required nome/max120, scopes, expiry, mentions; selectedScopes0/nodes>20 bloqueiam botão :81. Não criar erro/empty/skeleton/submit extra dentro modal, nem mover secret a analytics/screenshots |
| M5 | ToolsSidebar loading/skeleton; ferramentas vazias, roots ainda []; não existe form de submit modal | Organização ativa e lista; role owner/admin/member filtra links; tools status e SyncBanner; usuário/footer/staff condicional | Falha roots catch→[] :54–56; erro/progresso fornecido por sync-status/ToolsSidebar sem UI modal nova. Organização longa, scroll, safe-area, teclado virtual; account switch/logout/navigation saem imediatamente. open/closed não equivale a fetching/pending modal |

Labels nesta tabela resumem estados; **a fonte literal continua o código**. Não transcrever abreviações/espaços desta análise como copy de produto.

## 5. Confirmações nativas: nove call sites, sem superfície animável própria

`window.confirm` é diálogo do navegador. Preservar texto, ordem, aceitação/cancelamento; não substituir por AlertDialog para animar. Nenhuma confirmação foi acionada neste inventário.

| Path:linha / símbolo | Contexto e estado depois da resposta |
| --- | --- |
| `product/integrations-screen.tsx:60` selectAndSync | M2→confirm se seleção retorna espaço já sincronizado; busy já true; recusa retorna pelo finally; aceite full reprocess+requireHistory+finishSync; erro syncError/global; custo/cota no FULL_RESYNC_CONFIRM |
| `product/integrations-screen.tsx:61` resyncFolder | M2→confirm full; recusa sem busy; aceite busy, reprocess/history, notice; erro catalogError/global; finally libera |
| `product/integrations-screen.tsx:62` disconnect | Card catálogo→confirm preservando índice; pending disconnectingSourceId, DELETE; sucesso fecha M2 se houver e notice; erro global |
| `product/library-screen.tsx:234` removeFolderNode | Árvore/grade→confirm pasta/subpastas/índice/originais; busyNodeId depois aceite; erro global; atualiza listas |
| `product/library-screen.tsx:242` removeFolder | **Dentro M1**→confirm excluir espaço/dados locais; busyFolderAction=remove; sucesso remove da lista/notice; erro localizado folderActionErrors, finally libera |
| `product/library-screen.tsx:250` removeFileNode | Árvore/grade→confirm só se workspace_documents existem; sem refs erro imediato; busyFileId depois aceite; erro global, reload no sucesso |
| `product/team-staff.tsx:15` remove | Equipe→confirm remover membro; updatingMemberId; sucesso lista/notice, erro global; não é modal React da Equipe |
| `product/developer-screen.tsx:53` toggleConnection | Vincular MCP inativo→confirm de leitura/organização; busy PUT após aceite; ativo DELETE não confirma; erro inline na tela |
| `access-settings.tsx:53` revoke | Seção API→confirm revogar chave; busy DELETE/reload; erro seção; não é M4 |

Prefixo dos paths product acima: `frontend/app/`. FULL_RESYNC_CONFIRM em `frontend/app/product/types-and-api.tsx:26`. Não remover avisos de custo ou alterar permissões. Pendings dependem da API, jamais da animação.

## 6. Superfícies semelhantes, limites de escopo e CSS compartilhado

| Superfície / path:linha | Classificação / impacto |
| --- | --- |
| `frontend/components/ui/dialog.tsx:10,39–68` | Primitive Radix genérica, portal z50, fade/zoom95 duration200; importada por CommandDialog, **nenhum consumidor de produto encontrado**. Não aplicar overrides apenas por existir |
| `frontend/components/ui/alert-dialog.tsx:9,36–66` | Primitive genérica Radix, z50/duration200; sem consumidor produto; não substituir confirms |
| `frontend/components/ui/drawer.tsx:8,23,37–71` | Primitive Vaul genérica, portal z50/directions; sem consumidor produto. Não adicionar gesture/swipe |
| `frontend/components/ui/command.tsx:32–54` | CommandDialog compõe Dialog genérico; sem montagem produto. `/` do composer usa listbox próprio, não este dialog |
| `frontend/components/ui/sidebar.tsx:185–204` | Sidebar genérico mobile compõe Sheet; sem consumidor no app. M5 usa ToolsSidebar próprio, não este Sidebar |
| `frontend/app/product/library-grid.tsx:36–75` CardMenu | Menu não modal: z50 fixed sem portal; posiciona e foca após pos, Escape restaura, Tab/outside/scroll/resize fecham; ação fecha antes run. Documentar como origem de confirmação, **não mudar seu motion agora** |
| `frontend/app/question-scope.tsx:24–56` QuestionScopePicker | Group/popover inline, open/outside pointerdown, seleção/erro/loading; sem trap/modal/Escape dedicado. Não converter em dialog nem uniformizar dismiss |
| `frontend/app/mention-composer.tsx:92–98` | Listbox @/comandos, loading/erro/opções; não modal; não animar sugestões/dados por token |
| `frontend/app/product/shell.tsx:15–24` NotificationToast | Status/alert z70, dismiss/progress; não modal; não usar z-index global para ultrapassar dialog top layer |
| `frontend/app/organization-onboarding.tsx:23–73` | Página/onboarding com IntegrationScreen filho, não novo modal; pode hospedar M2; motion de página fora de escopo |
| `frontend/app/landing-page.tsx:172,226` | Details de menu público e 7 FAQs, disclosure não modal; sem focus trap/Escape/outside handler. Preservar sem dar semântica dialog |

CSS global `frontend/app/globals.css:1–3` importa Tailwind/tw-animate-css/vendor, `:22` root palette, `:358–374` alvos/disabled/foco. App controla button/link/summary focus, campos sem outline por **decisão humana F-054**; M5 portal recebe regra própria `mobile-chat.css:24`. Não reaplicar ring em todos os inputs nem mudar globals nessa extensão. A revisão de acessibilidade do foco de campos é decisão separada, não efeito de motion.

`chat-workspace.css:104–105` já hospeda estilos M1; `onboarding.css:29–37` M3; `mobile-chat.css:27–52,108–109` M5. Shared Sheet CSS afeta Sidebar se override indiscriminado. Uma nova regra `.product-app [data-slot=sheet-content]` **não alcança portal**. Não animar root/ancestrais do workspace: transform cria containing block e pode mudar posição de fixed menu/tour/overlay. `landing.css` é carregado no bundle do app por product-app→LandingPage, mas tokens/reduced-motion são locais `.landing-page`. `design-to-app.md:74–75` obriga manter esse isolamento.

## 7. Mapa de flows existentes

```text
LP: caso A↔B↔C → commit único imediato do thread/fontes (aria-live)
    FAQ fechado↔aberto; menu details fechado↔aberto → mesmos destinos.
Biblioteca: botão Sincronizações OU reprocessFolderNode confirmado → M1
    M1 → atualizar / re-sync incremental / confirm exclusão espaço → mesmos estados
    M1 → X/Escape/backdrop permitido → Biblioteca (foco UA).
Integrações: Gerenciar OU callback connected → M2 loading → catálogo OU erro/retry/reauth
    M2 → seleção+uniform → pending → [confirm full se necessário]
        → registro sync confirmado → fecha + navega Biblioteca?syncing=<source>
        OU onboarding.advance("sync") OU feedback interno (branches existentes)
    M2 → Re-sync → confirm full → pending → notice; M2 continua aberto
    M2 → Reconectar → OAuth externo (não testar nesta fase)
    catálogo → Desconectar → confirm → pending → fecha source + notice.
Mobile: abrir → M5 → Conhecer app → setOpen(false) + trigger síncrono → M3
    M5 → Nova conversa / ferramenta / aba / organização / sair → fecha + ação imediata.
Tour: M3 passo0↔1↔2↔3↔4 (mesmo dialog) → finish/pular/Escape/fora
    → salvar conclusão pending → erro mantém M3 OU desmonta + foco escolhido no pai.
Desenvolvedor: form API → create pending → M4 secret (load pode continuar)
    → copiar/Copiada OU erro seção → Fechar/Escape → limpa secret + restaura foco.
```

**Não há wizard de novos modais nem crossfade intermodal generalizado.** Troca Sheet→Tour pode ter overlap residual da saída Presence com tour top layer; onCloseAutoFocus do Sheet e rAF do tour/pai podem competir. É cenário obrigatório de fixture/QA; não inventar fila de navegação ou espera para resolver. Integrações→Biblioteca muda rota; não compartilhar pending/motion entre instâncias/organizações. Tour move posição/card no mesmo modal, não recria dialog a cada passo.

## 8. Gaps declarados e caminho seguro

Não acessado runtime autenticado, nem lidos dados privados, cookies existentes, chave real ou mensagens. **Nenhuma screenshot auth produzida.** Cinco modais têm evidência source; a QA de foco, nested native confirm, portal/presence, busy e resize está pendente para executor em fixtures.

Harness existente adequado como **base de mocks**: `artifacts/onboarding/tool-cards-check.cjs:22–53`: fake user qa@example.com, org111…, catálogo de integrações e respostas locais; não executar versão original contra backend real porque endpoints não mapeados passam adiante `:51`. `review-check.cjs:10–38` cria organizações e usa route.fetch/context.request; **não usar nesta fase**. `qa-server.py:31–69` é isolado mas cria identidade/estado e não é necessário: esta missão não o iniciou. Fixtures antigas/screenshots anteriores não são evidência runtime fresh dos modais atuais.

Plano seguro detalhado em implementation-plan.md: cópia temporária do harness em /tmp, contexto limpo, serviceWorkers blocked, todas APIs GET/POST/DELETE/PATCH respondidas localmente ou abortadas, sem route.fetch/pass-through/API real/OAuth. Dados sintéticos somente; não efetuar cadastro/login nem enviar pergunta. Cobrir M1–M5 pelo app existente com mocks. Se surgir dependência de dados humanos/credencial, acesso externo ou correção de comportamento, escalar ao piloto; inventário não está bloqueado por não autenticar.
