# Proveniência e escopo

Pesquisa real em 2026-10-02 America/Manaus (UTC−4); timestamps ISO UTC em 2026-10-03 nos JSON. Captura por Playwright Chromium anônimo, read-only: DOM, computed style, screenshots em 1440×900 e 390×844; fullpage desktop e mobile onde disponível. Sem login, envio de prompt/formulário, consentimento ou download de assets proprietários para reutilização.

| ID | URL solicitada → final | Capturas / dados | Confiança |
|---|---|---|---|
| dust | https://dust.tt/ → mesma | references/dust-*; hero/full/mobile + CTA hover/focus; desktop DOM/styles | observed |
| glean | https://www.glean.com/product/assistant → https://www.glean.com/ai-assistant | references/glean-*; hero/full/mobile/mobile-full; DOM/styles/states | observed |
| claude | https://claude.com/product/overview → mesma | references/claude-*; hero/full/mobile/mobile-full; DOM/styles/states | observed |
| notebook | https://notebooklm.google/ → https://notebook.google/ | references/notebook-*; hero/full/mobile/mobile-full; DOM/styles/states | observed |
| perplexity | https://www.perplexity.ai/ | source/references/perplexity-gap.json; bot wall excluída | observed, gap |

Paths de referências: DOM/dados em source/references; PNG em screenshots/references. DOM inclui conteúdo alheio unicamente como evidência privada, nunca copy a usar. Não há download de logos/imagens dessas páginas em assets/. Banners consent permanecem nos prints; podem limitar a dobra e pointer. Campos de computed style capturados antes da redução de movimento; screenshots legíveis em reduced-motion nas recapturas de Glean/Claude/Notebook. Dust inicial em no-preference. Headline rotativa do Notebook e animação de palavras do Claude mudam entre snapshot e print; comparar por frame, não supor uma cena constante.

Pass dedicado Dust antes de congelar: source/motion.json, 70 keyframes com corpos, 35 elementos animados, 154 transições distintas, 50 reveals amostrados, 11 grupos stagger, 35 regras reduced-motion, 10 chamadas Element.animate e 30 observers. 5 frames de uma animação com hashes distintos em screenshots/motion/. Ausência de canvas nesta captura não comprova ausência em todo o serviço. Motion kit derivado é somente diagnóstico e declara reproducibilidade parcial para JS. NÃO reutilizar motion.css/motion.js como plano Arquivio.

Pass estrutural Dust: source/components.discovered.json; 43 clusters nomeados, 18 repetidos, 31 screenshots, 3 estados com diffs calculados em 25 probes. Oito riscos reportados no arquivo são mantidos, inclusive probes sem estado real. Não converter estado ausente em observado.

Tooling: scripts da skill tentados primeiro; resolver ESM `import(index.js)` devolveu Playwright em `default`, deixando chromium undefined. Cópias temporárias em /tmp normalizam esse import; scripts/skills originais e produto não foram editados. Runs efetivos alcançaram o site real. Script custom /tmp/oc-browser-direction.cjs registra DOM/multi-viewport, capability que a lista MCP carregada não expôs.

Proposta de token: source/tokens.source.json; token-contract.report.json mapeia cada declaração → linha/source/confidence. Três valores da marca são provided por baseline (accent/hover/ink); demais valores são inferred, autorais. Nenhuma proposta é falsamente carimbada observed. Alias design-tokens.css é cópia portátil exata de tokens.css. Derivação JSON/@theme em source/derive-contract.mjs; revisar coerência e não editar derivados isoladamente.

Fontes abertas originais de Google Fonts, licenças OFL incluídas em fonts/. Famílias/weights são proposta inferred, arquivos físicos/licença verificáveis. Não são extração de fontes proprietárias dos concorrentes. Fontes no PDF e fixture não alteram app ou LP.

Fixtures Arquivio: somente contrato, não implementação de produto. source/preservation-lock.json + landing-source.snapshot.txt travam copy/wiring e arquivos protegidos. source/contrast-report.json contém cálculo sRGB de 11 pares propostos. Previews locais devem produzir zero requisições externas e conservar reduce. STYLEBOARD.pdf usa texto selecionável/vetores para UI própria; nenhuma fala/citação foi rasterizada no estudo.

Prova de motion: verify-motion executado com Chrome headed; 53/70 swatches passam, 17 falham (frames 0/50 idênticos, variáveis de contexto ausentes ou mudanças de propriedades não provadas). Autoplay/scrub/play/pause funcionam; zero requests externos e reduced-motion estão no report. Não reescrever observações para passar a prova. Gaps restritos ao diagnóstico Dust, que não é reutilizado no produto. Lista nominal e frames em source/motion-preview-proof/report.json.
