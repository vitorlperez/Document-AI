# Superfícies e elevação [M56] — contrato visual

Problema: em várias telas cards/boxes tinham o mesmo tom do fundo (empty state da Biblioteca `--sage` sobre painel branco; no escuro, `--panel` sobre `--paper` quase idênticos). A hierarquia só aparecia por uma borda de ~1,2:1.

## 1. Referências (só padrões, sem copiar marca)

- **Material 3** — papéis de superfície por tom (`surface container lowest … highest`), sem depender de elevação numérica; em tema escuro, *mais alto = mais claro*, e sombra fica para o que realmente sobrepõe (diálogos, menus). ([blog Material](https://material.io/blog/tone-based-surface-color-m3))
- **Radix Colors** — passo 2 = fundo sutil/card, passo 6 = borda de elemento *não* interativo, passos 7–8 = borda de interativo e foco. Daí: borda sutil ≠ borda forte. ([escala Radix](https://radix-ui.com/colors/docs/palette-composition/understanding-the-scale))
- **Vercel/Geist (resumos de terceiros)** — borda de ~8% de preto fazendo papel de sombra de 1px, sombra de repouso curta + ambiente larga, raio de 8/12px. Vendido como degraus: plano → anel → elevado.
- **Rogueon (captura em `motion-reference-rogueon/`)** — glass só em overlays (blur 12px, fundo 62–94% opaco, *hairline interna* 12–14% branco) → virou o `inset 0 1px 0` do dark.
- **shadcn/ui, Linear, Apple HIG** — pelo conhecimento geral: card = fundo + borda + sombra mínima; poço (input/empty) mais fundo que o pai; hierarquia por *camadas* (fundo → conteúdo → flutuante), nunca por sombra pesada.

## 2. Níveis (tokens em `frontend/app/globals.css`, regras em `frontend/app/surfaces.css`)

| Token | Claro | Escuro | Uso |
|---|---|---|---|
| `--surface-canvas` (= `--background`, `--paper`) | `#efeee5` | `#080e0b` | fundo da página, atrás de tudo |
| `--surface` (= `--panel`) | `#ffffff` | `#121c17` | painel principal (`.page-surface`, `.workspace-frame`), conteúdo corrido |
| `--surface-raised` (= `--card`, `bg-raised`) | `#ffffff` | `#1b2a24` | card dentro de painel, linha clicável, bolha |
| `--surface-sunken` (= `--sage`) | `#eaede2` | `#0c1410` | poços: sidebars, empty/error states, inputs (escuro), segmented, evidências |
| `--surface-overlay` (= `--popover`) | `#ffffff` | `#243730` | popover, menu, dialog, drawer, toast |
| `--edge-subtle` (= `--line`, `--border`, `--card-edge`) | `#d3d6c8` | `#2c3d35` | borda de card/painel/separador |
| `--edge-strong` (= `--input`, `--dialog-edge`) | `#aeb5a5` | `#4a6458` | empty (tracejada), card em hover, overlay, botão outline |
| `--edge-highlight` | transparente | `rgb(255 255 255 / .05)` | brilho de 1px no topo (só escuro) |

Inputs/selects/textarea usam `--control-edge` (`#7b857f` claro / `#6b8479` escuro, ≥3:1 sobre o fundo — WCAG 1.4.11); `--edge-strong` (≈2:1) é só para bordas de superfície e hover. Texto: `--foreground`/`--muted-foreground` com AA (≥4,5:1) em todos os fundos acima — verificado em `tests/surfaces-elevation.test.mjs`. `--muted-foreground` claro escureceu de `#657069` para `#5a655e` (no canvas novo o antigo dava 4,42:1).

### Sombras (3 níveis)

| Token | Quando | Claro | Escuro |
|---|---|---|---|
| `--elev-1` repouso | painéis, cards, header, botões outline | 1px + 2px/6px ink 8–10% | 1px preto 50% + highlight |
| `--elev-2` hover/foco | card clicável em hover, composer em foco | 2px + 10px/22px ink 20% | 4px/12px preto 55% + highlight 7% |
| `--elev-3` overlay | popover, menu, dialog, drawer, toast | 4px + 24px/52px ink 32% | duas camadas preto + highlight 9% |
| `--elev-inset` | poços: input, empty, segmented | inset 1px/2px ink 7% | inset 1px/3px preto 50% |

`--elev-ink` (`36 59 53` no claro) tinge a sombra de verde (identidade ArquivIO) em vez de cinza. No escuro a elevação vem **do tom** (canvas < sunken < surface < raised < overlay) + borda; a sombra só reforça.

### Raios

`--radius-control` 8px (inputs, botões, chips) · `--radius-card` 12px (cards, empty, menus) · `--radius-panel` 14px (painéis, dialogs). Mobile: painel usa o raio de card e volta a ter borda lateral (antes ia de ponta a ponta sem borda e se confundia com o fundo).

## 3. Quando usar cada nível

1. A página é `canvas`. O conteúdo principal vive num `surface` (painel) com borda sutil + `elev-1`.
2. Dentro do painel, agrupamentos independentes (seções, integrações, automações, chaves) são `raised`: borda sutil + `elev-1`. Clicáveis: hover → `elev-2`, borda forte, sobe 2px (`--motion-dist-xs`, `--motion-base`, `--ease-out`); em `prefers-reduced-motion` não translada.
3. O que é *vazio, lateral ou recuado* é `sunken` (poço): empty/error states (borda tracejada forte + inset), sidebar de ferramentas, lista de conversas, evidências, controle segmentado.
4. Inputs/selects/textarea: borda `control-edge`, `elev-inset`; branco no claro, `sunken` no escuro; foco = anel `--focus-ring` (já existente, `.mo-field`). Textarea transparente (composer, seletor de pastas) não ganha moldura própria para não duplicar borda.
5. Tudo que flutua é `overlay` + `elev-3` + borda forte: menus (`[role=menu]`), popovers do cabeçalho, export, mention/escopo, dialogs nativos, drawer mobile, toasts.
6. Regra de bolso: **nenhuma caixa pode ter o mesmo tom do pai sem borda forte ou sombra**.

Utilitários Tailwind `shadow-xs/sm` → `elev-1`, `shadow-md/lg` → `elev-2`, `shadow-xl/2xl` → `elev-3`; `bg-sunken`, `bg-canvas`, `bg-overlay`, `border-edge`, `border-edge-strong` existem no `@theme`.

## 4. Como está aplicado

`surfaces.css` é importado por `globals.css`; seus seletores terminam em `:not(.s_)` (nunca casa) para ganhar +1 de especificidade sobre CSS por tela importado depois. Cobre: header (desktop e mobile), `.page-surface`/`.workspace-frame`/`.auth-card`, seções diretas de `.page-surface > .grid`, `.integration-tool-card`, `.library-card`, `.org-picker-option`, qualquer `bg-panel|bg-raised` com borda dentro do painel, empty/error (`.library-empty`, `.state-panel`), sidebars, inputs, composer, menus/popovers/dialogs/drawer/toast, tabelas (cabeçalho em `--heading-bg`, linhas com hairline e hover sunken).

## 5. Antes / depois

Capturas (não versionadas): antes em `/private/tmp/claude-501/ui-final/` (claro) e `/private/tmp/claude-501/ui-surfaces-before/` (escuro); depois em `/private/tmp/claude-501/ui-surfaces/` com `contact-sheet.pdf` (antes × depois).

| Tela | Antes | Depois |
|---|---|---|
| Biblioteca (vazio) | box `#f3f5ef` tracejado sobre painel branco; sidebar quase igual ao painel | poço `#eaede2` com borda forte e inset; sidebar sunken; painel branco sobre canvas `#efeee5` com sombra |
| Automações / Integrações | cards brancos sobre painel branco, só borda 1,2:1 | cards `raised` com borda e `elev-1`, hover `elev-2`; "Em breve" vira poço tracejado |
| Escuro (todas) | painel `#141f1b` sobre `#0e1613`, cards iguais ao painel | canvas `#080e0b` → painel `#121c17` → card `#1b2a24` → overlay `#243730`, bordas e highlight |
| Menus/popovers | sombra única, fundo = painel | `overlay` + borda forte + `elev-3` |
| Mobile | painel sem borda lateral, cabeçalho = canvas | painel com borda e raio, cabeçalho em superfície própria com sombra |

## 6. Limites honestos

- Telas públicas (landing, docs, legais, login custom) têm CSS próprio (`landing.css`, `legal.css`, `custom-login*.css`); só herdam os tokens de canvas/borda via `--paper`/`--line`. Não receberam as regras de card.
- Screenshots estáticos: o hover (lift) foi validado por regra CSS/tokens, não por captura em movimento.
- O contraste de bordas decorativas (card/painel) é perceptível mas < 3:1; só bordas de controle (`--control-edge`, em inputs) seguem o critério de 3:1 onde ele é exigido.

## 7. Paleta compartilhada de modais [M56]

Referência: **Gerenciar integração**, `IntegrationScreen` (`integration-modal`, contrato de dismiss em 9223e9e). A captura local antes da alteração confirmou corpo `#ffffff` claro / `#243730` escuro, sombra `--elev-3`, raio 10px, borda ausente no claro / 1px `#4a6458` no escuro. Cabeçalho e área final transparentes sobre o corpo, sem faixa de cor adicional. Backdrop = `--primary` a 40%, sem blur (inclusive no escuro, onde `--primary` é `#6fc2ab`).

Tokens da fundação em `globals.css`: `--modal-bg` = `--surface-overlay`; `--modal-fg` = `--foreground`; `--modal-border` = `0px solid --edge-strong` claro / `1px solid --edge-strong` escuro; `--modal-shadow` = `--elev-3`; `--modal-radius` = `--radius` (10px); `--modal-header-bg` e `--modal-footer-bg` = corpo; `--modal-backdrop` = `color-mix(in oklab, var(--primary) 40%, transparent)`; `--modal-backdrop-filter` = `none`. Estes tokens substituem o padrão genérico overlay + scrim nos diálogos. Popovers/menus/toasts mantêm seus próprios papéis de superfície.

Aplicação central em `surfaces.css`: dialogs nativos, conteúdo `role=dialog`/`role=alertdialog`, painel filho de `ModalOverlay` (marcado `data-modal-overlay`), overlays Radix Dialog/AlertDialog/Sheet e Vaul Drawer, cabeçalhos/rodapés semânticos e `data-slot`. O wrapper de overlay nunca recebe fundo de painel. Geometria, rolagem, foco, dismiss, motion e confirmação permanecem locais; automação conserva tela cheia no mobile.

Inventário de telas: gerenciar integração, criar/editar automação (quatro etapas), sincronizações da Biblioteca, exibição de chave da API, criar tarefa ClickUp, tour da conversa, notificações, menu mobile e visualizador de arquivo em tela estreita (`role` condicional). Primitivas: Dialog, AlertDialog, CommandDialog (usa DialogContent), Sheet e Drawer. O tour mantém o wrapper de tela cheia transparente e o spotlight; somente `.tour-card` recebe a superfície compartilhada, e a sombra externa do spotlight usa `--modal-backdrop`. O drawer mobile mantém posição e tamanho definidos pelo layout.

Evidências locais: `/private/tmp/claude-501/modal-standard/` contém referências claro/escuro anteriores, capturas posteriores, estilos computados e contact sheet em PDF. Os fluxos de chave API e tarefa ClickUp podem usar respostas locais simuladas para inspeção sem gerar credenciais nem criar tarefas externas; a evidência identifica esses casos.

## 8. Botões: variantes e hierarquia [M56]

Tokens `--btn-*` em `frontend/app/globals.css` (claro e `.dark`), estilos em `frontend/app/buttons.css`, helper `btn(variant, size?, extra?)` em `frontend/app/ui/button-variants.ts` (reexportado por `app/ui`). Uso: `className={btn("primary")}` → `btn btn-primary`. Telas de CSS próprio (login, onboarding) consomem os mesmos tokens.

| Variante | Visual | Quando usar |
|---|---|---|
| `primary` | verde da marca preenchido + `elev-1` | **uma** ação principal por contexto (tela, card, modal): Criar, Salvar, Executar agora, Enviar |
| `secondary` | verde suave (tonal) | ação importante que não é a principal: Editar, Voltar (etapa), Atualizar, modelos |
| `ghost` | sem fundo, texto verde; hover tonal | terciária: Cancelar, Ver histórico, Fechar, ações de barra |
| `destructive` | vermelho preenchido | **confirmação** de ação irreversível, dentro do modal (Excluir, Confirmar revogação) |
| `danger-soft` | vermelho tonal | ação de risco com destaque médio |
| `danger-ghost` | texto vermelho; hover tonal | gatilho de ação destrutiva fora de confirmação: Excluir, Revogar, Desconectar, Remover |
| `success` / `info` | verde / azul tonais | confirmações e avisos acionáveis (sem uso obrigatório hoje) |

Tamanhos: `md` (44 px, padrão), `sm` (40 px), `icon` (quadrado 44 px; sempre com `aria-label`). `btn-block` ocupa a largura.

**Estados**: hover e press trocam o fundo (`--btn-*-hover` / `-active`; press também desloca 2 px e escala 0,975 pelos tokens de motion); foco = anel `--focus-ring` de 2 px (claro) / cor da marca (escuro) com offset 2 px; `disabled` = fundo `--btn-disabled-bg`, texto `--btn-disabled-fg`, sem sombra; **loading** = `aria-busy="true"` + `disabled`: conserva a cor da variante, ganha spinner CSS (`--motion-loop-spin`) e ignora cliques (o botão do composer do chat usa `aria-busy` sem spinner).

**Contraste**: todo par texto/fundo de `primary`, `secondary`, `destructive`, `danger-soft`, `success` e `info` (repouso, hover e press) tem ≥ 4,5:1 nos dois temas; texto de `ghost`/`danger-ghost` ≥ 4,5:1 sobre canvas, painel, raised, sunken e overlay; fundo de `primary`/`destructive` ≥ 3:1 contra o painel (WCAG 1.4.11). Verificado por `frontend/tests/button-variants.test.mjs`.

**Mapa nas telas**: Automações — Criar automação = primary; no card, Executar agora = primary, Editar = secondary, Ver histórico = ghost, Excluir = danger-ghost (à direita); modal de exclusão: Cancelar = ghost, Excluir = destructive; editor: Cancelar = ghost, Voltar = secondary, Próximo/Salvar = primary. Integrações — Gerenciar/Conectar = primary, Desconectar = danger-ghost, Atualizar = secondary. Biblioteca — Conectar uma fonte = primary, Sincronizar/Atualizar = secondary, Remover = danger-ghost. Equipe/Chaves/ClickUp/convite — ação do formulário = primary, Revogar/Remover = danger-ghost, Cancelar/Fechar = ghost ou secondary. Login e onboarding mantêm classes próprias (`.login-*`, `.onboarding-*`), alimentadas pelos mesmos tokens.

### Excluir automação
`DELETE /organizations/{org}/automations/{id}` (204; apaga também as execuções). Botão visível só para criador, Owner e Admin (`canEditAutomation`, mesma regra do backend). Abre `AutomationDeleteDialog` (`alertdialog` sobre `<dialog>` nativo: nome da automação, aviso de que histórico e PDFs deixam de ficar acessíveis, ESC/backdrop bloqueados durante a chamada). Sucesso: toast, card sai com `automation-card-leaving` (`--motion-base`, opacity+transform) e é removido da lista após o tempo do token; erro: toast persistente + alerta no modal, que continua aberto.
