# Motion foundation [M56] — contrato para as lanes de tela

Lane Fundação entregue. Padrões vêm de `specs/design/motion-reference-rogueon/` (só padrões; identidade ArquivIO mantida: verde, tokens existentes).

## 1. Decisão: CSS puro, sem biblioteca

Nenhuma dependência nova (`package.json` intacto). Motivos: (a) o app roda em Worker e é sensível a bundle; (b) tudo o que a referência pede é `opacity`/`transform`/`grid-template-rows` + estado por `data-*`, que CSS cobre; (c) saída de nós (o único ponto onde CSS puro dói) é resolvida por `Transition` (timer curto, desmonta após a saída) e `closeDialogAnimated` para `<dialog>`; (d) zero risco de tree-shaking/minificação no vinext. Build de produção verificado (`npm run build`, exit 0); SSR não quebra (hooks de browser só em `useSyncExternalStore` com snapshot de servidor `false`). Reavaliar `motion` só se surgir reordenação animada de listas (layout animation), o que nenhuma lane pede hoje.

## 2. Onde está o quê

| Arquivo | Conteúdo |
|---|---|
| `frontend/app/ui/motion-tokens.css` | Tokens `--motion-*`, `--ease-*`, keyframes `mo-*`, classes `.mo-*`, reduced-motion. Importado por `globals.css` (todas as telas já têm). |
| `frontend/app/ui/index.ts` | **Único ponto de import**: `import { … } from "@/app/ui"` (ou relativo). |
| `frontend/app/ui/{skeleton,loading,chat,transitions,feedback}.tsx` | Componentes. |
| `frontend/app/ui/motion-logic.ts` | Lógica pura (stagger, progresso, `MOTION_MS`). |
| `frontend/app/ui/dialog-motion.ts` | `closeDialogAnimated`. |
| `frontend/app/ui-demo/` | Vitrine interna `/ui-demo` (404 em produção salvo `UI_DEMO=1`; funciona em `npm run dev`). |
| `frontend/tests/ui-primitives.test.mjs` | 10 testes (tokens ↔ `MOTION_MS`, reduced-motion, variantes, sem literais). |

`interface-motion.css`/`.ts` seguem valendo (`--aq-motion-*`, `data-arquivio-motion`); ganhou só a saída por `data-closing`.

## 3. Tokens (em `:root`)

- Durações: `--motion-instant 80ms`, `fast 120`, `base 180`, `medium 280`, `slow 420`, `enter 600` (só 1ª carga/onboarding); loops `--motion-loop-typing 1000`, `loop-shimmer 2400`, `loop-pulse 2000`, `loop-spin 800`, `loop-indeterminate 1400`, `--motion-caret-blink 1060`.
- Easings: `--ease-out` (padrão), `--ease-in` (saídas), `--ease-in-out` (loops), `--ease-standard` (accordion/drawer), `--ease-spring`, `--ease-pop` (bolha/chip), `--ease-linear`, `--ease-blink`.
- Distâncias/escalas: `--motion-dist-xs 2px | sm 8 | md 14 | lg 24`, `--motion-scale-press .975`, `--motion-scale-hover 1.02`, `--motion-scale-pop-from .8`, `--motion-stagger-sm 30ms | md 80 | lg 150`, `--motion-blur-glass 12px`, `--motion-focus-width/offset 2px`.
- Skeleton: `--skeleton-base/--skeleton-peak` (tinta `--ink` do tema; funciona em claro e escuro).

**Reduced motion** (`prefers-reduced-motion: reduce`): durações viram `0.01ms`, distâncias `0`, escalas `1`, staggers `0`; regra global `*` com `animation/transition-duration: .01ms !important`, `iteration-count: 1` (vale também para keyframes antigos de outros CSS). Loops têm equivalente estático: skeleton = cor sólida, spinner = anel parado, pontos = opacidade fixa, caret oculto, progresso indeterminado = barra cheia 50%. Reveal por scroll só existe em `no-preference` (padrão = visível). `Transition` desmonta sem esperar. Sempre acompanhe estados de espera com texto (`role="status"`, `aria-busy`, `sr-only`).

## 4. API dos primitives

Todos aceitam `className`; os com `as` aceitam o elemento (`"li"`, `"span"`…). Texto default em PT-BR.

**Carregando**
- `<LoadingBlock label?>` — envelope acessível (`role=status`, `aria-busy`, texto `sr-only`). Coloque skeletons dentro. **Substitui os `<p role="status">Carregando …</p>`.**
- `<Skeleton width height>`, `<SkeletonLine>`, `<SkeletonBlock height>`, `<SkeletonAvatar size>`, `<SkeletonText lines>`, `<SkeletonCard media lines>`, `<SkeletonList rows avatar>` — decorativos (`aria-hidden`), larguras determinísticas (SSR estável).
- `<Spinner size label?>` — único spinner (com `label` vira `role=status` + texto). Substitui `sync-spin`/`ts-turn`/`library-card-spin`/`animate-spin`.
- `<ProgressIndicator value? label>` — `value` 0–100 determinada, omitido = indeterminada. Substitui as 3 barras (`sync-banner-slide`, `ts-slide`, `sync-slide`).
- `<Shimmer variant="surface"|"text">` — `text` para "Consultando os arquivos…".
- Regra: **skeleton** quando se sabe a forma do conteúdo (listas, cards, tabelas); **spinner** só inline em botão/ação curta; **progresso** quando há etapa/percentual; texto cru nunca sozinho.

**Chat**
- `<TypingIndicator label?>` — 3 pontos, altura fixa de 20px, some ao primeiro conteúdo (você desmonta).
- `<StreamingText state="streaming"|"idle"|"done">` — cursor sólido durante tokens, pisca ocioso, sem cursor em `done`. Hoje o backend não faz streaming; use com o reveal existente (`answer-reveal`), sem alterar `answer-reveal-logic`.
- Bolha do usuário: `<Enter variant="pop" origin="user">`; resposta: `origin="assistant"` (origem do scale no canto da cauda).

**Transições**
- `<Enter variant="fade|slide|slide-x|scale|pop" delay origin>` — entrada na montagem.
- `<Transition show variant exitMs>` — entrada e saída (nó fica montado até a saída acabar). Para menus, popovers, painéis, banners condicionais.
- `<StaggerItem index step="sm|md|lg">` — item de lista; índice limitado a `STAGGER_MAX = 8` (o resto entra junto com o 8º). `sm` linhas, `md` cards, `lg` elementos de peso. Helper: `staggerStyle(i)`.
- `<Reveal variant="slide|fade">` — scroll reveal nativo (`animation-timeline: view()`), sem JS; fallback = visível.
- `<ScreenTransition screenKey>` — entrada de tela (fade+8px, 280ms). Só entrada: a rota anterior já desmonta (`ProductApp` remonta a cada navegação). Não use View Transitions API (lazy do Next, suspeita no build minificado).
- `closeDialogAnimated(dialogEl, onClosed?)` — saída de `<dialog>` nativo (marca `data-closing`, CSS em `interface-motion.css` anima painel/backdrop, depois `close()`). Para Esc: `onCancel={(e) => { e.preventDefault(); closeDialogAnimated(ref.current); }}`. Só funciona em dialogs com `data-arquivio-motion-root` + `data-arquivio-motion="panel"`.
- `useReducedMotion()` — só para lógica JS (timers); estilos já são cobertos pelo CSS.

**Estados e feedback**
- `<EmptyState icon title description actions>` (`role=status`, ícone com pop) e `<ErrorState …>` (`role=alert`, tokens `--danger-*`). `icon` é um `ReactNode` (use lucide-react); `actions` com "Tentar novamente".
- `<ToastViewport>` + `<Toast open tone="info|success|error" title description action duration onDismiss>` — entrada e **saída animadas**, pausa no hover, `duration={null}` não fecha sozinho (use para erros). O `NotificationToast` atual (`shell.tsx`) segue existindo: a migração é da Lane 1, e **precisa preservar `PENDING_NOTICE_KEY`**.

**Hover / press / foco (classes)**
- `.mo-interactive` (botões/linhas: cor `fast`, press `translateY(2px) scale(.975)`; `data-variant="primary"` ganha glow só no hover), `.mo-interactive-card` (card clicável: sobe 2px, press), `.mo-field` (input: borda + halo de foco), `.mo-focus` (anel 2px/offset 2px = `--focus-ring`), `.mo-arrow` (ícone de seta que anda 2px no hover/foco do pai `a`/`button`), `.mo-check-pop` (ícone de concluído), `.mo-pulse` (indicador "vivo"). Observação: `.product-app :is(button,a):focus-visible` (globals) usa 3px e vence `.mo-focus` dentro do app; é intencional, não brigue com ele.

## 5. Regras para as lanes de tela

**Pode:** importar de `app/ui`; usar `var(--motion-*)`/`var(--ease-*)` e as classes `.mo-*` em CSS/JSX da sua feature; criar keyframes **da sua feature** só com os tokens; trocar `Loading…`, spinners, barras e vazios pelos primitives; trocar `RefreshCw animate-spin` por `<Spinner>`.

**Não pode:**
1. Editar arquivos da fundação: `app/ui/**`, `globals.css`, `interface-motion.*`, `components/ui/*`, `shared-ui.tsx`, `product-layout.css`, `product-app.tsx`, `layout.tsx`, `types-and-api.tsx`, `auth-screens.tsx`, `eslint.config.mjs`, `package.json`. Precisa de token/variante nova? Use `var(--x, fallback)` e peça à fundação.
2. Escrever `ms` ou `cubic-bezier` literais em CSS novo (só tokens); animar `width/height/top/left` (só `opacity`, `transform`, `grid-template-rows`; nunca `height`/`top` do shell mobile — `--app-vh/--app-vt`).
3. Entrada > 420ms em UI funcional (`--motion-enter` só em 1ª carga/onboarding); loops sem versão reduced-motion (os primitives já têm; keyframes próprios herdam a regra global).
4. Usar `next/link` novo, View Transitions API ou qualquer API de navegação lazy do Next (quebra no build minificado, ver auditoria §5); `<a href>`/`router.push`.
5. Mover/renomear `data-tour`, mexer em `PENDING_NOTICE_KEY`, `answer-reveal-logic`, hierarquia h1/h2 da tela Desenvolvedor.
6. Deixar animação ser dona de estado, foco ou dismiss (visual-only). Estado por `data-*`/`aria-*`.
7. Usar Canvas para artefatos visuais.

**Checklist por tela:** loading = `LoadingBlock` + skeleton com a forma real; vazio = `EmptyState`; erro = `ErrorState` com retry; listas ≥ 3 itens com `StaggerItem` (máx. 8); sem layout shift (indicadores com altura fixa); testar com reduced-motion ligado; validar no **build de produção**, não só `dev`.

## 6. Vitrine e verificação

`npm run dev` → `http://localhost:5173/ui-demo` (em produção = 404). Para testar reduced-motion: DevTools → Rendering → "Emulate prefers-reduced-motion". Verificação da entrega: lint exit 0, `tsc --noEmit` exit 0, build exit 0, `node --experimental-strip-types --test tests/*.test.mjs`: 190 pass / 4 fail (as mesmas 4 falhas — `answer-markdown`, `automation-editor`, `automation-recipients`, `library-indexing-badge` — existem sem estas mudanças; linha de base 180/4). Screenshots da vitrine em `/private/tmp/claude-501/motion-foundation/` (não versionados). Limite honesto: screenshots estáticos não provam as animações em movimento (validadas por tokens/CSS e testes, não por vídeo) e só foi inspecionado o tema escuro; o claro usa os mesmos tokens.

## Modais: superfície compartilhada [M56]

A paleta base de todos os dialogs agora vem de Gerenciar integração (`integration-modal`): tokens `--modal-*` em `globals.css`, consumo central em `surfaces.css`. Contrato completo, inventário e evidências em `surfaces-elevation.md`, seção 7. Backdrop usa primary a 40% sem blur nos dois temas. Cada modal conserva seus tempos, variantes, saída, foco e layout; `automation-modal.css` mantém geometria/mobile e usa a mesma paleta. Novos dialogs devem usar `<dialog>`, `ModalOverlay` ou as primitivas Dialog/AlertDialog para herdar automaticamente o padrão.

## Botões [M56]

Variantes de botão (primary, secondary, ghost, destructive, danger-soft, danger-ghost, success, info) com estados hover/press/focus/disabled/loading usam os tokens de motion (`--motion-fast`, `--motion-base`, `--motion-loop-spin`, `--motion-dist-xs`, `--motion-scale-press`). Contrato e hierarquia por tela: `surfaces-elevation.md`, seção 8.
