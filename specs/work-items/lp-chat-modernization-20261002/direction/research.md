# Pesquisa de direção — Arquivio

Data de consulta: **2026-10-02 America/Manaus**, timestamps UTC 2026-10-03 em JSON (UTC−4). Navegador Chromium/Playwright real, anônimo, read-only. Busca web e páginas oficiais; snapshots DOM + getComputedStyle + screenshots. Escopo: site público de cada serviço, não auditoria do app logado. Pesquisa sem envio de prompts, formulários, login ou consentimento. Quatro referências utilizáveis, uma tentativa excluída. Capturas preservam consent banners; estão anotadas, não removidas por CSS. Fontes de UI em imagem/filme das referências não foram interpretadas como componentes DOM.

## Comparação (observed, salvo interpretação marcada)

| Referência / adequação | Layout e hierarquia | Chat / fontes | CTAs / mobile | Motion e tradeoff |
|---|---|---|---|---|
| [Dust](https://dust.tt/) — conhecimento de equipe | Hero split; H1 Geist 69.12 px, peso 550, tracking −2.7648 px; fundo branco | Hero é cena conceitual; chat/contexto aparece mais abaixo. Fontes de resposta não validadas no app | Primário colorido, secundário textual; mobile H1 40 px e composição empilhada. Banner de cookies cobre parte inferior | Pass dedicado: 70 keyframes, 35 elementos animados, hooks JS e frame strip real. Bom ritmo SaaS; cena compete com evidência |
| [Glean Assistant](https://www.glean.com/ai-assistant) — maior proximidade B2B | Texto à esquerda, painel demonstrativo à direita; H1 Polysans 56/53.76 px | Conversa fica na dobra como cena de produto; conteúdo de pesquisa/citações está abaixo, não prova autenticação | CTA escuro + tour; mobile empilha produto depois de copy, banner ocupa área útil | CTA header 250 ms ease-in-out; CSS reduced-motion capturado. Forte produto; visual laranja e UI em cenas não transferíveis |
| [Claude Product](https://claude.com/product/overview) — conversa e simplicidade | Título serif 72/79.2 px, espaço amplo, composição de fotos/cartões | Material público mostra tarefas/demos; hero não demonstra fontes documentais como Arquivio exige | CTA sólido + download; mobile mantém leitura e usa cartões horizontais | Headline/reveal/orbita dinâmicos, CSS reduced-motion. Calor humano; excesso de cena e animação desviaria do diferencial |
| [NotebookLM / Gemini Notebook](https://notebooklm.google/) — informação sustentada por fontes | URL redirecionou a [notebook.google](https://notebook.google/), título observado “Gemini Notebook”; hero com headline rotativa | Narrativa de pesquisa ancorada em material fornecido e notebooks com contagem de fontes; na captura hero mostrou slides, não citações verificadas em chat | CTA único escuro; mobile mostra intro e CTA, sem painel de fontes na dobra | Keyframes de shine/reveal capturados; rotação varia entre viewport/momento. Bom modelo mental de fontes; não importar áudio/slides nem gradiente/cena |

Cada linha se apoia em `source/references/<id>-desktop.json`, `<id>-mobile.json`, DOM HTML e `screenshots/references/<id>-{hero,full,mobile}.png`. Glean foi solicitado em `/product/assistant` e redirecionou para `/ai-assistant`; registrado no JSON. Headline rotativa do Notebook e headline animada do Claude podem diferir entre snapshot inicial e print; este fato é uma limitação observada, não erro de copy Arquivio.

### O que copiar como princípio (inferred), não como execução

Dust: títulos sans compactos e distribuição assimétrica; substituir a cena por chat real. Glean: produto lado a lado com benefício; substituir showreel por uma resposta curta seguida da lista de documentos. Claude: respiro e ausência de ruído dentro do texto; mudar serif para sans e reduzir motion. Notebook: a fonte é objeto identificável, não selo abstrato; expor documento+provedor imediatamente sob a resposta. Todas as decisões são novas propostas para Arquivio, sem transferir marca, ativos, copy, métricas ou claims.

### Limitações / exclusões

[Perplexity](https://www.perplexity.ai/) foi tentada e devolveu Cloudflare “Just a moment…”. Nenhuma captura da barreira compõe o DNA; `source/references/perplexity-gap.json` registra o fato. ChatGPT não foi selecionado: esta comparação já tem quatro referências adequadas, com Glean/Dust mais próximos de organização e Notebook de fontes. Não se afirma comportamento interno, estados autenticados, fidelidade das citações ou conversão de nenhuma referência. Hover/focus são amostras restritas, não cobertura completa; sites com consent overlay podem bloquear o ponteiro.

## Duas direções concretas (inferred)

| Decisão | A — Contexto vivo (recomendada) | B — Farol de conhecimento |
|---|---|---|
| Composição desktop | Hero 42% + preview 58%; chat/fontes em superfície branca na dobra | Hero central em palco escuro; chat branco largo logo abaixo, trilha de fontes |
| Mobile | Copy compacta; chat acima dos rails Biblioteca/Busca; fonte visível logo após resposta | Palco compacto seguido do chat branco; mais área de transição vertical |
| Tipos | Manrope 650 + IBM Plex Sans 400/500/600 | Space Grotesk 600 + IBM Plex Sans 400/500 |
| Paleta | #F5F7F4 / #142B25 / #1C6052 / #D9F279 | #102F27 / #F5F7F4 / #D9F279, UI #FFFFFF / #142B25 |
| Motion | Feedback 140–180 ms; reveal inferior opcional 240 ms | Entrada de painel 240 ms, sem orbita; feedback igual a A |
| Futuro app | Mesmos semantic tokens e UI clara; nenhum tema muda agora | Dark stage fica exclusivo LP; app reutilizaria somente tokens de UI clara |
| Força / custo | Produto legível e confiável; menor custo visual/operacional | Maior impacto de campanha; maior chance de afastar LP da UI atual |

**Recomendação: A.** Resolve o problema observado no baseline (produto abaixo da dobra), preserva a tinta verde e dá visibilidade ao diferencial específico: resposta + origem + limite de evidência. O brilho lima é pequeno, decorativo; a chamada comercial usa verde sólido. B é viável se H2 priorizar contraste dramático e aceitar a distinção entre palco de marketing e superfície do app. Nenhuma direção cria preços, integrações, copy ou funcionalidades.

Fonts abertas, não assets de concorrentes: [Manrope](https://github.com/google/fonts/tree/main/ofl/manrope), [IBM Plex Sans](https://github.com/google/fonts/tree/main/ofl/ibmplexsans), [Space Grotesk](https://github.com/google/fonts/tree/main/ofl/spacegrotesk). Licenças OFL e arquivos no contrato; implantação self-hosted e subset somente após H2.
