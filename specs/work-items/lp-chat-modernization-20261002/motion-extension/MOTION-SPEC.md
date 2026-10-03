# Contrato de motion — Arquivio A + modais existentes

Data: 2026-10-03 · fase inventário/contrato · **não implementado**. Fonte de autoridade: H4 aprovado pelo dono. DNA h-ed/direção A e layout/copy atuais mantidos. Evidência localizada em INVENTORY.md; runtime disponível nesta fase apenas LP pública.

## 1. Intenção e invariantes

Modernidade por feedback curto e continuidade entre estados existentes. Chat/fontes têm prioridade de leitura; modais parecem entrar no mesmo sistema, sem transformar o produto inteiro. Sem bounce, glow, blur animado, parallax, auto-play, digitação simulada ou transições de dados/citações por token.

**provided**: troca de caso 180–220 ms, FAQ/menu suave, hover/press, seções ≤280 ms, redução respeitada, modais existentes incluídos. **inferred**: valores/arquitetura abaixo, escolhidos para preservar dados, acesso, comportamento e custos. **observed**: LP implementada 140/180/240 ms; Shared Sheet 500/300 ms source, não comprovados em runtime auth.

- Conteúdo/API/aria-live/foco/pending mudam no instante da ação/resultado. Não aguardar animationend, timer, networkidle ou outro modal sair para disparar a ação.
- Preservar todas strings comerciais/FAQs/avisos fictícios, destinos/âncoras/handlers e estados reais da matriz INVENTORY §§3–5. Nenhum novo CTA/copy/modal.
- `busy`, disabled, cancelar, duplicidade de submit e persistência mantêm suas regras atuais. Não sincronizar API com frame/timer. Não animar chegada de erro, mensagem de sucesso, progresso, catálogo, arquivos/citações ou atualização de polling.
- Paleta/tipos/layout app ficam atuais. Não promover tokens LP ao :root, não modificar globals/brand/provider-logo. F-054 continua valendo para foco de campos. O contrato de motion não autoriza correção de trap/dismiss nem tratamento de dados tardios.

## 2. Tokens propostos e proveniência

Todos abaixo são **inferred — proposta autoral H4**. Não são valores extraídos de marca alheia. Nomes `--aq-motion-*` constituem apenas camada motion A2/fallback; valores declarados em roots de componente **opt-in**, incluindo ambos os nós do portal. Aliases B-slot LP podem consumir esses valores dentro `.landing-page`, sem alterar cores/tipos do DESIGN.md. Nenhum token desconhecido inventado como observado.

| Token / valor | Papel / fonte da decisão |
| --- | --- |
| `--aq-motion-enter: 200ms` | card/overlay existente; centro do intervalo H4 |
| `--aq-motion-exit: 180ms` | apenas saídas já suportadas pelo Presence Radix; menor tempo para liberar superfície |
| `--aq-motion-case: 200ms` | caso da LP substitui180 atual; intervalo H4 |
| `--aq-motion-disclosure: 200ms` | FAQ/menu público sem atrasar open; H4 |
| `--aq-motion-hover: 140ms` | feedback de cor/ícone já do DNA; não confundir com ciclo modal |
| `--aq-motion-reveal: 240ms` | valor atual da LP, dentro limite280 |
| `--aq-motion-ease-enter: cubic-bezier(.2,.8,.2,1)` | ease-out já coerente com LP, sem overshoot |
| `--aq-motion-ease-exit: cubic-bezier(.4,0,1,1)` | aceleração curta de saída Presence, proposta nova |
| `--aq-motion-ease-disclosure: cubic-bezier(.4,0,.2,1)` | simétrico já usado pelo chevron FAQ |
| `--aq-motion-offset: 6px` | curta translação de superfície, não layout; LP caso4px, mobile sheet12px via extensão local |
| `--aq-motion-scale: .99` | sutil; opcional no card overlay M2; nunca texto por token/hero/composer |
| `--aq-motion-opacity-start: .92` | painéis com texto começam legíveis; não fade de 0 da resposta/fontes; contraste medir com composição real |
| `--aq-motion-delay: 0ms` | modais/casos/disclosure/feedback sempre zero atraso |
| `--aq-motion-stagger: 20ms`, máximo40ms | apenas módulos decorativos inferiores LP; total último item≤280ms, substitui atrasos atuais até120 |

Redução: durations/delays efetivamente0, opacity1/transformnone em cada opt-in. Não registrar fallback 200ms em media reduce. Não generalizar `*` fora `.landing-page`. Foco/outline nunca interpolados. Press usa feedback de cor instantâneo/≤140ms; ícone pode mover1px, **texto e hitbox fixos**; nenhum scale global de buttons (prejudica foco/posição).

## 3. Contrato por superfície

| Superfície | Entrada / troca normal | Saída / interrupção | Sem regressão |
| --- | --- | --- | --- |
| LP caso (3 estados) | Conteúdo/aria-pressed commit imediato; visual thread .92→1 e translateY4px→0,200ms enter; painel/composer/labels estáticos | Novo clique cancela efeito anterior e aplica só estado final. Não manter resposta antiga em DOM para crossfade | Um único thread/fontes do caso ativo; nenhum tokentyping, fake loading, blur ou scroll automático; aria-live polite preservado e foco fica no botão |
| LP FAQ (7 details) | open nativo imediato; resposta já disponível; animação **decorativa** de wrapper do corpo opacity .92→1/translateY4px→0,200ms; chevron180–200ms | close nativo imediato, chevron reverte suavemente200ms. Corpo sai imediatamente porque details o oculta; não impedir toggle para “fechar animando” | Sem JS/no suporte: abrir/fechar nativos completos. Não usar max-height arbitrário, recortar copy longa ou remover open até fim de timer |
| LP menu details | summary/open imediatos; nav comopacity.92→1/translateY−4px→0,200ms | Fechamento nativo imediato. Não adicionar Escape/outside/auto-dismiss/role dialog ausentes | Mesmos destinos e teclado nativo; nada fica focusable invisível após closed; não atrasar CTA/nav |
| LP seções inferiores | Atual IO once threshold.15,opacity+translateY8px,240ms; children≤40ms atraso | Não reanimar no scroll para cima; ao unmount/mediachange limpar efeitos | Total cada sequência≤280ms. Hero, casos, avisos, CTAs superiores/fontes nunca escondidos. Sem JS visíveis; foco em descendente torna seção visível imediatamente sem smooth scroll |
| M1 Sincronizações nativo | showModal/foco UA imediatos; **section interno** entra .92→1/Y6px→0,200ms; backdrop pode entrar sóopacity200ms | close/cancel/onClose e statefalse imediatos, **sem retenção para exit**; nova abertura reinicia efeito do novo ciclo | Root dialog/top layer/overflow não transformados; não reanimar poll histórico/lista/progress3s; manter X liberado e Escape/backdrop blocked conforme busy |
| M2 Integração ativa overlay | Mount+foco C2 imediatos; section visual Y6px/.99→1 eopacity.92→1,200ms; overlay cor alpha0→alpha atual,200ms **se separado do painel** | closeTool/unmount imediato, exit0ms; não guardar catálogo/source em snapshot para fade-out | Nunca opacity no overlay pai que multiplica texto; root não transformado; status/erro/resultados imediatos, sem sair/reentrar loading→catalog; X/Escape/outside originais |
| M3 Tour | showModal e rAFfocus originais; card visualopacity.92/Y6px,200ms | finish espera somente onComplete atual. Desmonta imediatamente após sucesso; erro aparece instantâneo sem replay. Exit0ms | Não transformar dialog fullscreen ou highlight; top/left/rect continuam imediatos; por index, animar só interior de card200ms sem remount do dialog/primary. Não interpolar spotlight/scroll/alvo |
| M4 API secret | showModal imediato; conteúdo visualopacity.92/Y6px,180–200ms; nenhum fade da string isolada | closeSecret limpa secret **imediatamente**, exit0ms; não copiar DOM/guardar secret em closure de animação para exit | Copiar/Copiada e erro seção existentes; sem mover erro/foco/copy, sem logs/screenshots reais; não aguardar load/copy/animation para fechar |
| M5 Sheet móvel | Só instância mobile-nav opt-in: contentopacity.92→1,translateX−12px→0,200ms; overlay fadealpha0→atual,200ms; substitui slide100% e durações500/300 desta instância | data-state=closed usaopacity1→.92/X0→−12px,180ms (mecanismo Presence existente). open/navigation/selection/quit continuam imediatos, sem nova espera | Mesma primitive/portal/dismiss/trap; reduced removecontent+overlay. Tour handoff requer teste de concorrência foco; não encadear ações após exit |
| Confirms nativos / primitives não usadas | Nenhuma animação sob controle da LP/app | Preservar nativo/mecanismo atual | Não substituir pelos genéricos AlertDialog/Drawer para obter motion |

**Fechamento compatível:** motion 180–220 ms não implica atrasar todo close. M1/M2/M3/M4 atualmente fecham/desmontam imediatamente; contrato intencionalmente mantém isso. Manter dialog aberto/inert por200ms para saída mudaria acesso/foco; reter secret/catálogo inventaria nova política. Só M5 tem saída Presence já existente, encurtada. Se o dono exigir saída simétrica animada em todas as superfícies, o executor deve pedir ao piloto decisão de lifecycle/foco/retensão; não improvisar. Esta limitação não bloqueia entrada, estados, feedback ou inventário aprovado.

“Fade” de conteúdo legível começa .92; backdrop de0 não esconde texto e precisa nó separado. Se contraste/foco na composição cair abaixo do requisito, preservar opacity1 nos painéis de leitura e usar só translação curta; é fallback autorizado por preservação/a11y, não nova direção. Texto/foco jamais totalmente transparentes.

## 4. Camada reutilizável mínima, escopada

Proposta de dois pequenos arquivos, **apenas plano**:

1. `frontend/app/interface-motion.css`: tokens e keyframes `aq-*` somente `[data-arquivio-motion]`; papéis explícitos `panel`, `backdrop`, `sheet-panel`, `sheet-backdrop`, `tour-card`; estados/modo parametrizados. Import por consumers de app, sem :root/global `[role=dialog]`/`dialog`/`[data-slot]` universal.
2. `frontend/app/interface-motion.ts`: helper visual opt-in `playSurfaceEntry(ref, cycleKey)` via Web Animations quando necessário para dialog reaberto/etapa; cancel() anterior, media reduce/change, cleanup, estilos base finais. Não possui open-state, timers de close, API, router, focus(), inert, portal, scroll lock ou busy. Só use JS onde CSS não reinicia de forma confiável; CSS `[open]` em dialog é alternativa menor a provar na fixture.

M1: aplicar atributo/helper na section de `library-screen.tsx:261` acionado por spacesPanelOpen, **não** por folders/history. M2: section em `integrations-screen.tsx:67`, sem alterar C2/modal-dismiss. M3: card interior de `conversation-tour.tsx:78` com cycleKey=index, isolado da posição measured; não keyar modal/button. M4: content opt-in de `access-settings.tsx:83`, key do ciclo modal, sem capturar string secret no helper. Wrappers opcionais não mudam markup comercial nem o fluxo form.

M5 requer seam mínimo em `components/ui/sheet.tsx:47–63`: prop opt-in `motionProfile?: "arquivio"` consumida localmente (não passada à primitive como atributo desconhecido); carimbar **Overlay e Content** com profile/role. Consumer mobile-nav passa prop; default continua o mesmo para Sidebar/UI genérica. Classes não cumulam `animate-in/slide-in/...` e novos keyframes no ramo opt-in. Não inserir uma segunda Presence/portal/focus trap. Props/events aria, ref e onCloseAutoFocus preservados.

LP: selectors exclusivamente `.landing-page .landing-*`, keyframes `lp-*`. Não importar CSS de app para obter paleta/radius/tipo; pode usar mesmo valor/easing declarado localmente. Alterar somente timing/efeito de classes atuais e pequenos wrappers visuais se necessários; manter `frontend/tests/landing-contract.test.mjs` conforme escopo. Contrato derivado do DNA dá coerência sem migrar o app global.

Evitar manipulação global de animation do elemento: helper só cancela Animation que ele criou, nunca spinner/progress/Radix alheio. Não usar transition:all, will-change permanente, duration utilities conflitantes ou medir DOM em loop. Redução e focusin/has(:focus-within) da LP revelam conteúdo já marcado pending imediatamente.

## 5. Acessibilidade, concorrência e resultado imediato

- Focus trap/restauração/dismiss são dos mecanismos já usados. Transform no filho visual, não no root fixo/modal. Foco entra antes/independentemente da animação; indicador não anima cor/blur/opacity própria.
- M5→M3: fechar Sheet e abrir tour pelas ações existentes; observar onCloseAutoFocus e rAFprimary. Se Sheet roubar foco do tour no runtime, interromper e escalar ajuste **de foco** ao piloto; não corrigir com timeout200/180. Não mudar regra de replay/finished nem escolher target novo.
- Abrir→fechar→abrir em<180ms: cancelar effect antigo; fechar desmonta como hoje; callback de ciclo antigo não fecha/foca nova instância. API callbacks atuais não ganham novas dependências de animação. Trocar fonte/organização/rota: cleanup effects; nenhuma instância do motion reutiliza conteúdo/foco do tenant anterior.
- Clique rápido nos casos: React commit do último caso wins, nenhuma fonte antiga persiste. Preferir live region externa **estável** (mesmo aria-live polite existente) com filho visual keyado para replay, em vez de duas regiões; conteúdo substituído uma vez, não anunciado em cadaframe. Mover aria-live da div keyada para container estável é ajuste de semântica equivalente a validar, não nova mensagem/copy. Se anuncia mais que hoje ou perde anúncio, manter estrutura original e animar CSS sem remount adicional.
- Erros role alert, statuses/live e secrets não são escondidos/retardados; height:auto de dados imediata, sem FLIP da lista/contador/citações. Não aplicar aria-hidden na resposta ativa por causa da animação.
- `prefers-reduced-motion` ao carregar **e ao mudar durante efeito**: cancelar motion opt-in, restaurar estado final, opacity1/transformnone, zero delay; backdrop no alpha final; no layout/focus/API change. Lib mantém lifecycle sem tempo artificial .01ms caso suporte 0; testar Presence com animation:none/0 e cancel, não depender de animationend para regra de negócio.

## 6. Gate para execução/QA

Proposta pronta para implementação restrita; **nenhuma mudança aplicada nesta fase**. Aprovar por componente somente quando:

- Matriz M1–M5 e nove confirms preservada; nenhum modal/copy/CTA/rota novo; nenhum arquivo compartilhado mudado fora seam opt-in.
- Entrada medida 180–220ms, saídas conforme §3, delay0; reveal total≤280ms; sem typing/token motion e sem replay a cada fetch/poll.
- Teclado, outside press/drag, busy/X diferentes, focus restoration e trocaSheet→Tour passam em fixtures sintéticas fresh. Sem afirmar auth pass baseado só na LP.
- Contexto com redução inicial + mudança durante efeito; JS disabled para disclosures públicos; foco/acessibilidade sem dependência do timer; ausência de requests reais verificada.
- Contraste/hitbox/overflow intactos em375/390/768/1024/1440; resize mobile↔desktop, safe-area e teclado (simulado) não deixam foco preso no Sheet escondido. Desvio prévio é identificado separadamente, não corrigido por motion sem autorização.
- Evidência de frames/keyframes computados e DOM registra **qual superfície/ciclo e source vs fixture**, não vídeo ou screenshot de dados privados. Skills inline [oc-design-dna, oc-browser].
