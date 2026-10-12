# Referência de motion — rogueon.ai/pt-br (padrões, não identidade)

Captura ao vivo em 2026-10-12 (Playwright 1440×900, hooks de `IntersectionObserver`/`getContext`/`Element.animate`, `MutationObserver` em atributos `data-*`, leitura do bundle CSS, páginas `/pt-br` e `/pt-br/code`). Dados brutos em `motion.json`. Evidência visual (não versionada): `/private/tmp/claude-501/rogueon-capture/` (`screenshots/chat-*`, `intro-*`, `state-*`, `mobile-*`, `ds-code/screenshots/motion/*-t{000..100}.png`, `strip-*`).

Escopo: só **padrões de motion** para o ArquivIO. Nada de marca, texto, cor ou asset deles.

**Limites honestos:** o chat real do produto está atrás de login (não acessado, nenhum dado enviado); o "chat" observado é a demo animada da landing. Streaming token a token real não foi observável. O canvas do hero é JS e só foi medido por estado/tempo.

## 1. Filosofia geral

- **Poucas curvas, muitas durações curtas.** Só 2 easings nomeados cobrem quase tudo: `out = cubic-bezier(.2,.8,.2,1)` e `spring = cubic-bezier(.25,1.4,.5,1)`. O resto é `ease`.
- **Durações dominantes:** 120ms (15 usos) para cor/fundo/sombra; 160–200ms para opacidade e press; 300–380ms para transform com spring; 550ms só para o "pop" do balão; 900–1100ms só para entradas de seção.
- **Hover e foco compartilham regra** (`:hover, :focus-visible`), foco = outline 2px offset 2px.
- **Estado por atributo, animação por CSS.** O JS só troca `data-*` (`data-conversation`, `data-intro-state`, `data-typing`, `data-shown`); o CSS faz toda a transição. Facilita reduced-motion e teste.
- **Sempre há saída de emergência:** `animation: x 0s 1.5s forwards` força visibilidade se o JS da intro falhar; botão "pular" na intro.

## 2. Espera de mensagem no chat (indicadores de digitação/streaming)

**Máquina de estados** (medida): `idle → user (+150ms) → typing (+900ms) → reply (+2000ms) → idle`, loop. Disparada quando 45% do bloco entra (`IntersectionObserver threshold .45`).

```css
.chat[data-conversation] .bubble { opacity:0; scale:.55;
  transition: opacity .35s ease, scale .55s cubic-bezier(.3,1.5,.5,1); will-change: translate; }
.chat[data-conversation=user]   .bubble--user,
.chat[data-conversation=typing] .bubble,
.chat[data-conversation=reply]  .bubble { opacity:1; scale:1; }
.bubble--user      { transform-origin: 100% 100%; }  /* cresce a partir da cauda */
.bubble--assistant { transform-origin: 0 100%; }
```

- **Balão entra com "pop" (scale .55→1, overshoot de spring)**, opacidade mais rápida (.35s) que a escala (.55s). A origem do transform é o canto da cauda.
- **Flutuação ambiente depois de entrar:** `float 4.6s / 5.4s ease-in-out infinite`, atrasos .6s/1.4s, 2º balão `reverse`. Usa a propriedade `translate` (não `transform`) para não conflitar com `scale`.
- **Indicador de digitação (3 pontos):**
  ```css
  @keyframes typing-dot { 0%,60%,100%{opacity:.25;transform:none} 30%{opacity:.9;transform:translateY(-3px)} }
  .typing i { animation: typing-dot 1s infinite }       /* ciclo 1s */
  .typing i:nth-child(2){ animation-delay:.15s } .typing i:nth-child(3){ animation-delay:.3s }
  .typing { display:none; height:20px; gap:4px }       /* altura fixa = zero layout shift */
  ```
  Só existe no estado `typing`; sobe 3px com opacidade .25→.9. Stagger 150ms.
- **Caret de digitação (headline/texto):** barra 2px × .9em; **pisca** `1.06s step-end infinite` quando parado; **fica sólido** (`animation:none; opacity:1`) enquanto "digita". Digitação palavra a palavra em rajadas de ~230–450ms com pausas de ~1.8s.
- **Reduced motion:** caret some, texto final aparece direto (versão `sr-only` mantém o texto completo), balões ficam visíveis estáticos.

Aplicação ao ArquivIO: pontos de digitação ao esperar a primeira resposta do assistente; caret sólido durante streaming de tokens e pulsando só quando ocioso; mensagem do usuário entra com pop curto; nenhum shift de layout.

## 3. Estados de carregamento

| Padrão | Implementação medida | Quando usar |
|---|---|---|
| **Shimmer** | `linear-gradient(90deg, c@18%, c@38% 50%, c@18%)`, `background-size:200% 100%`, `animation: shimmer 3.2s ease-in-out infinite`; keyframe `0%{bg-pos-x:100%} 100%{bg-pos-x:-100%}`; barras 9px, raio 999px | skeleton de linhas/blocos |
| **Pulse** | `0%,100%{opacity:.6} 50%{opacity:1}`, 2.6s ease-in-out infinite, atrasos negativos ~70ms por ponto | indicador "vivo" discreto |
| **Twinkle** | opacidade .25→1 `alternate`, duração/atraso por variável CSS (`--t/--d`) | decoração; evitar em UI densa |
| **Typing dots** | seção 2 | espera de resposta |
| **Intro com skip** | ~3.0s (playing@223ms → done@3213ms); fundo em scale 2.05 + blur ~45px relaxa; conteúdo `translateY(14px)+opacity 0 → 0`; botão "pular" sempre visível | onboarding/primeira abertura (opcional) |

Shimmer é **lento (3.2s) e de baixo contraste** (18%→38% de tinta), não o clássico 1.2s. Sob reduced-motion: `animation:none` (barra estática).

## 4. Transições entre telas / estados

- **Sem page transition global observada** (navegação normal entre rotas). A "transição entre estados" é feita **in-place** com atributos: intro (`pending/playing/done`), chat (`idle/user/typing/reply`), tabs (`aria-selected`), accordion (`open`), mascote (`data-shown`), menu mobile.
- **Accordion (FAQ):** `details/summary`; ícone "+" vira "−" (barra gira 90°→0, `.3s var(--out)`, opacidade .5→1 no hover/aberto); em outro componente o painel anima `grid-template-rows` **`.28s cubic-bezier(.3,.8,.3,1)`** (técnica 0fr→1fr, sem medir altura).
- **Tabs:** `background/color .15s`; selecionada = fundo sólido + cor de acento; hover = fundo 3.5% branco. Sem slide de indicador.
- **Menu mobile:** painel `backdrop-filter: blur(16px)` sobre fundo escuro 82% opaco.
- **Banner/toast:** entra `.22s ease-out` (opacity 0→1 + `translateY(8px)→0`); **sem animação de saída**.
- **Mascote espiando:** wrapper com `clip-path`, imagem `translateY(102%)→0` em `.8s cubic-bezier(.34,1.56,.64,1)`, opacidade `.08s linear`.
- **Estado do hero (notch):** `opacity .16s ease, transform .46s cubic-bezier(.2,1.25,.4,1)` de `scale(.55,.42)` com `transform-origin:50% 0` (expande para baixo).

## 5. Scroll reveal e stagger

- **Reveal nativo por scroll (sem JS):** `@supports (animation-timeline:view())` + `@media (prefers-reduced-motion:no-preference)`:
  ```css
  .reveal { animation: reveal linear both; animation-timeline: view(); animation-range: entry 0 entry 45%; }
  @keyframes reveal { from{opacity:0; transform:translate3d(0,28px,0)} to{opacity:1; transform:none} }
  ```
  Variante "stand" (blocos grandes): `perspective(1600px) rotateX(16deg) translate3d(0,64px,0) scale(.95)`, opacidade completa em 60%, `animation-range: entry 0 cover 38%`. Variante só-fade para cards.
- **Entrada na carga:** `rise` 900ms `out` fill `both` (y18 + opacity); `arrive` 1100ms `out` fill `backwards` (y26 + scale .82 + opacity). Variantes `*Lead` sem opacity (para itens já visíveis).
- **IntersectionObservers observados:** `threshold .45` (gatilho de demo), `rootMargin 200px` (ativar/carregar mídia antes de entrar).
- **Stagger:** 150ms entre pontos de digitação; 30/60/90ms (e .12/.15/.18/.21s) em grupos de itens pequenos. Regra: ~30ms para itens leves, ~150ms para elementos de peso.
- **Ambiente:** `drift` (translate/rotate por variável, alternate ease-in-out), loop longo `30s cubic-bezier(.45,0,.55,1) alternate`, marquee `70s linear infinite` com `mask-image` nas bordas e **pausa em hover/focus-within/active**.

## 6. Hover, foco, press

- **Press:** botão `:active → translateY(2px) scale(.975)` (`.16s ease`); card com objeto `:active → translateY(5px) scale(.94)` `.12s`.
- **Hover botão primário:** fundo um passo mais claro + `box-shadow: 0 8px 30px -8px <acento>@.45` (glow só no hover), `.2s`.
- **Hover card-objeto:** `scale(1.045) rotate(-2deg) brightness(1.06)` com `spring .38s`; etiqueta aparece (`opacity .2s` + `translate3d(-50%,…)`).
- **Dock:** hover/foco → `translateY(-8*pt)` spring `.38s`, etiqueta glass (blur 12px) e ponto indicador (`opacity .2s`).
- **Link inline:** hover/foco vira "marca-texto" (fundo cheio + `box-shadow 0 0 0 2px`), `.12s ease`.
- **CTA com seta:** `translateX(2–3px)` no ícone.
- **Chip/exemplo:** `filter: brightness(.94)` `.12s`. Logo de nav: `opacity 1→.75`.
- **Foco visível:** `outline: 2px solid <acento>; outline-offset: 2px` (medido `2px/2px`), igual em todos os interativos.

## 7. Blur / glass / glow

- `backdrop-filter: blur(12px)` (banner, tags, dock, badge) e `blur(16px)` (menu mobile), sempre com fundo escuro 62–94% de opacidade e **hairline interna** `box-shadow: inset 0 0 0 1px rgb(255 255 255/.12–.14)`.
- `filter: blur(~45px)` apenas numa camada de fundo durante a intro; `invert(1)` + `mix-blend-mode:difference` para um controle que flutua sobre mídia variável.
- Glow: **apenas** no hover do CTA primário (sombra difusa deslocada, alpha .45). Sem glow estático.
- Sombra de superfície flutuante: `0 18px 50px rgb(0 0 0/.35)`.

## 8. Reduced motion (cobertura real)

- 29 regras (`/pt-br`) e 22 (`/code`): bloco global `*,::before,::after{animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important; scroll-behavior:auto}`.
- Reveals scroll-driven só existem em `no-preference` (padrão = visível, não oculto).
- Por componente: `animation:none`/`transition:none` em shimmer, balões, tabs, links; remove decoração (caret, drift, scroller); marquee vira lista com wrap; estado final garantido (balões visíveis).
- **Toggle manual "pausar movimento"** na página `/code` (além da media query).

## 9. O que aproveitar vs. não copiar

| Aproveitar | Não copiar |
|---|---|
| Máquina de estados via `data-*` + CSS | Textos, mascote, balões coloridos, fotos |
| Pop de balão com origem na cauda | Paleta, tipografia, marca |
| Pontos de digitação 1s / stagger 150ms / altura fixa | Intro cinematográfica de 3s (pesada p/ SaaS de docs) |
| Shimmer lento e suave | Canvas hero, marquee, drift decorativos |
| `animation-timeline: view()` com fallback | Efeito "stand" 3D (chamativo demais) |
| Foco 2px offset 2px, hover=focus | Glow neon |

## 10. Proposta de **motion tokens** para o ArquivIO (app SaaS de documentos)

Princípio: produtividade primeiro. Movimento comunica **estado** (carregou, chegou, mudou) e é curto; decoração fica de fora. Sem entradas > 400ms em UI funcional.

### Durações
```css
:root {
  --motion-instant: 80ms;   /* tooltip off, toggles, caret */
  --motion-fast:   120ms;   /* hover cor/fundo/borda, link */
  --motion-base:   180ms;   /* press, fade de painel, foco */
  --motion-medium: 280ms;   /* accordion, drawer, popover, tab, linha de resultado */
  --motion-slow:   420ms;   /* entrada de bolha/modal, pop com spring */
  --motion-enter:  600ms;   /* só primeira carga / onboarding (opcional) */
  --motion-loop-typing: 1000ms;   /* ciclo dos pontos de digitação */
  --motion-loop-shimmer: 2400ms;  /* skeleton (mais rápido que a ref. 3.2s: lista longa) */
  --motion-loop-pulse: 2000ms;
  --motion-caret-blink: 1060ms;
}
```

### Easings
```css
:root {
  --ease-out:    cubic-bezier(.2,.8,.2,1);      /* padrão para entradas/saídas */
  --ease-in-out: cubic-bezier(.45,0,.55,1);     /* loops e movimentos longos */
  --ease-standard: cubic-bezier(.3,.8,.3,1);    /* accordion/drawer (grid-template-rows) */
  --ease-spring: cubic-bezier(.25,1.4,.5,1);    /* hover lift, popover (overshoot leve) */
  --ease-pop:    cubic-bezier(.3,1.5,.5,1);     /* bolha de chat, chip, badge "novo" */
  --ease-linear: linear;                        /* marquee/progresso */
  --ease-blink:  step-end;                      /* caret */
}
```

### Distâncias e escalas
```css
:root {
  --motion-dist-xs: 2px;    /* press (translateY) */
  --motion-dist-sm: 8px;    /* toast, popover, tooltip */
  --motion-dist-md: 14px;   /* entrada de item de lista/card */
  --motion-dist-lg: 24px;   /* reveal de seção (máx.) */
  --motion-scale-press: .975;
  --motion-scale-hover: 1.02;     /* mais contido que a ref. (1.045) */
  --motion-scale-pop-from: .8;    /* bolha/modal (ref. .55 é exagerado para documentos) */
  --motion-stagger-sm: 30ms;      /* linhas de lista/resultados */
  --motion-stagger-md: 80ms;      /* grupos de cards */
  --motion-stagger-lg: 150ms;     /* pontos de digitação */
  --motion-stagger-max: 8;        /* itens animados; o resto entra junto */
  --motion-blur-glass: 12px;      /* popover/menu glass */
  --focus-ring: 2px solid var(--color-accent);
  --focus-offset: 2px;
}
```

### Receitas (token → uso)
| Situação | Receita |
|---|---|
| Hover/foco de botão, link, linha | `fast` `ease-out` em `background/color/border/box-shadow` |
| Press | `base` `ease-out`, `translateY(var(--motion-dist-xs)) scale(var(--motion-scale-press))` |
| Mensagem do usuário entra | `slow` `ease-pop`, `scale(.8→1)` + `opacity`, origem no canto da cauda |
| Esperando resposta | pontos `loop-typing`, stagger `lg`, `translateY(-3px)`, altura fixa; some ao primeiro token |
| Streaming | caret sólido (sem blink) durante tokens; blink `caret-blink` só ocioso |
| Skeleton (lista de documentos/resultados) | shimmer `loop-shimmer` `ease-in-out`, 18%→38% de tinta |
| Entrada de lista (documentos, citações) | `medium` `ease-out`, `dist-md` + opacity, stagger `sm`, máx. 8 itens |
| Accordion / painel de fontes | `grid-template-rows 0fr→1fr` `medium` `ease-standard` |
| Drawer / painel lateral de documento | `medium` `ease-standard`, translate de 100% (sem bounce) |
| Popover/menu (glass) | `base` `ease-spring`, `dist-sm` + opacity; `backdrop-filter: blur(var(--motion-blur-glass))`; saída `fast` |
| Toast | entra `base` `ease-out` (`dist-sm`), sai `fast` **com** animação de saída (melhoria sobre a ref.) |
| Upload/indexação em progresso | barra com `ease-linear`; estado "concluído" com pop `slow` no ícone |
| Reveal de seção (landing/onboarding) | `animation-timeline: view()` `entry 0 entry 45%`, `dist-lg`, atrás de `@supports` |
| Tabs | `base` na cor/fundo; sem slide de indicador no MVP |

### Reduced motion (regra obrigatória)
```css
@media (prefers-reduced-motion: reduce) {
  :root { --motion-fast:.01ms; --motion-base:.01ms; --motion-medium:.01ms; --motion-slow:.01ms; --motion-enter:.01ms; }
  *, *::before, *::after { animation-iteration-count:1 !important; scroll-behavior:auto !important; }
  .skeleton, .typing-dot { animation: none; opacity:.6 }   /* estático, ainda legível */
  .caret { animation: none; opacity:1 }
}
```
Reveals de scroll **só** em `no-preference`; estado final sempre visível por padrão. Estados que dependem de movimento (digitando, carregando) precisam de equivalente estático (texto "Pensando…", `aria-busy`, `role="status"`). Considerar toggle "reduzir movimento" nas preferências do app, além da media query.

### Checklist de adoção
1. Declarar tokens em um único arquivo CSS; proibir `ms`/`cubic-bezier` literais fora dele (lint).
2. Estado por `data-*`/`aria-*`, animação só em CSS (testável por atributo).
3. Altura/largura fixas em indicadores de espera (sem layout shift).
4. Toda entrada tem saída (a ref. não tem) e tudo tem versão reduce.
5. Animar só `opacity`, `transform`, `scale/translate` e `grid-template-rows`; `will-change` apenas durante a animação.
