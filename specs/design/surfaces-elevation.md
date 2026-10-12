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
