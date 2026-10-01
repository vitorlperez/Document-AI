# M31 — Integrações disponíveis na LP

- Status: implementado e verificado localmente; executor: pane-305; branch compartilhada: main.
- Pedido: atualizar a LP com as ferramentas que têm integração.
- Escopo: `frontend/app/landing-page.tsx`; manter o layout existente.
- Catálogo confirmado no registro backend e na gestão frontend: Google Drive,
  OneDrive, Notion e SharePoint. Airtable está em breve e fica fora da lista.
- Entrega: quatro fontes na seção de integrações, prévia ilustrativa coerente,
  textos de conexão e FAQ com as quatro ferramentas; explicar que SharePoint
  oferece bibliotecas de sites SharePoint/Teams, sem prometer chats do Teams.
- Verificação: suíte frontend existente, TypeScript, ESLint do arquivo, build,
  revisão do diff e atualização graphify.
- Limite: nenhuma mudança no fluxo Notion, já implementado nos commits anteriores.

skills: inline [oc-builder, oc-stamp]

## Revisão do commit 34b9257

- Status: corrigido e verificado localmente; executor: pane-307; branch compartilhada: main.
- Escopo adicional autorizado: `frontend/app/landing.css`,
  `frontend/app/layout.tsx` e FAQ em `frontend/app/landing-page.tsx`.
- Corrigir distribuição das quatro fontes em mobile/tablet/desktop, metadados
  SEO e explicação de Owner/Admin e acesso compartilhado sem permissões
  originais por documento do SharePoint.
- Atualizar somente o serviço frontend local com rebuild/recreate, preservando
  os demais serviços e volumes. Sem push ou deploy externo.
- Contrato: specs MVP §4, ADR-0016 e runbook SharePoint §1/§3.
- skills: inline [oc-builder, oc-blackbox, oc-stamp].

### Correções e evidência da revisão

- Prévia: sidebar vertical acima de 960px; título em linha própria e quatro
  colunas entre 721–960px; duas colunas até 720px, distribuindo as fontes em
  duas linhas equilibradas. Tamanhos de logos e textos preservados.
- `description` e `openGraph.description` citam as quatro integrações.
- FAQ explicita conexão somente por Owner/Admin do Arquivio, distingue
  aprovação pelo administrador Microsoft 365 e informa que as permissões
  originais por documento do SharePoint não são reproduzidas.
- Reprodução estática antes da correção: `/tmp/m31-landing-check.cjs`, 2/12
  verificações aprovadas, 10 falhas, exit 1. Após: 12/12, zero falhas, exit 0.
  Abrange 320, 390, 520, 720, 768, 820, 960 e 1440px; verifica regras CSS,
  equilíbrio das colunas e espaço por fonte, sem substituir renderização visual.
- Verificação final do frontend compartilhado: `node --import tsx --test
  tests/*.test.mjs` (42/42, exit 0), `npx tsc --noEmit` (exit 0),
  `npm run lint` (exit 0) e `npm run build` (5/5 etapas, exit 0).
- `graphify update .`: 6061 nós, 17644 arestas, 346 comunidades, exit 0.
  Artefatos gerados, já alterados antes desta tarefa, ficam fora do commit.
- Rebuild local: a consulta da imagem base e depois o helper
  `docker-credential-desktop` retiveram o build padrão. Após cancelamento,
  reconstrução local sem rede com base `arquivio-frontend:m31-base`,
  dependências idênticas (SHA-256 de package/lockfile conferidos), configuração
  Docker temporária vazia e builder legado. Imagem resultante: `ddfc8c7be3fa`,
  exit 0; Dockerfile temporário fornecido por stdin, sem alterar o do projeto.
- `docker compose up -d --no-deps --force-recreate frontend`: exit 0.
  Conferência de IDs/estado/saúde comprovou sete outros serviços intactos,
  incluindo banco, migração e worker; nenhuma ação em volumes/dados.
- LP e CSS servidos: HTTP 200; HTML contém quatro fontes e a FAQ corrigida;
  os dois metadados contêm os quatro conectores; stylesheet entregue contém
  os grids de duas/quatro colunas. Os três arquivos da LP no container têm
  SHA-256 idêntico ao workspace.
- Coordenação: rebuild incluiu snapshot dos arquivos de onboarding do pane-308
  (`product-app.tsx` e `integration-cards.css`). O CSS continuou mudando após
  a captura e diferia do workspace na conferência; a entrega final de onboarding
  requer seu próprio rebuild. Esses paths não pertencem a este commit.
- Limite visual: browser `iab` indisponível e inventário de navegadores vazio;
  nenhuma inspeção visual realizada. Sem push ou deploy externo.

## Evidência

- `node --import tsx --test tests/*.test.mjs`: 42 passed, 0 failed, exit 0.
- `npx tsc --noEmit`: exit 0.
- `npx eslint app/landing-page.tsx`: exit 0.
- `npm run build`: cinco etapas concluídas, exit 0.
- `git diff --check`: exit 0; revisão confirmou quatro fontes na lista,
  SharePoint na prévia e menção às quatro ferramentas na FAQ/processo.
- `graphify update .`: 6059 nodes, 17642 edges, 355 communities, exit 0.
  Arquivos gerados já estavam alterados; permanecem fora do commit.
- Layout/CSS existentes preservados. Sem nova inspeção visual em navegador
  nesta etapa e sem deploy; verificações são locais.
