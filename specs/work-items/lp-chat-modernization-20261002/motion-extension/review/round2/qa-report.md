# QA independente final — H4 motion LP + M1–M5

**Data:** 2026-10-03 · **Branch/base:** `design/lp-chat-modernization-20261002` / `a43dbdd` · **Preview:** http://127.0.0.1:5181/ · **Parecer técnico:** PASS. A aprovação humana final de H4 continua pendente.

## Resultado e severidade

- **Extensão motion:** P0 0 · P1 0 · P2 0. Nenhuma regressão de design, interação, conteúdo ou dados reproduzida.
- **Baseline separado:** três achados P2 registrados como F-208 (posição M4), F-209 (`failed:null` em M1) e F-210 (limite de isolamento do ModalOverlay). Não foram introduzidos pelo motion.
- **Workstream LP completo:** conta também o residual P2 aceito F-206; total atual P0 0 · P1 0 · P2 4. F-207 foi confirmado com estado `verificado`. F-206 segue `reaberto` no mesmo ID, com o tradeoff já aceito pelo piloto; não propus outra rodada para a dobra.

## Proveniência e escopo

A revisão usou os contratos completos `motion-extension/INVENTORY.md`, `MOTION-SPEC.md`, `implementation-plan.md`, `evidence/build/README.md`, `evidence/build/motion-qa-report.json` e `evidence/build/harness-snapshot.cjs.txt`, além de `COPY.md`, `MICROCOPY-QA.md`, `CLAIMS-AUDIT.md`, `direction/DESIGN.md`, `evidence/round2/geometry.json`, `evidence/round2/after/qa-report.json` e `design-to-app.md`.

O patch acompanhado contém os oito seams rastreados e os arquivos novos `interface-motion.ts`, `interface-motion.css`, `interface-motion.test.mjs`, `landing-contract.test.mjs` e assets locais. O diff dos seams está em `evidence/tracked-seams.patch`; o inventário está em `evidence/source-diff-audit.json`. Comparando com `a43dbdd`, os nove `window.confirm` mantêm texto idêntico, os três elementos HTML `<dialog>` de produto continuam presentes, os callbacks/cópia/API/busy/permissões dos seams permanecem nos handlers existentes e a prop nova do Sheet é opt-in só em M5. Nenhum path protegido mudou: 11 hashes registrados e diffs de globals, brand, layout/rota, auth, API e backend conferidos em `evidence/protected-paths-audit.json`.

O container dedicado `arquivio-lp-preview-20261002` está atualizado com imagem `arquivio-lp-preview:motion-review-20261003`, bind `127.0.0.1:5181`, restart `unless-stopped` e `API_UPSTREAM_URL=http://host.docker.internal:8000`. O teste público ocorreu primeiro em contexto limpo **sem mock, route ou interceptação**: `/` respondeu 200 e o GET real same-origin `/api/session` respondeu 200 com `null`; sem cookie, alerta de sessão, erro de console ou chamadas além de GET. Não foi usada conta real. As páginas M1–M5 foram exercitadas depois, em fixtures sintéticas fail-closed; toda rota `/api/*` foi respondida localmente ou abortada e nenhum host externo foi permitido. Não houve API real autenticada, mensagem, conta ou segredo real.

## Lente 1 — design, motion e coerência com A

**PASS.** A LP permanece coerente com a direção A e o style-lock: casos/FAQ entram em 200 ms com deslocamento curto e estado imediato; menu entra em 200 ms; reveal é 240 ms + stagger de até 40 ms (máximo medido 280 ms); hover/press ≤140 ms. `getComputedStyle(...).animationTimingFunction` confirmou o easing CSS previsto para caso/menu (`cubic-bezier(0.2, 0.8, 0.2, 1)`) e FAQ (`cubic-bezier(0.4, 0, 0.2, 1)`). O `getComputedTiming().easing` do objeto CSSAnimation devolve `linear` no Chromium; não foi usado como fonte do easing, pois o estilo computado CSS mostrou as curvas do contrato.

M1–M4 entram com foco/estado imediato e painel de 200 ms, sem transformar o root; fecham imediatamente como no baseline. M5 usa o Presence já existente: entrada 200 ms, saída 180 ms, foco restituído e ação/navegação não espera o fim. Trocas rápidas da LP e dos passos do Tour deixam apenas o ciclo atual. O Sheet padrão e os primitives sem uso continuam no ramo original.

| Viewport | Resposta (y) | 1ª fonte (y) | Grid do stage | Overflow / I-01 × texto |
| --- | ---: | ---: | --- | --- |
| 375×812 | 811 | 905 | 1 coluna | nenhum / 0 interseções |
| 390×844 | 799 | 893 | 1 coluna | nenhum / 0 interseções |
| 768×1024 | 894 | 993 | 1 coluna | nenhum / 0 interseções |
| 1024×900 | 494 | 594 | 386.391 / 533.609 px, 42/58, gap 40 | nenhum / 0 interseções |
| 1440×900 | 475 | 575 | 517.438 / 714.562 px, 42/58, gap 48 | nenhum / 0 interseções |

**F-207 confirmado.** O grid 42/58 já vale em 1024 px; a primeira fonte aparece em y594 dentro da dobra de 900 px. **F-206 continua parcial:** em 390×844 a resposta começa em y799 (bloco termina em y849) e a primeira fonte em y893 — 83 px além da meta y810, embora tenha ganho 121 px desde a rodada anterior. Em 375×812, resposta y811 e fonte y905. Mantenho explícita a meta parcial e o tradeoff aceito: não reduzir tipografia nem esconder/reordenar conteúdo para caber.

## Lente 2 — acessibilidade, responsividade e ciclo de vida

**PASS técnico, com limite baseline documentado.** Nos cinco tamanhos, sem scroll horizontal; alvos visíveis ≥44 px; chat ≥16 px e avisos ≥13 px. As duas fontes locais e o asset I-01 carregam com HTTP 200; a arte não cruza texto. Reveal com foco mostra a seção antes de animar; sem JS o FAQ nativo abre e conteúdo não fica oculto. `prefers-reduced-motion` inicial e dinâmico remove animações e entrega o estado final na LP e nos M1–M5.

O harness confirmou foco em M1/M2/M3/M4/M5, retorno ao trigger, Tab/Shift+Tab, Escape, clique externo, arrasto para o backdrop, X e bloqueios de busy de acordo com o baseline; polling não reexecuta motion nem dispara ação duplicada. Tour mantém o mesmo card ao mudar de etapa, e a corrida Sheet→Tour preserva o foco no Tour. Resize M5 390→1024 remove Drawer, overlay e estilos Radix de scroll-lock; não sobra overlay, elemento `inert`/oculto nem conteúdo desktop inacessível: Tab alcançou um botão visível e o clique de ponteiro funcionou.

**F-210 é uma limitação preexistente:** M2 declara `aria-modal=true` e envolve Tab nos extremos, mas a captura fresh tem `appHiddenAncestors=[]` e `bodyPointerEvents=auto`; o componente não marca o app como inerte nem aplica bloqueio explícito de rolagem. A fala/virtual cursor de leitor de tela **não foi testada manualmente**. Não atribuo esse limite à extensão.

## Lente 3 — conteúdo, callbacks, API, busy e dados

**PASS.** `landing-contract.test.mjs` compara literais e nomes acessíveis do contrato COPY/MICROCOPY, mantém os três casos (“Resposta com fontes”, “Com menção @”, “Sem evidência suficiente”), os sete FAQs, quatro integrações, âncoras, rotas legais, sete ligações de callback (3 `onLogin`, 4 `onSignUp`) e uma única `ProductPreview`. O build/runtime público confirmou esses itens sem alerta ou chamada autenticada. Nenhuma cópia, CTA ou permissão foi removida para ajustar a dobra.

Na fixture sintética, M1 polling não repetiu entrada; M2 clique duplo gerou um POST; M3 pending manteve o diálogo aberto com um POST e a corrida não enviou pergunta; M4 clique duplo gerou um POST, clipboard foi stub local e a chave obviamente falsa saiu do DOM imediatamente ao fechar; M5 encerrou com o Presence já presente. Nenhum valor de segredo foi salvo no relatório. Os 9 `window.confirm` nativos e seus textos correspondem ao baseline.

**Achados baseline (fora do PASS de motion):** F-208 registra o `<dialog>` M4 em x=0,y=0, 512×255, margem 0; F-209 registra a string “Falhas por documento ()” com `failed:null`; F-210 registra o limite do `ModalOverlay`. Os três têm evidência independente no diretório `evidence/legacy/` e permanecem sem correção de produto nesta revisão.

| Finding | Correção objetiva sugerida (não aplicada) |
| --- | --- |
| F-208 | Restaurar centralização do `<dialog>` M4 com regra de layout escopada ou `margin:auto`, mantendo o painel de motion interno. |
| F-209 | Tratar `failed: null` como indisponível e evitar construir resumo com parênteses sem valor. |
| F-210 | Avaliar `inert`/`aria-hidden` no app de fundo e bloqueio de rolagem, com restauração no unmount; confirmar depois com leitor de tela manual. |

## Comandos e evidência fresh

Comandos em `frontend/`, salvo Docker e `git diff --check` na raiz:

| Checagem | Resultado |
| --- | --- |
| `npx tsc --noEmit -p .` | exit 0 |
| `npm run lint` | exit 0 |
| `VITE_API_BASE_URL=/api npm run build` | exit 0 |
| `node --import tsx --test tests/*.test.mjs` | exit 0 · 98 pass / 0 fail |
| `docker build -f Dockerfile.production --build-arg VITE_API_BASE_URL=/api -t arquivio-lp-preview:motion-review-20261003 .` | exit 0 |
| `curl /` · `curl /api/session` no preview | exit 0 · 200 · 200 `null` |
| Browser público limpo (sem mock), 19 checks | exit 0 · 19/19 |
| Harness de re-review LP + M1–M5 | exit 0 · 92/92; 26 LP + 14 M1 + 18 M2 + 11 M3 + 9 M4 + 13 M5 + 1 rede |
| Reprodução sintética M1/M4 baseline | exit 0 · sem falha do harness |
| Hash preservation + diff paths protegidos vs `a43dbdd` | exit 0 · 11/11 hashes; nenhum diff protegido |

O QA original do build lista 80 checks, não 61 de fixtures: os arrays brutos somam 26 públicos + 53 fixtures (`14+13+11+7+8`) + 1 rede = 80. O README original foi corrigido para refletir essa soma. O harness independente desta re-review acrescentou 12 checks adversariais aos grupos M2/M4/M5 e totalizou 92/92; não misture as duas contagens. Logs e dados estão em `review/round2/evidence/`.

Capturas de veredito, da página pública limpa e sem mocks (uma desktop e uma mobile): `evidence/verdict-desktop-1440x900.png` e `evidence/verdict-mobile-390x844.png`.

## Parecer

**PASS técnico da extensão H4**, sem P0/P1/P2 atribuível ao motion; os três P2 baseline estão separados e F-206 permanece explicitamente aceito como residual P2. **H4 ainda requer aprovação humana final.** Nenhum código de produto foi editado nesta revisão; não houve commit nem push.
