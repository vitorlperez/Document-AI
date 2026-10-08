# Arquivio — DNA de direção A: Contexto vivo

Contrato autoral para a LP, 2026-10-02 (America/Manaus). **Proposta, H2 pendente.** `provided` = brief/baseline; `observed` = navegador real; `inferred` = decisão nova, nunca valor atribuído a uma referência. A alternativa B está no STYLEBOARD.pdf e em research.md. Tokens canônicos implementam A somente; não mesclar as duas direções.

## 1. Visual Theme & Atmosphere

Feels like uma ferramenta clara e pronta para trabalho: conhecimento organizado, resposta legível e caminho de volta às fontes. A superfície clara recebe verde-petróleo da marca e um pequeno sinal lima, sem aparência editorial de escritório antigo. O produto ocupa o espaço de maior contraste; a confiança vem da resposta limitada pela evidência, não de adjetivos ou selos novos. **inferred**, proposta A, apoiada pela composição dividida observada no Glean e pelo peso sans observado no Dust (`screenshots/references/{glean,dust}-hero.png`).

**Key Characteristics**

- Chat e documentos utilizados na primeira dobra desktop; uma resposta e primeira fonte na dobra móvel 390×844. **inferred**, metas de composição, não resultado implementado.
- Verde #1C6052 e wordmark `arquivio.` preservados. **provided**, baseline §3.
- H1 sans compacto; corpo/UI confortável; hierarquia por contraste e espaço, não gradientes. **inferred**, tokens.css.
- Prévia é um componente real, com os três casos existentes e avisos fictícios. **provided**, baseline §§4–6.

## 2. Color

| Papel | Proposta hex | Token | Confiança/origem |
|---|---|---|---|
| Fundo limpo | #F5F7F4 | --bg | inferred, A |
| Tinta principal | #142B25 | --fg | inferred, A |
| Marca / CTA | #1C6052 | --accent | provided, baseline §3, atual verde-petróleo |
| Hover CTA | #124B3F | --accent-hover | provided, baseline §3 |
| Wordmark | #243B35 | --brand-ink | provided, baseline §3 |
| Painel de produto | #FFFFFF | --surface | inferred, A |
| Painel de fontes | #EAF2EC | --source-surface → --surface-muted | inferred, A |
| Texto secundário | #51635A | --fg-muted | inferred, A; texto normal ≥4.5:1 |
| Divisor decorativo | #D5DFD7 | --border | inferred, A; não identifica controle sozinho |
| Borda de controle | #718379 | --border-strong | inferred, A; limite identificável ≥3:1 |
| Foco | #965B0D | --focus-ring | inferred, A; reforça o âmbar atual |
| Sinal gráfico | #D9F279 | --signal-lime | inferred, A; nunca texto claro ou CTA principal |

As variáveis acima são **propostas locais**, não CSS vars observadas nas referências. Valores computados brutos, seletores, cores e fontes das referências estão em `source/references/*-desktop.json`. Ex.: Glean H1 rgb(29,29,29) = #1D1D1D; CTA header rgb(0,0,0) = #000000. Claude CTA background rgb(20,20,19) = #141413 e texto rgb(250,249,245) = #FAF9F5. Notebook CTA #1F1F1F / #FFFFFF. Não transportar essas marcas/paletas para Arquivio.

### Gradient System

**inferred**: sem gradiente de hero. Fundo plano; painel branco; lima limitado a pequeno marcador ornamental, nunca fontes. Efeitos observados são registrados em `source/motion.json` (Dust), mas o kit motion derivado é diagnóstico da referência, **proibido colá-lo na LP**. B usa palco plano #102F27 com texto #F5F7F4, marca original em pequena placa branca e produto branco, sem purple→blue/blue→cyan.

## 3. Typography

**inferred**: A combina **Manrope 650** nos títulos e **IBM Plex Sans 400/500/600** na UI e corpo. Arquivos abertos com OFL em fonts/; seleção autoral, não as fontes proprietárias das referências. Manrope deixa o título contemporâneo sem afastar o nome; Plex diferencia caracteres e sustenta listas densas. Marca continua Arial bold e Layers3 do componente atual (**provided**, baseline §3); não substituir pela fonte do H1.

H1 34–56 px (`--text-4xl`, 1.08, tracking -0.035em); H2 32–44 px; corpo 16–18 px / 1.55; chat 16 px / 1.55; fonte/documento 14 px; avisos 13 px. Títulos podem quebrar em mais linhas mantendo o texto literal e a ordem. `em` comercial permanece no DOM; na A vira sans sem itálico, verde. Nunca usar texto de chat em imagem. B: **Space Grotesk 600 + IBM Plex Sans 400/500**, hero 40–64 px centralizado; UI mantém mesmo corpo da A.

Evidência **observed**: Dust H1 Geist 69.12 px/62.208 px, -2.7648 px; mobile 40 px. Glean H1 Polysans Neutral 56 px/53.76 px; mobile capturado em `glean-mobile.json`. Claude H1 anthropicSerif 72 px/79.2 px, CTA anthropicSans; mobile 36 px (ver JSON). Isso informa ritmo, não licença para reproduzir famílias. Valores propostos têm confidence individual no report.

## 4. Spacing & Grid

**inferred**: grade de 4 px; escala 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96. Container max 1280 px; desktop 64 px de margem em 1440 (container efetivo 1312, limitado a 1280); mobile 16 px; tablet 24–32 px. Seções 80–112 px desktop, 48–64 mobile. Header 72 px desktop / 56 mobile; alvos mínimos 44×44 px. CTAs 48 px. Fontes com linha mínima 40 px, área de ação se existir 44 px.

Desktop ≥1024: hero/produto em grade `minmax(0,0.42fr) minmax(0,0.58fr)`, gap 40 px; Biblioteca pode ser rail 128 px, chat restante, fontes sob resposta. `Buscar arquivos` fica em faixa própria abaixo do transcript, sempre com sua copy. Entre 768–1023: uma coluna, chat pleno. ≤767: fontes em lista abaixo da resposta; sem transformar UI em screenshot; Biblioteca e Busca continuam na mesma figura, abaixo do núcleo do chat. Menu existente ≤820 preservado. Validar 375/768/1024/1440 após H2.

## 5. Layout & Composition

**inferred**, A: uma única área superior combina hero e a seção `#produto`, em ordem DOM hero → produto. Texto esquerdo usa ~42% e preview direito ~58%. Header e copy comercial têm precedência, mas nenhum espaçador monumental antecede a UI. O título de Produto continua literal no topo da figura, com escala reduzida a 22–26 px. Há somente **uma** ProductPreview, nunca duas versões divergentes. Os três botões de casos permanecem antes da conversa. Avisos ficam junto da empresa e na legenda, em texto legível.

Meta de dobra A desktop 1440×900: header até y72; hero inicia y136; pergunta e resposta entre y310–520; pelo menos a lista de fontes começa até y620. Mobile 390×844: header y0–56, hero copy/CTAs y80–390; título de Produto e casos y420–545; pergunta/resposta/primeira fonte até y810. Esses números são **inferred**, metas condicionadas à quebra de texto, não promessa de caber tudo em 375×667. Em telas curtas, permitir scroll normal; nunca ocultar a copy ou reduzir chat abaixo de 16 px para caber.

Sequência inferior intacta: Integrações → Rotina → Como funciona → FAQ → Fechamento → Footer. Diferenciar Rotina com três linhas editoriais ligadas por um fio fino; Como funciona com três módulos de processo e nota de compartilhamento inteira. Não eliminar a seção aparentemente redundante. FAQ duas colunas no desktop, uma no mobile. Toda copy permanece completa, mesmo que não caiba nas miniaturas do styleboard.

B, **inferred**: palco verde escuro centralizado, título curto em largura max 880 px e preview branco largo logo abaixo; fontes como trilha horizontal desktop. Mais impacto de campanha; exige mais altura e adaptação de marca em alto contraste dentro do escopo LP. A tem melhor legibilidade móvel e migração ao app.

## 6. Components

Inventário Arquivio **provided**: baseline §§5–6 e `source/landing-source.snapshot.txt`. Inventário estrutural real do Dust **observed**: `source/components.discovered.json`; não confundir com catálogo da marca Arquivio. `components.html` é um **fixture técnico do contrato**, não site implementado nem nova copy comercial.

| Componente da LP | Variantes/estados preservados | Tratamento A inferred |
|---|---|---|
| Marca / skip link / nav | normal, hover, focus-visible; menu closed/open | marca existente; underline + outline; menu nativo |
| CTA | sign-up, login; hover, active, focus-visible | verde sólido e link textual; mesmos handlers |
| Seleção de casos | 3 botões; aria-pressed false/true | pills com contorno forte, wrap sem truncar |
| Conversa | resposta com fontes; menção @; sem evidência | texto vivo, fontes abaixo, aria-live polite |
| Biblioteca / Busca | ilustrativos; não inputs reais | rails/faixas preservados, aria-hidden conforme original |
| Fonte | número, documento, provedor; não link novo | lista organizada; nenhuma ação falsa |
| Integração | Google Drive/OneDrive/Notion/SharePoint | logos existentes, mesma lista |
| FAQ | 7 details closed/open; focus-visible | rows com divisor; área summary ampla |
| Avisos | prévia, fictício, leitura, conteúdo indexado, compartilhamento | nunca tooltip nem letra apagada |
| Footer | duas marcas/âncoras legais | destinos inalterados |

Fixture também documenta Loading/Empty/Error/Populated/Edge e Untouched/Dirty-valid/Submitted-pending como **inferred, migração futura do app**. A LP não busca dados nem aceita formulário: não inserir esses estados/funções na LP. Estado de sessão pertence ao app e não muda. Todos os estados atuais e futuros têm rótulos explícitos; capturas locais do fixture não são evidência de funcionalidade nova.

## 7. Motion & Interaction

**observed**: baseline FAQ 180 ms; primário 160 ms; reduced-motion zera transições. Dust motion live: keyframes com corpos, hooks JS/IntersectionObserver, frame strip e valores medidos em `source/motion.json`; prova em `screenshots/motion/`. Glean/Claude/Notebook têm CSS e reduced-motion em JSON por referência; comportamento autenticado não foi observado. A captura estática reaplica reduced-motion para legibilidade depois de medir motion normal, explicitado em evidence.md.

**inferred**, plano autoral A (não usar motion.css da pesquisa): hover 140 ms só cor/borda; FAQ 180 ms só chevron; troca de caso até 180 ms opacity, mantendo leitura imediata e aria-live polite; reveal inferior opcional 240 ms, translateY 8 px, threshold 0.15, uma vez, stagger 40 ms, máximo 120 ms total. Hero, resposta, fontes e CTAs visíveis no primeiro paint; reveal progressivo não bloqueia conteúdo quando JS falha. Nenhum autoplay, cursor fictício, rolagem sequestrada, typewriter ou parallax sobre fontes. Sem ticker contínuo de integrações.

`prefers-reduced-motion: reduce`: duração/delay 0; transform none; opacity 1; scroll-behavior auto; não alterar o estado selecionado. Focus nunca anima. Se o scroll acionado por âncora for suave no futuro, remover sob reduce. Contrato local de motion proposto em `motion-plan.md`; kit de referência é diagnóstico separado.

## 8. Voice & Brand

**provided**: Arquivio, pt-BR, equipes/organizações. Copy comercial e FAQ literal, preços ausentes. O H1 continua “A resposta está nos arquivos. Agora você sabe onde.”; não inserir slogans das referências, planos, prova social, métricas ou claims novos. Google Drive, OneDrive, Notion, SharePoint são as quatro integrações. “Prévia ilustrativa”, “Estúdio Aurora” e “Exemplos fictícios.” ficam visíveis. A frase de acesso compartilhado e a limitação de permissões SharePoint têm o mesmo destaque de hoje.

Fonte canônica da copy não depende de copywriter: snapshot exato de landing-page.tsx + baseline §§4–5. A LP não ganha “permissões por documento”, “sincronização contínua”, “SOC 2”, “resposta sempre correta”, automações ou integrações importadas dos concorrentes. Tipografia e layout mudam; o contrato de informação permanece.

## 9. Anti-patterns

**inferred**, restrições ligadas ao pedido e baseline:

- Hero só texto e produto abaixo da primeira tela desktop; mockup de chat com texto rasterizado.
- Copiar cenário isométrico do Dust, fotos/orbita do Claude, relevo laranja do Glean ou slides/gradientes do Notebook.
- Accent padrão indigo/purple e gradiente “trust”; lima claro sobre branco como texto normal.
- Rotacionar os casos automaticamente, animar tokens de resposta ou fabricar loading para a LP.
- Truncar “Sem evidência suficiente” ou mover avisos de exemplo fictício para tooltip.
- Trocar fontes por chips sem nome/provedor, inserir links de fonte inexistentes ou substituir a lista por desenho.
- Editar brand.css/globals.css/product-app.tsx/layout.tsx ou qualquer app autenticado durante esta fase.
- Aplicar tokens globais agora; alterar FAQ/CTAs/copy/âncoras para acomodar o layout; gerar mídia antes de H2.
