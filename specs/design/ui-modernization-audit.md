# Auditoria de UI do frontend (ArquivIO) — base para a varredura de modernização

Escopo: `frontend/` (vinext 1.0.0-beta.5 sobre Next 16 App Router, React 19.2, Tailwind 4.2, deploy Cloudflare Worker).
Método: `graphify query` + leitura de código (somente leitura). **Não foi feita inspeção visual no navegador**: o app respondia 200 em `http://localhost:3000`, mas a auditoria foi feita só pelo código; os problemas visuais abaixo são inferidos do markup/CSS e precisam de confirmação em screenshot na primeira lane que tocar cada tela.

---

## 1. Inventário de rotas, telas e componentes

### 1.1 Rotas (`frontend/app/**/page.tsx`)

Quase todas as rotas são casquinhas `"use client"` que renderizam `<ProductApp screen="…" />` (`app/product-app.tsx`). O roteamento por tela e os guards (sessão, organização, onboarding, papel) vivem em um único componente.

| Rota | Arquivo | `screen` | Observação |
|---|---|---|---|
| `/` | `app/page.tsx` | `home` | Landing se deslogado (`landing-page.tsx`); 1 org → redireciona; N orgs → `OrganizationPicker` |
| `/login` | `app/login/page.tsx` | `home` | Mesma tela `home`; `SignIn` = `product/custom-login.tsx` |
| `/invitations/[token]` | `app/invitations/[token]/page.tsx` | `invitation` | `InvitationAcceptance` |
| `/staff` | `app/staff/page.tsx` | `staff` | `StaffCenter` (`product/team-staff.tsx`) |
| `/companies/[companyId]` | `.../page.tsx` | `company` | Chat/conversa (`CompanyDashboard`) |
| `/companies/[companyId]/library` | `.../library/page.tsx` | `library` | `LibraryScreen` |
| `/companies/[companyId]/automations` | `.../automations/page.tsx` | `automations` | `AutomationsScreen` |
| `/companies/[companyId]/integrations` | `.../integrations/page.tsx` | `integrations` | `IntegrationScreen` (owner/admin) |
| `/companies/[companyId]/team` | `.../team/page.tsx` | `team` | `TeamScreen` |
| `/companies/[companyId]/developer` | `.../developer/page.tsx` | `developer` | `DeveloperScreen` (owner/admin) |
| `/companies/[companyId]/profile` | `.../profile/page.tsx` | `profile` | `ProfileScreen` |
| `/companies/[companyId]/admin` | `.../admin/page.tsx` | `admin` | `AdminScreen` (owner/admin) |
| `/docs/api` | `app/docs/api/page.tsx` | — (**server**) | `api-reference.tsx`, `api-docs.css`, `api-docs-logic.ts` |
| `/termos`, `/privacidade` | `app/termos/page.tsx`, `app/privacidade/page.tsx` | — (**server**) | `legal-layout.tsx` + `legal.css` |
| `/api/[...path]` | `app/api/[...path]/route.ts` | — | Proxy para o backend (não é UI) |

Layout raiz: `app/layout.tsx` (ThemeProvider `theme-provider.tsx`, importa `globals.css` e `theme-toggle.css`; `<html lang="pt-BR" suppressHydrationWarning>`).

### 1.2 Casca e navegação
- `app/product/shell.tsx` — `Shell` (header desktop com abas primárias, org, papel, sino, tema, menu da conta) e `NotificationToast` (toast caseiro com barra `toast-progress`, 6 s).
- `app/mobile-nav.tsx` — `useIsMobileShell` (<768px), `useVisualViewportHeight` (teclado iOS), `MobileShellHeader` + drawer `Sheet` (`components/ui/sheet.tsx`, com `motionProfile="arquivio"`). CSS: `mobile-chat.css`.
- `app/product/account-menu.tsx` — `AccountMenu`, `AvatarBadge`, `AvatarWithGear`.
- `app/product/notification-bell.tsx` — sino + lista de notificações (estado vazio incluso), `follow-toggle.tsx` (seguir pergunta).
- `app/product/org-picker.tsx` + `org-picker.css`; `app/theme-toggle.tsx/.css`; `app/brand.tsx/.css`.

### 1.3 Chat / conversa e "streaming" de resposta
- `app/product/chat-workspace.tsx` (395 linhas, ~35 KB, **o maior ponto de colisão**): `CompanyDashboard`, `ConversationLibraryWorkspace` (composer, escopo, histórico, viewer), `AssistantAnswer`, `AnswerFeedback`, `SourceDocuments/SourceDocumentRow`. CSS: `chat-workspace.css`.
- Composer: `mention-composer.tsx/.css`, `composer-keys.ts`, `question-scope.tsx/.css`, `tools-sidebar.tsx/.css`, `product/conversation-history.tsx`.
- Resposta: `answer-markdown.tsx`, `answer-blocks.ts`, `answer-display.ts`, `answer-actions.tsx`, `answer-reveal.tsx` + `answer-reveal-logic.ts`, `source-reading.tsx/.css` (logos das fontes acendendo em sequência).
- Viewer de fonte: `file-viewer.tsx/.css`, `pdf-viewer.tsx/.css`, `docx-viewer.tsx`, `file-viewer-logic.ts`.
- Extras: `clickup-task-modal.tsx`, `product/insights-panel.tsx`, `product/usage-panel.tsx`.
- **Streaming real não existe.** `answer-reveal-logic.ts` documenta: "the API answers with one JSON body, not a stream". O efeito de "digitação" é um reveal word-by-word (28 ms/palavra, 0,7–3,6 s) sobre texto já completo, com cortes seguros para markdown/citações. Enquanto espera, o usuário vê `SourceReadingStatus` + botão com "Consultando…" e `RefreshCw` girando. Streaming SSE exigiria mudança de backend (fora do escopo da UI).

### 1.4 Biblioteca / grade
- `app/product/library-screen.tsx` (264 linhas, **~48 KB, maior arquivo**): tela, sidebar de ferramentas, busca, breadcrumbs, painel de espaços sincronizados (`<dialog>`), paginação infinita.
- `app/product/library-grid.tsx` (grade/lista/tamanhos S/M/L, `CardMenu`), `library-indexing-badge.tsx`, `library-indexing-status.ts`, `use-library-items.ts`, `library-view-logic.ts`, `library-view.css`, `shared-ui.tsx` (`LoadingIndicator`, `Pagination`, `LibrarySidebarHeader`, `LibraryBreadcrumbs`).
- Sync: `sync-status.tsx/.css`, `sync-status-logic.ts` (spinner de logo, `SyncBanner`).

### 1.5 Integrações
- `app/product/integrations-screen.tsx` (**~41 KB**) + `integration-cards.css`, `provider-logo.tsx`, `provider-labels.ts`.

### 1.6 Automações
- `product/automations-screen.tsx` (lista + estado vazio), `automation-editor.tsx`, `automation-folder-picker.tsx`, `automation-recipients.tsx`, `automation-history.tsx`, `automation-report-view.tsx`, `automation-webhooks.tsx`, `automations-api.ts`, `automations-model.ts`, `automation-delivery-model.ts`.

### 1.7 Desenvolvedor
- `product/developer-screen.tsx` (`CodeBlock`, `McpSettings`, `ApiDocsCard`), `access-settings.tsx` (chaves de API, `<dialog>` do segredo), `developer-mcp-config.ts`.

### 1.8 Conta, time, admin
- `product/profile-screen.tsx`, `product/team-staff.tsx` (Team + Staff), `product/admin-screen.tsx`.

### 1.9 Onboarding / tour
- `organization-onboarding.tsx` + `onboarding.css` (wizard owner: conectar fontes → "Lendo arquivos" → "Preparando para o chat"); `conversation-tour.tsx` (tour em `<dialog>` com `data-tour="…"` nos alvos: `new-conversation`, `navigation`, `tools`…); `product/auth-screens.tsx` (`Loading`, `InvitationAcceptance`, `Onboarding` de organização, `InvalidCompany`).

### 1.10 Login e público
- `product/custom-login.tsx` + `custom-login.css` (split story/form, `ThemeToggle` flutuante); `landing-page.tsx` (444 linhas) + `landing.css` (519 linhas, o CSS mais animado do app); `docs/api/*`; `legal-layout.tsx`, `legal.css`.

### 1.11 Arquivos suspeitos (lixo de duplicata)
Rastreados no git e com espaço no nome: `app/product/custom-login 2.tsx`, `app/custom-login 2.css`, `public/favicon 2.svg`, `tests/landing-contract.test 2.mjs`. `custom-login 2.tsx` **diverge** de `custom-login.tsx`. Não são importados; devem ser removidos por uma lane (ou pela fundação) para não gerar confusão em buscas/edições.

---

## 2. Como o estilo e o motion funcionam hoje

### 2.1 Estilo
- **Tailwind 4.2** via `@tailwindcss/postcss` (`postcss.config.mjs`), `@import "tailwindcss"` em `app/globals.css`, mais `tw-animate-css` e o vendor `vendor/shadcn-tailwind-4.13.0.css`.
- **Tokens em CSS custom properties** em `globals.css` (`:root` + `.dark`, ~509 linhas): cores semânticas shadcn (`--background`, `--primary`…) **e** tokens próprios (`--paper`, `--ink`, `--sage`, `--line`, `--panel`, `--surface-raised`, `--control-edge`, `--focus-ring`…). Tema claro/escuro via `next-themes` (`.dark`). Paleta verde-floresta/papel.
- Mistura de três camadas: (a) utilitários Tailwind **inline em JSX muito denso** (arquivos de tela com linhas de 300+ caracteres, componentes múltiplos por linha; `style={{}}` só em 4 arquivos); (b) ~2.180 linhas de CSS por feature importado por componente (`chat-workspace.css`, `library-view.css`, `landing.css`, `mobile-chat.css`, `tools-sidebar.css`, `sync-status.css`, `onboarding.css`…); (c) shadcn vendorizado em `components/ui/*` (50+ componentes, **quase não usados**: só `sheet` em `mobile-nav.tsx` e `badge` em `library-indexing-badge.tsx`; `skeleton.tsx` e `spinner.tsx` existem e **ninguém importa**).
- ESLint ignora regras nos arquivos vendorizados (`components/ui/**`), então eles devem continuar "verbatim".
- Utilitários de cor ad hoc fora dos tokens: `text-rose-600/900`, `border-emerald-200`, `text-amber-300`, `text-violet-700` (toast, convites, staff) — não respeitam o tema escuro de forma consistente.

### 2.2 Motion existente
- **Nenhuma lib de animação** (sem framer-motion/motion, react-spring, auto-animate). Dependências relevantes: `tw-animate-css`, `vaul`, `sonner` (instalado, **não usado**: o app tem toast próprio), `embla-carousel-react`, `radix-ui` (Presence embutida nos primitives).
- **Camada opt-in `interface-motion.css` / `interface-motion.ts`** (H4, "direction A"): tokens `--aq-motion-enter: 200ms`, `--aq-motion-exit: 180ms`, easings, offset 6 px; atributos `data-arquivio-motion` / `data-arquivio-motion-root` / `.aq-motion-overlay`. Escopados com `:where()` (nenhum token em `:root`, nenhum seletor global de dialog) por decisão explícita. `playSurfaceEntry()` usa Web Animations e respeita `prefers-reduced-motion`. Em uso: `<dialog>` da tour, `<dialog>` do segredo de API (`access-settings.tsx`), dialog de espaços (`library-screen.tsx`), modal de ferramenta (`integrations-screen.tsx`), drawer mobile. **Saída (fechamento) de dialogs é imediata**; só o `Sheet` anima saída.
- Keyframes soltos e duplicados (todos feitos à mão, sem biblioteca comum): `sync-spin`, `sync-banner-slide`, `ts-slide`, `ts-turn`, `sync-slide` (onboarding.css), `library-sync-progress`, `library-card-spin`, `ts-skeleton-pulse`, `source-reading-pulse`, `answer-caret`, `answer-settle-in`, `fv-sheet-in/out`, `fv-cited-pulse`, `toast-progress`, ~10 `lp-*` na landing. Há três "barra indeterminada" diferentes (`sync-banner-slide`, `ts-slide`, `sync-slide`) e três spinners rotativos (`sync-spin`, `ts-turn`, `library-card-spin`) além de `animate-spin` Tailwind.
- `prefers-reduced-motion`: tratado em `interface-motion.css`, `answer-reveal.tsx`, `source-reading.tsx`, `file-viewer.tsx` e via `motion-safe:` nos spinners. Não há garantia global (keyframes soltos em outros CSS dependem de cada arquivo).
- Transições de rota: **nenhuma**. Trocar de aba remonta `ProductApp` (a própria nota `PENDING_NOTICE_KEY` existe porque "the route change remounts this component"), então o shell inteiro pisca a cada navegação e a tela mostra `Loading` de tela cheia.

### 2.3 Padrões de loading hoje
| Padrão | Onde | Observação |
|---|---|---|
| `LoadingIndicator` (RefreshCw girando + texto) | `product/shared-ui.tsx`; usado em `auth-screens` (Loading), biblioteca, equipe… | Único componente reutilizável; spinner genérico |
| Texto cru `<p role="status">Carregando …</p>` | Automações (`automations-screen.tsx:106`), folder-picker, recipients, history, report-view, webhooks, developer (MCP), insights, usage, conversation-history, access-settings, pdf/file viewer | Maioria das telas: **só texto, sem skeleton** |
| Skeleton próprio | só `tools-sidebar.tsx` (`.ts-skeleton`, `ts-skeleton-pulse`) | Único skeleton real do app |
| Barra de progresso com % | `sync-status.tsx`, onboarding `SyncProgress`, `library-sync-progress` | Dados reais de sync, 3 implementações |
| Botão com spinner + rótulo | composer (`Consultando…`), `Salvando…`, `Enviando…` | Sem estado "otimista" |
| Tela cheia | `Loading()` em `auth-screens.tsx`; "Preparando sua organização…" em `product-app.tsx:114`; `LandingPage` durante o loading de `/` | Duas telas de loading diferentes em sequência na entrada |
| Lazy chunk | `file-viewer.tsx` (`PdfViewer`/`DocxViewer` via `lazy`) | Fallback "Carregando visualizador…" |

### 2.4 Estados vazios e de erro
- **Vazios**: bons em copy, fracos em apresentação. Biblioteca tem `.library-empty` com ícone + título contextual (6 variantes) + CTA; automações tem card tracejado com CTA "Conectar pastas"; os demais são uma linha de texto (`Nenhum webhook cadastrado.`, `Nenhuma execução registrada…`, `Nenhuma notificação por enquanto…`). O primitive shadcn `components/ui/empty.tsx` existe e não é usado.
- **Erros**: três mecanismos coexistem — toast global (`setError`/`setNotice` → `NotificationToast`, erro não some sozinho; notice some em 6 s), `<div role="alert">` inline com "Tentar novamente" (biblioteca, escopo, onboarding) e `<p role="alert">` solto. Mensagens centralizadas em `messageFor()` (`types-and-api.tsx`). Não há error boundary de rota nem página 404/erro estilizada (`InvalidCompany` cobre só org inválida).

---

## 3. Problemas visuais e de UX por tela

Marcação: **[código]** = visto no código; **[verificar]** = hipótese a confirmar visualmente.

**Entrada / auth** (`product-app.tsx`, `auth-screens.tsx`, `custom-login.tsx`)
1. Sequência de até três loadings diferentes (landing → `Loading` → "Preparando sua organização…") sem transição entre eles; sensação de piscadas. [código]
2. Cores crus (`text-amber-300` no ícone de erro de convite/`InvalidCompany`) sobre fundo claro têm baixo contraste. [verificar]
3. `custom-login 2.tsx` duplicado e divergente. [código]

**Shell / navegação** (`shell.tsx`, `mobile-nav.tsx`, `account-menu.tsx`, `notification-bell.tsx`)
4. Trocar de aba usa `<a href>` + `onNavigate` e remonta tudo: sem indicador de rota ativa animado, sem transição, flash do loading global. [código]
5. Toast: posição `top-20` fixa, só barra de progresso; erro nunca some; sem empilhamento (apenas 1 mensagem por vez); cores `rose/emerald` fora de tokens. `sonner` instalado e sem uso. [código]
6. Menu da conta e sino abrem/fecham sem animação de entrada/saída. [verificar]
7. Header desktop denso: nome da org em pílula, papel, abas, 3 ações; truncamento por `max-w-36` em largura média. [verificar]

**Chat** (`chat-workspace.tsx`, `source-reading.tsx`, `answer-*`)
8. Resposta chega inteira após espera, sem skeleton de mensagem; só um botão girando + `SourceReadingStatus`. O reveal fake (até 3,6 s) pode atrasar leitura e some em histórico restaurado (consistência ok, mas sem entrada de bolhas de mensagem). [código]
9. Composer: `RefreshCw` no botão de envio e rótulo trocando entre "Enviar"/"Consultando…" (layout shift possível entre `composer-send-label`). [verificar]
10. Mensagem do usuário e resposta aparecem sem transição de entrada; scroll programático segue o reveal via `onProgress`. [código]
11. Estado inicial da conversa vazia e sugestões de pergunta: sem estado "primeiro uso" rico (depende de onboarding). [verificar]
12. `chat-workspace.tsx` concentra 35 KB: qualquer lane de chat é gargalo de merge. [código]

**Biblioteca** (`library-screen.tsx`, `library-grid.tsx`)
13. Loading inicial = ícone girando + texto numa área vazia (`library-empty`), em vez de skeleton de cards; ao paginar, texto "Carregando mais arquivos e pastas…" sem skeleton de linhas. [código]
14. Grade sem animação de entrada/stagger; mudança grade↔lista/tamanho S/M/L é salto seco. [código]
15. Estado vazio com 6 variantes é bom em copy, mas ícone estático. `library-card-spin` e `library-sync-progress` duplicam spinners de `sync-status.css`. [código]
16. Painel de espaços sincronizados em `<dialog>` com entrada animada mas saída imediata. [código]
17. `library-screen.tsx` com 48 KB: maior risco de colisão do projeto. [código]

**Integrações** (`integrations-screen.tsx`)
18. 41 KB num arquivo; "Carregando fontes conectadas…" e "Carregando espaços sincronizados…" em texto; modal de ferramenta anima só entrada. [código]

**Automações** (`automations-*.tsx`)
19. Lista: "Carregando automações…" em texto; estado vazio é um card tracejado simples (bom candidato a empty state ilustrado). [código]
20. Execução: "Consultando os arquivos e preparando o resultado…" estático durante geração do relatório; histórico/relatório/webhooks cada um com seu "Carregando …". Sem skeleton nem progresso. [código]
21. Editor/folder-picker/recipients: listas longas sem estado de skeleton; botões "Salvando…" sem feedback de sucesso inline. [código]

**Desenvolvedor** (`developer-screen.tsx`, `access-settings.tsx`)
22. `CodeBlock` copiar sem feedback animado (verificar); "Carregando informações do MCP…" em texto; chaves: lista vazia em frase única; segredo exibido em `<dialog>` com entrada animada. [código/verificar]
23. Já houve ajuste de hierarquia h1/h2 (commit 155a5d8); `.page-surface h1` força 17px, o override está em `product-layout.css`. Não regredir. [código]

**Conta / equipe / admin** (`profile-screen.tsx`, `team-staff.tsx`, `admin-screen.tsx`, `usage-panel.tsx`)
24. "Carregando equipe…/organizações…/uso…" em texto; tabelas sem skeleton; convites com "Enviando…". Blocos de acesso negado repetidos 3× em `product-app.tsx` (inline `ShieldCheck`) — candidatos a componente. [código]

**Onboarding / tour** (`organization-onboarding.tsx`, `conversation-tour.tsx`)
25. Wizard com progresso por etapas (`STEPS`) e barra `sync-slide`; transição entre etapas seca. Tour já tem entrada animada do card e troca de texto (`playSurfaceEntry`), mas o destaque do alvo (`data-tour`) não tem spotlight animado. [código/verificar]

**Docs/API e legal** (`docs/api/*`, `legal-layout.tsx`)
26. Páginas **server** sem JS de navegação: links precisam ser `<a>`. Sem motion; baixo valor, alto risco (ver §5). [código]

**Landing** (`landing-page.tsx`, `landing.css`)
27. É a única superfície com motion rico (`lp-*`, reveal, hero, demo). Qualquer unificação de tokens não deve quebrá-la; contrato testado em `tests/landing-contract.test.mjs`. [código]

---

## 4. Proposta de lanes (paralelismo sem colisão de arquivos)

### Princípio de propriedade
Cada arquivo tem **um único dono**. Lane Fundação (F) cria/edita os arquivos compartilhados; as lanes de área **importam** e nunca editam compartilhados. Se uma lane precisar de uma mudança num compartilhado, pede à Fundação (ou adia para a rodada seguinte). Ordem: **F primeiro (merge), depois A–F em paralelo.**

### Decisão de biblioteca de motion
Recomendação: **CSS-first, sem dependência nova** (as keyframes já existem; o app é Worker/edge e sensível a bundle). Adotar uma lib (`motion`) só se a Fundação concluir que presença/layout animation (lista que reordena, saída de itens) não é viável com CSS + `@starting-style` + `Presence` do Radix. Se adotada: um único arquivo de wrapper (`app/ui-motion/presence.tsx`) esconde a lib; as lanes só importam o wrapper.

### Lane F — Fundação (dona exclusiva dos compartilhados)
Arquivos que **só a F toca**:
- `frontend/app/globals.css` (tokens de motion `--motion-*`, easings, durações, utilitários `.skeleton`/shimmer, regra global `prefers-reduced-motion`)
- `frontend/app/interface-motion.css`, `frontend/app/interface-motion.ts` (+ `tests/interface-motion.test.mjs`)
- `frontend/components/ui/skeleton.tsx`, `frontend/components/ui/spinner.tsx`, `frontend/components/ui/empty.tsx`, `frontend/components/ui/sheet.tsx` (vendorizados: alterar só com cuidado, preservar regra de lint)
- `frontend/app/product/shared-ui.tsx` (`LoadingIndicator`, `Pagination`…)
- `frontend/app/product-layout.css`, `frontend/app/theme-toggle.css`, `frontend/app/brand.css`
- `frontend/eslint.config.mjs`, `frontend/package.json`, `frontend/postcss.config.mjs`, `frontend/vite.config.ts`
- Remoção de duplicatas: `app/product/custom-login 2.tsx`, `app/custom-login 2.css`, `public/favicon 2.svg`, `tests/landing-contract.test 2.mjs` (confirmar com o dono antes).

Entregáveis (novos arquivos, todos da F): `frontend/app/ui/` com:
1. `motion-tokens.css` (importado em `globals.css`): durações 120/180/240/360 ms, easings in/out/spring, deslocamentos, `@media (prefers-reduced-motion)` global; mapear os tokens `--aq-motion-*` existentes para os novos (mantém compatibilidade).
2. Primitives: `Skeleton` (variantes linha/círculo/card), `Shimmer` (CSS puro), `Spinner` (um só, substitui os 3), `ProgressBar` (determinada + indeterminada, substitui as 3 implementações), `LoadingBlock` (skeleton + `role=status` + texto sr-only), `EmptyState` (ícone/título/descrição/CTA), `Reveal`/`Stagger` (entrada com atraso por índice), `Presence` (entrada/saída por `data-state`), `useReducedMotion()`.
3. Transição de rota/tela: `ScreenTransition` (wrapper simples; sem View Transitions API a menos que seja suportado no vinext — validar).
4. Toast: decidir entre manter `NotificationToast` (dono: lane Shell) ou migrar para `sonner` (já instalado). Se migrar, o provider vai em `layout.tsx` (F) e a API no `product/shell.tsx` (Shell).
5. Documentação curta `frontend/app/ui/README.md` com contrato de uso (quando usar skeleton vs spinner, durações, a11y).
6. Testes: `tests/ui-primitives.test.mjs` (lógica pura; reduced-motion; tokens).

Também da F (arquivos compartilhados de camada superior): `frontend/app/layout.tsx`, `frontend/app/product-app.tsx` (substituir `Loading`/transições de tela e os 3 blocos de acesso negado por componentes), `frontend/app/product/types-and-api.tsx`, `frontend/app/product/auth-screens.tsx` (`Loading`).

### Lane 1 — Shell, navegação, conta, notificações
Dono de: `app/product/shell.tsx`, `app/mobile-nav.tsx`, `app/mobile-chat.css`, `app/product/account-menu.tsx`, `app/product/notification-bell.tsx`, `app/product/follow-toggle.tsx`, `app/product/org-picker.tsx`, `app/product/org-picker.css`, `app/theme-toggle.tsx`, `app/brand.tsx`.
Escopo: aba ativa com indicador animado, menus (conta/sino) com entrada/saída, toast moderno (empilhável, tokens de cor, auto-dismiss de erro opcional), drawer mobile.
Testes que tocam: `tests/account-menu.test.mjs`, `tests/mobile-history.test.mjs`.

### Lane 2 — Chat e resposta
Dono de: `app/product/chat-workspace.tsx`, `app/chat-workspace.css`, `app/answer-*.ts(x)` (`answer-markdown`, `answer-blocks`, `answer-display`, `answer-actions`, `answer-reveal`, `answer-reveal-logic`), `app/source-reading.tsx/.css`, `app/mention-composer.tsx/.css`, `app/composer-keys.ts`, `app/question-scope.tsx/.css`, `app/tools-sidebar.tsx/.css`, `app/product/conversation-history.tsx`, `app/product/insights-panel.tsx`, `app/product/usage-panel.tsx`, `app/clickup-task-modal.tsx`, `app/file-viewer.tsx/.css`, `app/pdf-viewer.tsx/.css`, `app/docx-viewer.tsx`, `app/file-viewer-logic.ts`.
Escopo: skeleton de mensagem do assistente, entrada de bolhas, composer, indicador "pensando" no lugar do spinner no botão, viewer de fonte com transição de painel, histórico.
**Atenção de risco**: dividir `chat-workspace.tsx` internamente antes de paralelizar mais gente nele. Se for preciso 2 pessoas, a lane 2 vira 2a (composer/histórico/sidebar) e 2b (resposta/viewer), com a extração do arquivo feita pela 2a no primeiro commit.
Testes: `answer-*.test.mjs`, `conversation-tour.test.mjs` (não, ver Lane 6), `composer-keys.test.mjs`, `mention-label.test.mjs`, `file-viewer-logic.test.mjs`.

### Lane 3 — Biblioteca e sincronização
Dono de: `app/product/library-screen.tsx`, `app/product/library-grid.tsx`, `app/product/library-indexing-badge.tsx`, `app/product/use-library-items.ts`, `app/library-view.css`, `app/library-view-logic.ts`, `app/library-indexing-status.ts`, `app/sync-status.tsx/.css`, `app/sync-status-logic.ts`.
Escopo: skeleton de cards/linhas, stagger da grade, transição grade↔lista/tamanho, empty states, unificar spinner/progresso de sync nos primitives da F, dialog de espaços com saída animada.
Nota: `library-screen.tsx` é o maior arquivo (48 KB); uma lane só.
Testes: `library-view-logic`, `library-indexing-*`, `sync-status`.

### Lane 4 — Integrações e onboarding
Dono de: `app/product/integrations-screen.tsx`, `app/integration-cards.css`, `app/provider-logo.tsx`, `app/provider-labels.ts`, `app/organization-onboarding.tsx`, `app/onboarding.css`, `app/new-space-options.ts`.
Escopo: cards de integração com skeleton, wizard de onboarding com transição de etapa e progresso, modal de ferramenta com saída.
Testes: `provider-labels`, `new-space-options`, `m49-wiring`.

### Lane 5 — Automações
Dono de: `app/product/automations-screen.tsx`, `automation-editor.tsx`, `automation-folder-picker.tsx`, `automation-recipients.tsx`, `automation-history.tsx`, `automation-report-view.tsx`, `automation-webhooks.tsx` (+ `automations-api.ts`, `automations-model.ts`, `automation-delivery-model.ts` somente se necessário).
Escopo: skeleton de lista/histórico, empty state com ilustração e CTA, progresso de execução ("Consultando os arquivos…" → etapas), feedback de salvar com confirmação inline, webhooks.
Testes: `automation-*.test.mjs`.

### Lane 6 — Desenvolvedor, equipe/admin/perfil, auth/login, tour
Dono de: `app/product/developer-screen.tsx`, `app/access-settings.tsx`, `app/developer-mcp-config.ts`, `app/product/profile-screen.tsx`, `app/product/team-staff.tsx`, `app/product/admin-screen.tsx`, `app/product/custom-login.tsx`, `app/custom-login.css`, `app/conversation-tour.tsx`, `app/modal-dismiss.tsx`.
Escopo: copiar com feedback, empty de chaves, tabelas com skeleton, login com transição, spotlight do tour.
Testes: `developer-*`, `conversation-tour`, `auth-navigation`.

### Lane 7 (opcional, risco isolado) — Páginas públicas
Dono de: `app/landing-page.tsx`, `app/landing.css`, `app/docs/api/*`, `app/legal-layout.tsx`, `app/legal.css`, `app/termos/page.tsx`, `app/privacidade/page.tsx`.
Escopo: só polimento; **proibido `next/link`** (ver §5). Contrato de landing em `tests/landing-contract.test.mjs`, `tests/public-page-links.test.mjs`, `tests/developer-heading-hierarchy.test.mjs`.

### Matriz de conflito (quem não pode tocar o quê)
| Arquivo compartilhado | Dono | Lanes 1–7 |
|---|---|---|
| `globals.css`, `interface-motion.*`, `components/ui/*`, `shared-ui.tsx`, `product-layout.css`, `product-app.tsx`, `layout.tsx`, `types-and-api.tsx`, `auth-screens.tsx`, `eslint.config.mjs`, `package.json` | F | só importam |
| CSS por feature | a lane dona da feature | não cruzam |
| `tests/*.test.mjs` | lane que toca o código testado | novos testes: um arquivo por lane, nome com prefixo da lane |

Regras de fluxo: cada lane commita só seus arquivos (`git add` específico, nunca `-A`); se precisar de um token novo, abre pedido à F e usa fallback `var(--x, valor)` até lá. Um merge da F antes das demais.

---

## 5. Armadilhas e restrições (registrar em todo briefing de lane)

1. **`<Link>` do vinext quebra no build minificado** (commit 155a5d8, `[M54]`): o bundle de produção faz tree-shaking das exportações de navegação que `next/link` carrega de forma lazy (`navigateClientSide`, `getPrefetchCache`…); o clique lança `e is not a function` e não navega. Em `/docs/api` e nas páginas legais (server-rendered) usar **`<a href>`**. Teste de regressão: `tests/public-page-links.test.mjs` (proíbe `next/link` e `<Link` em `app/docs/api/page.tsx` e `app/legal-layout.tsx`, e valida que todo `href` existe como rota). Lint: a regra `@next/next/no-html-link-for-pages` está desligada só para esses dois arquivos em `eslint.config.mjs`.
2. **`next/link` ainda é usado em outros arquivos**: `product/shell.tsx` (toast), `product/insights-panel.tsx`, `product/custom-login.tsx` (+ duplicata), `product/automations-screen.tsx`. Já existe indício de que o `Shell` usa `<a href>` com `onNavigate` para as abas (provavelmente pelo mesmo motivo). **Tratar `next/link` como suspeito em produção em todo o app**: não adicionar novos usos, e a lane dona de cada arquivo deve validar o clique no build minificado (não só `dev`) ou trocar por `<a>`/`router.push`.
3. **Sempre validar em build de produção** (`npm run build` + `npm start`/wrangler), não só `next dev`: tree-shaking e minificação mudam o comportamento (vide item 1). Qualquer API do Next acessada de forma lazy (prefetch, `router.prefetch`, `useLinkStatus`, View Transitions) é suspeita.
4. **Não usar `Canvas`** para artefatos visuais (AGENTS.md); artefato visual independente = PDF.
5. **Reduced motion**: toda animação nova deve respeitar `prefers-reduced-motion`; o padrão atual é visual-only, nunca dono de estado/foco/dismiss (`interface-motion.css`); duração aprovada 180–220 ms (`clampDuration`). Fugir disso exige aprovação.
6. **Escopo do `interface-motion.css`**: seletores `:where()` e atributos opt-in foram decisão deliberada (sem tokens em `:root`, sem seletores globais de `dialog`/`[data-slot]`). A F pode introduzir tokens globais novos, mas deve manter os `--aq-motion-*` funcionando.
7. **`components/ui/*` é vendorizado** (shadcn 4.17.0, regras de lint relaxadas): alterar só na F e preferir wrappers em `app/ui/` a editar o vendor.
8. **Elementos `data-tour`** (`new-conversation`, `navigation`, `tools`, …) são alvos do tour: renomear/mover quebra `conversation-tour.tsx`.
9. **`<dialog>` nativo**: saída animada exige manter o nó até o fim da animação (o `open` some imediatamente). Dialogs hoje fecham sem animação por esse motivo; resolver com classe `closing` + `animationend` na F, não ad hoc por lane.
10. **Toast**: `PENDING_NOTICE_KEY` em `sessionStorage` carrega avisos entre telas porque a troca de rota remonta `ProductApp`. Qualquer toast/transição de rota novo deve preservar esse contrato.
11. **Mobile**: `useVisualViewportHeight` e `--app-vh/--app-vt` controlam teclado iOS; não animar `height`/`top` do shell. Breakpoint do shell = `max-width: 767px`.
12. **Hierarquia h1/h2 da tela Desenvolvedor** (`product-layout.css` corrige `.page-surface h1 { 17px }`): preservar `tests/developer-heading-hierarchy.test.mjs`.
13. **Streaming**: não existe no backend; não projetar UI que dependa de tokens parciais sem alinhar com backend. O reveal atual deve continuar compatível com `answer-reveal-logic` (cortes seguros para markdown/citação).
14. Arquivos com nome duplicado (`* 2.*`) não são importados; ignorar nas buscas até remoção.
15. Densidade do JSX: muitos arquivos têm linhas de 300+ caracteres. Ao reformatar, fazer em commit separado do diff funcional para não gerar conflito de merge.

---

## 6. Prioridades sugeridas (impacto × esforço)
1. F: tokens de motion + `Skeleton`/`Spinner`/`ProgressBar`/`EmptyState`/`Reveal` + saída de `<dialog>`.
2. Substituir os ~30 "Carregando …" em texto por `LoadingBlock` (lanes 1–6).
3. Skeleton de biblioteca (lane 3) e de resposta no chat (lane 2) — as duas telas mais vistas.
4. Transição de tela e aba ativa (F + lane 1), toast moderno (lane 1).
5. Empty states ilustrados (automações, chaves, notificações).
6. Landing/docs (lane 7) por último, com o contrato intacto.
