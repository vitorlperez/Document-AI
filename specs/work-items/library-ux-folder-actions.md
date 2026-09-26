# Biblioteca: experiência e gestão por pasta

**Status:** done

## Fonte e resultado esperado

- Pedido do usuário nesta missão e `specs/001-mvp-document-intelligence.md`, F3; contrato aprovado em `specs/work-items/F-029.md`.
- Na Biblioteca, Owner/Admin pode escolher um `WorkspaceFolder` sincronizado, iniciar re-sync somente desse escopo e remover o escopo com confirmação explícita de perda dos dados indexados locais.
- Member pode navegar sem ações de gestão. Falhas e job ativo são mostrados claramente; o provedor externo permanece intacto.
- A tela deve facilitar navegação, identificação do escopo atual, estado de sincronização e acesso às ações.
- Investigar resync incremental por provedor, sem alterar nesta entrega a política de ingestão.

## Decisões, impacto e propriedade

- "Pasta" gerenciável é o `WorkspaceFolder` (F-029); pastas intermediárias da árvore remota não recebem exclusão local avulsa.
- Backend já possui POST `/workspace-folders/{id}/sync` (202) e DELETE `/workspace-folders/{id}` (204, 409 em job ativo), sempre com `organization_id`; nenhuma alteração de API ou migração.
- UI: pane-53, somente `frontend/app/product-app.tsx` e CSS da Biblioteca. Backend: pane-56, auditoria sem mudanças. Testes: pane-57, `backend/tests/`. Incremental: pane-58, investigação somente leitura. Integração/validação final: pane-52.
- Autorização: Owner/Admin; backend valida organização e pasta; Member não recebe ações. Exclusão não toca arquivos ou credenciais externos.
- Falha da fila retorna 503 e mantém job durável para retry; UI deve comunicar falha e permitir nova tentativa.

## Aceite e testes

| Critério | Evidência |
| --- | --- |
| Gestão de pasta com confirmação e estados claros na Biblioteca | Implementação UI e revisão independente pendentes |
| Exclusão local preserva fonte e outras pastas | Testes API do pane-57: 12 focados passaram |
| Re-sync enfileira só a pasta escolhida | Testes API do pane-57: 12 focados passaram |
| Member/tenant estrangeiro negados; 409/503 tratados | Testes API do pane-57: 12 focados passaram |
| Viabilidade incremental documentada | Pane-58: OneDrive delta existente; Google changes.list possível; Notion metadata possível com ressalvas |

## Validação

- Backend: 34 testes focados e Ruff passaram na auditoria do pane-56; sem diff em `backend/app/`.
- Testes adicionais: 12 testes focados e Ruff passaram; commit `1e2ad42` adiciona `backend/tests/api/test_workspace_folder_management_api.py`.
- Frontend: `npm run build` passou; `npm run lint` passou sem erros, 1 warning preexistente (`loadCatalog`).
- API focada: 5 testes passaram ao rerodar; backend tests e Ruff passaram na validação independente (17 API tests).
- `git diff --check` passou. Revisor independente aprovou polling (erros visíveis, tracker liberado) e região aria-live; 0 findings.
- `graphify update .` executado após as alterações.
- Investigação de provedores: OneDrive já usa delta; Google Drive oferece Changes API; Notion permite pular leitura de blocos por `last_edited_time` com reconciliação da listagem. Alterações incrementais apareceram em commits separados durante o trabalho; a validação ampla encontrou 1 teste OneDrive falhando e Ruff apontou import `quote` ausente na implementação Google. Não fazem parte do diff da Biblioteca e permanecem sem aprovação nesta entrega.
- Gate: aprovado para UX/ações da Biblioteca.
