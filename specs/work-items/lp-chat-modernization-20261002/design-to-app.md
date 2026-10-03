# Design → App — migração futura da direção A (não executada)

Status: **proposta**. Nada no app autenticado foi alterado nesta missão. Este documento mapeia o que a LP implementou (`frontend/app/landing.css`, escopo `.landing-page`) para uma migração futura em work-item próprio, com QA de auth/organização/permissões.

## 1. Tokens implementados na LP (fonte: `landing.css`, bloco `.landing-page`)

| Token LP (escopado) | Valor | Papel | Alias semântico proposto p/ app | Nota de migração |
| --- | --- | --- | --- | --- |
| `--lp-bg` | `#f5f7f4` | fundo da página | `--color-bg` | app hoje usa papel `#faf9f5`/branco; comparar densidade antes |
| `--lp-fg` | `#142b25` | tinta principal | `--color-fg` / `chat-ink` | |
| `--lp-fg-muted` | `#51635a` | texto secundário (≥4.5:1 em bg/surface/surface-muted) | `--color-muted` | substitui `#69746e` (baseline, contraste menor) |
| `--lp-accent` | `#1c6052` | marca, CTA, selecionado | `--color-accent` / `source-ink` | idêntico ao verde atual do app |
| `--lp-accent-hover` | `#124b3f` | hover CTA | `--color-accent-hover` | idêntico |
| `--lp-brand-ink` | `#243b35` | wordmark | (manter em `brand.css`) | marca compartilhada, não migrar sem aprovação |
| `--lp-surface` | `#ffffff` | painéis, shell de chat | `chat-surface` | |
| `--lp-surface-muted` | `#eaf2ec` | lista de fontes, balão do usuário, faixa "Como funciona" | `source-surface` | |
| `--lp-surface-tint` | `#eef4e4` | selo "Prévia ilustrativa" | `--color-surface-tint` | |
| `--lp-border` | `#d5dfd7` | divisores decorativos | `--color-border` | não usar sozinho para limite de controle |
| `--lp-border-strong` | `#718379` | borda de controles (≥3:1) | `--color-border-control` | pills, composer, campo de busca |
| `--lp-focus` | `#965b0d` | anel de foco 3 px / offset 3 px | `focus-ring` | substitui `#bb761c` do baseline |
| `--lp-lime` | `#d9f279` | marcador gráfico, `::selection`, destaque no fechamento escuro | `--color-signal` | nunca texto sobre claro; ok sobre `#1c6052` |
| `--lp-font-display` | Manrope variável (`Arquivio LP Display`) | títulos 650 | `--font-display` | renomear família ao promover para global |
| `--lp-font-body` | IBM Plex Sans variável (`Arquivio LP Text`) | UI/corpo | `--font-sans` | app hoje usa Arial; migrar com teste de densidade |
| `--lp-radius-sm` / `--lp-radius-md` | 8 px / 16 px | controles / painéis | `--radius-sm` / `--radius-md` | um raio por papel; 24 px só no fechamento |
| `--lp-fast` / `--lp-case` / `--lp-disclosure` / `--lp-slow` | 140 / 200 / 200 / 240 ms | hover-press / troca de caso / FAQ-menu / reveal (stagger 20–40, total ≤280) | `--aq-motion-hover` / `-case` / `-disclosure` / `-reveal` | reduced-motion zera (H4) |
| `--lp-ease` / `--lp-ease-in-out` | `cubic-bezier(.2,.8,.2,1)` / `(.4,0,.2,1)` | | `--ease-out` / `--ease-in-out` | |

Fontes: `frontend/public/landing/fonts/{manrope,ibm-plex-sans}-latin-var.woff2` (subset Latin + Latin-1 + Latin Ext-A parcial + pontuação, OFL incluída). Para o app, mover para `public/fonts/` e declarar `@font-face` uma vez (ex.: em `globals.css`) **em work-item próprio**.

## 2. Componentes da LP → equivalentes no app

| Componente LP (classe) | Estados implementados | Equivalente no app | Passo de migração |
| --- | --- | --- | --- |
| Botão primário `.landing-button` | normal, hover (escurece + seta 2 px), active, focus-visible | botões primários de `product/*` | extrair primitive `Button variant=primary` com tokens acima |
| Link de ação `.landing-login` | hover underline, focus | links secundários | `Button variant=link` |
| Pills de caso `.landing-demo-options button` | `aria-pressed` false/true, hover, focus | seletor de escopo / tabs | `ToggleGroup` com borda `border-strong` |
| Shell de chat `.landing-app-shell` | estático | workspace de conversa (`chat-workspace.css`) | adotar superfícies `chat-surface`/`source-surface` |
| Balão do usuário `.landing-user-message` | com/sem menção | mensagens do usuário | raio 14/14/4/14, `surface-muted` |
| Menção `.landing-mention-line` | — | `mention-composer` | chip com borda accent 27% |
| Resposta + autor `.landing-answer` | com fontes / sem evidência | resposta da IA | avatar accent + glifo lima |
| Lista de fontes `.landing-answer-sources` | 0, 1, 3 + "Ver mais" | evidências/citações | linhas 40 px, número tabular, provedor à direita (quebra abaixo no mobile) |
| Composer `.landing-composer` | ilustrativo | `mention-composer.tsx` | borda `border-strong`, raio 12 |
| Rail Biblioteca `.landing-app-sources` | ilustrativo | `tools-sidebar` / biblioteca | linhas 40 px, pasta indentada em `surface-muted` |
| Busca `.landing-app-search` | ilustrativo | busca por nome da biblioteca | campo + botão 40 px |
| FAQ `.landing-faq-list details` | closed/open, hover, focus | accordions de ajuda | summary 64 px, chevron 180 ms |
| Nota de compartilhamento `.landing-process-note` | estático | avisos/alerts informativos | borda esquerda 4 px accent |

## 2.1 Breakpoints implementados (rodada 2)

| Faixa | Composição |
| --- | --- |
| ≥1280 | grade 42/58, gap 48; prévia com rail Biblioteca (168 px) à esquerda do chat |
| 1024–1279 | grade 42/58, gap 40; dentro da prévia: chat → Biblioteca → Busca empilhados; integrações 2×2; H1 ≤ 44 px |
| ≤1023 | hero e prévia empilhados; arte I-01 estática abaixo do texto de Rotina |
| ≤767 | workspace chat → Biblioteca → Busca; processo em coluna |
| ≤560 | ritmo compacto; casos em 3 colunas (rótulos em 2 linhas, alvo 52 px); H1 34 px, chat 16 px, avisos 13 px |

Para o app: a regra "rail lateral só com ≥ ~700 px de largura útil de chat" é reaproveitável no workspace de conversa. Nenhum token de cor, tipo ou motion mudou nesta rodada; os avisos passaram a usar 13 px (`--text-xs`) de forma consistente.

## 3. Estados que a LP **não** implementa (pertencem ao app)

A LP não busca dados nem aceita formulário. Para o app, prever com os mesmos tokens: Loading (skeleton com a forma real da lista de fontes, nunca spinner genérico), Empty (sem fontes conectadas → CTA de integração para Owner/Admin), Error (`--danger #a83435`, mensagem + "Tentar novamente"), Populated, Edge (nome de documento longo quebra com `overflow-wrap:anywhere`; resposta sem evidência mantém paridade visual). Formulários: Untouched / Dirty-valid / Submitted-pending. Referência visual: `direction/screenshots/fixture/state-*.png`.

## 4. Sequência proposta (outro work-item)

1. Inventariar tokens atuais do app (`globals.css`, `brand.css`, CSS por tela) e medir contraste/densidade.
2. Promover os tokens da §1 como primitives + aliases semânticos sem renomear estados existentes; manter `brand.css` intacto.
3. Provar na tela de conversa (resposta + fontes + sem evidência) com Loading/Empty/Error/Populated/Edge.
4. Migrar componente a componente (§2), com testes de auth, organização e permissões; display do app menor que o hero da LP; UI em IBM Plex Sans 16/1.55.
5. Remover as duplicações `.arquivio-brand` de `landing.css` só quando `brand.css` absorver os tamanhos.

## 5. Riscos conhecidos

- `landing.css` é carregado também no bundle do app (importado por `landing-page.tsx` via `product-app.tsx`); por isso todo seletor novo é `.landing-*`/`.landing-page` e as famílias de fonte têm nomes exclusivos. O teste `frontend/tests/landing-contract.test.mjs` falha se surgir seletor fora desse escopo.
- As regras `.arquivio-brand` sem escopo foram mantidas do baseline (mesmo comportamento que o app já recebia).

## 6. Motion H4 — LP e cinco modais existentes (implementado)

Escopo só de motion; cores, tipos e layout do app continuam como estão. Contrato: `motion-extension/MOTION-SPEC.md`. Evidência: `motion-extension/evidence/build/README.md`.

**Camada reutilizável opt-in** (sem tokens no `:root`, sem seletor global):
- `frontend/app/interface-motion.css`: tokens `--aq-motion-enter 200ms`, `--aq-motion-exit 180ms`, `--aq-motion-ease-enter cubic-bezier(.2,.8,.2,1)`, `--aq-motion-ease-exit cubic-bezier(.4,0,1,1)`, `--aq-motion-offset 6px`, `--aq-motion-opacity-start .92`, declarados só em `[data-arquivio-motion]`, `[data-arquivio-motion-root]` e `.aq-motion-overlay`. Keyframes `aq-panel-in`, `aq-panel-in-scale`, `aq-backdrop-in/out`, `aq-backdrop-color-in`, `aq-sheet-in/out`. Com `prefers-reduced-motion` tudo vira `animation: none`.
- `frontend/app/interface-motion.ts`: `playSurfaceEntry(targets, options)` usa WAAPI só onde o CSS não reinicia sem remount (troca de etapa do tour). Cancela o ciclo anterior, respeita o reduced-motion inicial e o dinâmico, não usa fill. Não tem timers, foco, rede, storage, nem estado open/close.

| Papel (atributo) | Uso | Regra |
| --- | --- | --- |
| `data-arquivio-motion-root` em `<dialog>` + `data-arquivio-motion="panel"` no filho | M1, M4 | painel interno entra a cada `[open]`; backdrop só por opacity; root nunca transformado; fechar imediato |
| `.aq-motion-overlay` + `data-arquivio-motion="panel-scale"` | M2 (`ModalOverlay` via `className`) | overlay anima a cor, nunca opacity; painel .92/Y6/.99 no mount; unmount imediato |
| `data-arquivio-motion="tour-card"` + helper | M3 | card entra com o dialog; etapa anima só o texto, sem remount |
| `SheetContent motionProfile="arquivio"` → `sheet-panel`/`sheet-backdrop` | M5 | substitui slide/500/300 só nessa instância; entrada 200 e saída 180 pelo Presence existente; default do Sheet intacto |

**Para migrar outras telas do app:** adicione o atributo do papel ao nó visual interno (nunca ao root fixo/modal), importe `interface-motion.css` e não segure a saída de superfícies que hoje fecham imediatamente. Confirms nativos e primitives sem uso (Dialog, AlertDialog, Drawer, Command, Sidebar) ficaram de fora de propósito. Em estados de dados (loading, erro, polling, catálogo, citações), nada anima: eles aparecem no mesmo tick.
