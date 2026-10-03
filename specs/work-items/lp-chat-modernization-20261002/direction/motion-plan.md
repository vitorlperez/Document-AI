# Motion Arquivio — proposta inferred, sujeita a H2

| Superfície | Gatilho | Propriedades | Tempo / easing | Reduced-motion |
|---|---|---|---|---|
| CTA/link | hover/active | background/color/border; underline instantâneo | 140 ms, cubic-bezier(.2,.8,.2,1) | 0 ms |
| Focus-visible | teclado | outline 3px/offset 3px | imediato, sem blur | igual |
| FAQ | abrir/recolher nativo | chevron rotate 180deg; texto aparece nativamente | 180 ms, cubic-bezier(.4,0,.2,1) | sem rotação animada |
| Caso de prévia | botão aria-pressed | conteúdo troca imediatamente, fade discreto opcional | 180 ms max | sem fade; aria-live mantém |
| Seção abaixo da dobra | IntersectionObserver, once | opacity + translateY(8px) | 240 ms, threshold .15; stagger 40ms/max120 | opacity1/transformnone, zero delays |
| Mobile menu | details nativo | nenhum bloqueio; abertura imediata | imediato | igual |

Resposta/fontes/hero/CTAs nunca são escondidos antes de JS. Conteúdo base opacity1; nenhuma typing animation, input falso operável, loop de logos, scroll-jacking, parallax de texto ou skeleton fictício. Reveals inferiores opcionais, aprimoramento progressivo; remover se custo ou acessibilidade não justificar. B usa apenas uma entrada opcional de painel com mesmos limites, sem órbita.

`source/motion.json`, `motion.css`, `motion.manifest.json`, `motion.js`, `preview/motion.html` são **captura/derivados diagnósticos Dust**. Não são o plano acima nem assets do Arquivio; não copiar para frontend. Provas CSS não atestam a coreografia JS ou o efeito de conversão. Fase de direção não implementa runtime motion.
