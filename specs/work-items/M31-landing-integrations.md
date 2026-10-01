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
