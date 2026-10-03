# Arquivio — direção da LP, H2 pendente

**Recomendação A / Contexto vivo**: marca original, superfície clara e chat com fontes desde a dobra. **B / Farol de conhecimento**: palco verde escuro, marca original em placa branca, chat claro. Somente direção; nenhuma implementação ou geração de mídia.

Abra **STYLEBOARD.pdf** para comparar as duas direções: 10 páginas, desktop/mobile, estados, paleta/type, motion e decisão H2. UI própria desenhada em texto/vetores, fontes abertas incorporadas.

## Contrato para o build posterior

- DESIGN.md: nove seções canônicas; design-dna.md: índice portátil.
- design-contract.md: evidência/decisões/riscos/gate.
- research.md: quatro referências oficiais com links, tradeoffs e datas; Perplexity bloqueada e excluída.
- implementation-handoff.md: arquivos permitidos e preservação exata de copy/wiring/estados.
- tokens.css + design-tokens.css: canônico/alias exato, **103 tokens** em quatro camadas e extensões; JSON/Tailwind derivados.
- motion-plan.md: motion autoral Arquivio. **Não usar motion.css/js**: são diagnóstico da referência Dust.
- assets-policy.md + assets/README.md: imagem própria opcional, não produzida; sem vídeo/áudio.

## Evidências técnicas

source/evidence.md orienta a leitura de source/references, screenshots/references, motion/component capture e provas. source/preservation-lock.json trava os arquivos de produto/baseline. source/contrast-report.json: 11 pares passam; source/fixture-proof.json: zero requests externos/erros, mobile 375 sem overflow, reduce=0s, arquivos protegidos intactos. source/quality-gate.txt: P0 8/8, P1 5/5. source/motion-preview-proof/report.json: 53/70 swatches; 17 gaps da pesquisa, declarados e sem impacto no plano próprio.

HTMLs componentes/previews são espécimes técnicos requeridos pelo contrato da skill, não um site implementado. O artefato visual independente de aprovação é o PDF. Fonte editável do PDF em source/styleboard-source.py; fixture em source/emit-fixture.py. Tudo desta execução está neste diretório; baseline e arquivos da copywriter intocados.

skills: inline [oc-design-dna, oc-browser]. PDF skill lida para autoria/renderização. H2 permanece humano e pendente.
