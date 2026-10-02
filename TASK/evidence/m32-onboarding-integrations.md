# M32 — onboarding e integrações

## Alterações verificadas

- Google Drive incluído no retorno OAuth compartilhado: carrega a fonte conectada e abre o modal de gerenciamento `sync-tool-title` diretamente.
- Modal intermediário exclusivo do Google Drive removido, incluindo suas props. O cabeçalho do cartão gerencia uma fonte conectada ou inicia a autorização nos demais estados.
- Os quatro cartões usam `Conectar` como texto da conexão inicial. Os estados de gerenciamento e reconexão mantêm suas ações.
- `integration-cards.css`, importado por `product-app.tsx`, aplica `cursor: pointer` aos cabeçalhos clicáveis e às ações dos cartões, e `cursor: not-allowed` aos botões desabilitados. Isso também cobre a segunda etapa do onboarding, que reutiliza `IntegrationScreen`.

## Evidência — 2026-10-02

- `cd frontend && npx tsc --noEmit --incremental false`: exit 0.
- `cd frontend && npx eslint app/product/integrations-screen.tsx`: exit 0.
- `cd frontend && node --experimental-strip-types --test tests/new-space-options.test.mjs tests/provider-labels.test.mjs tests/sync-status.test.mjs`: 39 testes, 39 passaram, 0 falhas, exit 0.
- `node /tmp/m32-integration-smoke.cjs`: 8 verificações de comportamento, exit 0. O script temporário transpila o componente e exercita seus efeitos e handlers com hooks/API simulados: retorno OAuth das quatro integrações, quatro botões `Conectar` e cabeçalho do Google Drive nos estados conectado, reconexão necessária e desconectado.
- O mesmo script sobre o componente anterior (`--before`) falhou com `google_drive must open management after OAuth`, confirmando a reprodução do comportamento corrigido. Exit 1 esperado.
- `graphify update .`: exit 0; 6344 nós, 18960 relações, 349 comunidades. Grafo, relatório, HTML, labels e manifest atualizados.
- `git diff --check`: exit 0.

A verificação de comportamento usa API simulada; não foi executada uma autorização Google real ou uma validação visual no navegador. A regra de cursor foi inspecionada no CSS compartilhado.

Alterações concorrentes na biblioteca, shell, layout e tour não foram editadas nem incluídas no commit desta tarefa.
