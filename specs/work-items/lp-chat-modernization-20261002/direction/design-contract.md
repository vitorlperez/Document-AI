# Design contract — direção, H2 pendente

## Goal & target
LP pública Arquivio para equipes pt-BR: mostrar chat com documentos/fontes desde a dobra e renovar expressão SaaS preservando marca, toda copy e interações. Sem implementação, app autenticado, arquivos compartilhados, geração de mídia, preço novo ou claims novos.

## Evidence table

| evidence | confidence | note |
|---|---|---|
| brief-baseline.md §§3–7 + work-item.md | provided | limites, marca, copy, destinos e estados vinculantes |
| baseline/desktop-01-fold.png + mobile-01-fold.png | observed | capturas prévias; produto fora da primeira tela |
| source/references/*-desktop.json + *.dom.html | observed | DOM, estilos calculados, URLs finais, timestamps, clusters |
| screenshots/references/*-hero/full/mobile.png | observed | quatro páginas públicas reais; consent banners e rotação preservados |
| source/motion.json + screenshots/motion/* | observed | Dust, pass antes de qualquer freeze, frames distintos; não copiar |
| source/components.discovered.json | observed | vocabulário Dust capturado estruturalmente; distinto dos componentes Arquivio |
| tokens.css + token-contract.report.json | inferred/provided por token | proposta A; verde/hover/brand ink vêm da baseline; nenhum token sem fonte |
| STYLEBOARD.pdf + fixtures | inferred | estudos vetoriais próprios, proposta e contrato; não produto implementado |

## Keep / Change / Do-not-copy

| Referência | Keep | Change | Do-not-copy |
|---|---|---|---|
| Dust | ritmo sans, hero dividido | produto substitui metáfora gráfica | isometria, cores, logos, avatares, números e claims |
| Glean | UI presente na primeira tela | fontes legíveis em HTML, não showreel | relevo laranja, cenas, Polysans, promessas enterprise |
| Claude | superfície quieta, leitura clara | sans, fontes junto da resposta, motion menor | fotos, órbitas, marca, fontes proprietárias e copy |
| Notebook | material fonte identificável | destacar resposta e documentos antes de formatos derivados | slides, áudio, gradiente, Google Sans e assets |
| Arquivio baseline | marca, verde, texto, CTAs, FAQ, casos, avisos | hierarquia, grid, tipo e espaçamento | nada deve ser removido para caber; snapshot é binding |

## Stance
A, Contexto vivo: ferramenta de conhecimento clara, protagonista em HTML, tinta verde preservada e sinal lima discreto. Uma única prévia ao lado do hero; resposta e lista de documentos no centro de maior contraste. Mobile empilha sem perder estados ou avisos. A elegância deve facilitar a inspeção de evidência, enquanto a modernidade vem do peso sans, contraste e composição.

## Risks & unknowns

- H2 ainda não aprovou A/B, webfonts ou slot opcional; **nenhuma implementação autorizada por este contrato**.
- Alturas da nova dobra são metas inferred: precisam de prova 375/768/1024/1440 após H2. Em 375×667 não cabe toda a figura/copy; scroll normal obrigatório.
- Pesquisa anônima não comprova citações, permissões, estados internos ou a11y dos apps concorrentes.
- Cookie overlays limitam inspeção de algumas interações; não foram aceitos nem removidos. Perplexity foi excluída por Cloudflare.
- Claude/Notebook têm hero dinâmico: prints em reduced-motion para leitura, valores motion medidos antes. Não combinar frames como se simultâneos.
- Kit motion derivado reproduz diagnóstico CSS de Dust parcialmente; não reproduz JS/canvas e não é o plano Arquivio. Verify-motion: 53/70 amostras passam, 17 com gaps documentados; não há alegação de reprodução completa. 70 animações de referência não são 70 animações propostas.
- Não há fonte custom já aprovada. OFL proposta e arquivos originais disponíveis; pesos/self-hosting/subset ainda dependem de H2. CSS usa fallback.
- Não há imagem própria existente definida para I-01 (`asset: ?`, inferred). Layout deve funcionar sem imagem. Imagem pode ser produzida depois de H2; áudio/vídeo não têm key e não fazem parte do plano.
- Fixture de futuros estados do app é documentação técnica; não novas funções da LP. Native FAQ/menu e três casos atuais são binding.

## Quality-gate checklist

- [x] 4 referências utilizáveis com URL/data, DOM, full/hero/mobile; bot wall excluído.
- [x] DESIGN.md contém 9 headings exatos; evidência separada de proposta.
- [x] Tokens em A1-identity/A1-structure/A2/B-slot/C-extensions, fonte/confiança/linha; JSON/Tailwind derivados.
- [x] Nenhum accent indigo/purple ou trust-gradient no contrato Arquivio.
- [x] Fixture técnico separa componentes existentes de 5+3 estados futuros; seletores hover/active/focus.
- [x] Marca/copy/destinos/âncoras/FAQ/avisos e assinatura travados em source/preservation-lock.json.
- [x] Contraste normal ≥4.5:1, foco/controle ≥3:1 calculados em source/contrast-report.json.
- [x] PDF renderizado e inspecionado; UI própria em texto/vetor; fontes incorporadas.
- [x] Linter determinístico da skill executado contra este diretório; resultado em source/quality-gate.txt.
- [ ] H2 humano: escolher direção; aprovar tipo/cores/composição/motion/slot. Continua pendente.

A aprovação do fixture/linter comprova a integridade dos artefatos de direção, não aprovação humana nem validação de uma LP construída.
