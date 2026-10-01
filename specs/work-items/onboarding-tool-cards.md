# M31 — Padronização dos cards de ferramentas no onboarding

- Status: implementado e verificado localmente; executor: pane-308; branch compartilhada: main.
- Pedido: corrigir a formatação dos textos dos cards das ferramentas no onboarding.
- Escopo: markup dos cards em `frontend/app/product-app.tsx` e stylesheet próprio;
  preservar `landing-page.tsx`, `landing.css`, `layout.tsx` e alterações concorrentes.
- Causa reproduzida: descrições ficam na coluna estreita entre ícone e seta
  (69px de recuo), ícones se centralizam sobre textos de alturas diferentes,
  rodapés não acompanham a altura dos cards e Airtable usa outro alinhamento.
- Hipótese: cabeçalho independente, descrição ocupando a largura do card,
  tipografia uniforme e rodapé flexível ao fundo eliminam a desformatação.
- Reprodução antes da correção: Playwright com APIs simuladas e frontend fonte,
  larguras 1440/768/390/320; regressão de recuo falha em todas (exit 1).
- Limites: não reconstruir/recriar containers; QA integrado será coordenado após
  a entrega da LP. Nenhuma alteração de integração/Notion nesta etapa, já corrigida.
- Resultado: cabeçalhos iguais, descrições de 13px/22px ocupando a largura do card,
  aviso de conta Microsoft separado, ações no fundo e alvos de toque de 44px.
- E-mails longos ficam limitados à área de status e preservam o valor no tooltip.
- Verificação: 16 casos (4 larguras × 4 estados), 7 interações, 42 testes frontend;
  TypeScript, ESLint e `git diff --check` aprovados. Evidência detalhada:
  `TASK/evidence/m31-onboarding-tool-cards.md`.
- Limite da entrega: validação no frontend fonte com respostas de API simuladas;
  sem rebuild/recreate de containers ou QA integrado desta etapa.

skills: inline [oc-builder, oc-blackbox, oc-stamp]
