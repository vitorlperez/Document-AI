# clickup-connector-20261007 - Conector ClickUp (tarefas e Docs, somente leitura)

**Status:** done

## Source and outcome

- Source specification: pedido do produto (missão "Missao 45", 2026-10-07) + `specs/adr/ADR-0019-clickup-connector.md`; padrão de `specs/adr/ADR-0016-sharepoint-connector.md` e `backend/app/integrations/notion.py`. Análise prévia `specs/research/integracoes-analise-2026-09-29.md` §4 recomendava não priorizar ClickUp; a decisão do produto prevalece (registrado na ADR).
- User outcome: um Owner/Admin conecta o ClickUp por OAuth, escolhe Workspace/Space/Folder/List (ou tudo) e as tarefas e Docs entram na biblioteca da empresa, indexados e citáveis, como qualquer outra fonte.
- Non-goals: escrita no ClickUp, webhooks, comentários, anexos, checklists, histórico, campos de usuário/relacionamento, ACL por tarefa, tarefas fechadas/arquivadas por padrão, MCP de terceiros ao vivo.

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |
| Integrar ClickUp apesar do "fora de foco" da pesquisa | produto (usuário) | aprovado | ADR-0019 |
| Provider `clickup` no padrão Notion, sem migração e sem serviço novo | implementação | aprovado | ADR-0019 D1 |
| Token sem expiração/refresh (docs oficiais) | implementação | aprovado | ADR-0019 D2 |
| Um documento por tarefa; fechadas fora por padrão | implementação | aprovado | ADR-0019 D5/D6 |
| Sem delta de API: re-listar e pular o que não mudou; sem remoções com leitura parcial | implementação | aprovado | ADR-0019 D7 |
| Intervalo 0,7 s (limite 100 req/min) | implementação | aprovado | ADR-0019 D8 |
| Chave de cifra própria `CLICKUP_TOKEN_ENCRYPTION_KEY` | implementação | aprovado | ADR-0019 D9 |
| `ACTIVE_DOCUMENT_LIMIT` (500) precisa subir para orgs com muitas tarefas | produto/operação | **pendente de ação humana** | ADR-0019 Consequências; runbook §2 |

## Ready checklist

- [x] Acceptance criteria written in Given/When/Then form.
- [x] Owning module, API/data impact and failure states identified (módulo `integrations`; sem migração; falhas: 401→`reauth_required`, 403/404 por item, 429→retry/`RemoteThrottled`).
- [x] Authorization, tenant and workspace-folder impact assessed (Owner/Admin para conectar, catálogo e seleção; `organization_id` em todo acesso via `OrganizationScope`; recuperação continua escopada por `workspace_folder_id` pelo pipeline existente).
- [x] Performance and observability impact assessed (≈85 req/min; progresso `(lista|workspace)/total`; logs do `RemoteHttp`; sem segredos em log).
- [x] Protected decisions approved or marked not applicable (provedor externo e custo: aprovados pelo produto; limite de documentos: ação humana).

## Ownership

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | Esta seção + ADR-0019 |
| Implementation owner | `backend/app/integrations/clickup.py`, `registry.py`, `api/integrations.py`, `core/config.py`, `ingestion/tasks.py`, `api/ingestion.py`, `library/service.py` (nome do provider), `scripts/rekey_sources.py`, frontend (`provider-*`, `integrations-screen`, `types-and-api`, `question-scope`, `new-space-options`), infra (`render.yaml`, `docker-compose.yml`), docs | Mudança de produção |
| Test engineer | `backend/tests/unit/test_clickup_integration.py`, `backend/tests/api/test_company_library_api.py` (8 testes ao final), `frontend/tests/provider-labels.test.mjs`, `frontend/tests/new-space-options.test.mjs` | Testes automatizados |
| Feature validator | Read-only | Gate independente (ver Validator report) |

## Acceptance criteria and test matrix

| Criterion | Test layer | Evidence |
| --- | --- | --- |
| **AC1** Dado Owner/Admin, quando inicia OAuth, então é redirecionado a `app.clickup.com/api` com `client_id`, `redirect_uri` e `state`; sem configuração, 503 | unit + API | `test_clickup_authorization_url_carries_client_redirect_and_state`, `test_clickup_requires_oauth_configuration`, `test_clickup_oauth_start_requires_configuration` |
| **AC2** Dado o callback válido, então o token é trocado, cifrado (nunca em claro), e-mail normalizado, auditoria `data_source.connected`, uma fonte por org; state é de uso único | unit + API | `test_clickup_exchange_code_...`, `test_clickup_connection_creates_one_encrypted_source_per_organization_and_audits_it`, `test_clickup_oauth_round_trip_stores_only_encrypted_credentials` (inclui replay → 401) |
| **AC3** Dado membro comum, inativo, outra organização ou fonte de outro provider, então conectar/catálogo/seleção/desconectar são negados e nada muda | unit + API | `test_clickup_connection_denies_members_and_other_organizations_and_foreign_sources`, `test_clickup_catalog_and_selection_reject_non_admins` (member/inactive/outsider), `test_clickup_disconnect_is_admin_only_and_clears_the_credentials` |
| **AC4** Dado o token revogado (401), então a fonte vira `reauth_required` (409), sem 500 e sem perder o indexado | unit + API | `test_clickup_revoked_token_surfaces_as_unauthorized`, `test_clickup_revoked_token_asks_for_reconnection_instead_of_failing` |
| **AC5** O catálogo expõe Workspace › Space › Folder › List e aceita seleção em qualquer nível (e rejeita ID desconhecido) | unit + API | `test_clickup_catalog_builds_the_workspace_space_folder_list_tree`, `test_clickup_catalog_exposes_the_hierarchy_and_saves_a_folder_scope` |
| **AC6** Dada uma seleção, só os descendentes são lidos; Docs só no escopo do pai; tarefas fechadas só com a flag | unit | `test_clickup_selected_folder_indexes_only_its_descendants`, `..._all_accessible_...`, `test_clickup_closed_tasks_are_excluded_unless_enabled` |
| **AC7** O texto indexado carrega fatos da tarefa e a hierarquia dos Docs; título-only continua achável | unit | `test_clickup_task_text_...`, `test_clickup_custom_fields_...`, `test_clickup_doc_text_...` |
| **AC8** Re-sincronização: itens inalterados não são relidos/re-embedados; alterados/forçados/full são; removidos viram `removed` e saem da biblioteca; leitura parcial não remove | unit (puro + persistência real em SQLite) | `test_clickup_unchanged_...`, `test_clickup_naive_database_timestamps_...`, `test_clickup_changed_forced_and_full_runs_reread_content`, `test_clickup_deleted_task_...`, `test_clickup_unreadable_...`, `test_clickup_sync_persists_documents_projects_the_hierarchy_and_prunes_deleted_tasks` |
| **AC9** Paginação (tarefas `last_page`, Docs `cursor`), cabeçalho `Bearer`, 401/403/404 mapeados | unit | `test_clickup_list_tasks_paginates_...`, `test_clickup_docs_are_paginated_by_cursor`, `test_clickup_client_uses_bearer_header_...`, `test_clickup_401_is_auth_and_403_404_are_item_failures` |
| **AC10** Chave própria e distinta em produção; adapter registrado | unit | `test_clickup_registry_adapter_is_wired_...`, `test_clickup_in_production_requires_its_own_distinct_encryption_key` |
| **AC11** UI: card ClickUp com conectar/gerenciar/reconectar/desconectar, rótulo e logo; catálogo hierárquico com caminho completo e cobertura | frontend (node:test + tsc + eslint) | `provider-labels.test.mjs`, `new-space-options.test.mjs` |
| Performance (`sem harness de benchmark`) | advisory | intervalo de 0,7 s por requisição (teórico ≈85 req/min < 100); não medido contra a API real |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |
| `cd backend && .venv/bin/python -m pytest tests/unit -q` | 1211 passed, exit 0 | implementação | validador: ClickUp + remote_http 55 passed |
| `cd backend && .venv/bin/python -m pytest tests/api -q` | 270 passed, exit 0 | implementação | validador: `-k clickup` 9 passed |
| `cd backend && .venv/bin/python -m pytest tests/integration -q` | 20 skipped (exigem `TEST_DATABASE_URL` PostgreSQL), exit 0 | implementação | não executável sem Postgres descartável |
| `cd backend && .venv/bin/ruff check app tests scripts` | All checks passed | implementação | validador: exit 0 |
| `cd frontend && node --experimental-strip-types --test tests/provider-labels.test.mjs tests/new-space-options.test.mjs` | 12 pass, 0 fail | implementação | validador: 12 pass |
| `cd frontend && node_modules/.bin/tsc --noEmit -p .` e `eslint` nos arquivos alterados | exit 0 | implementação | validador: tsc exit 0 |
| `graphify update .` | 7508 nós; `graphify query` encontra `ClickUpDocumentProvider` | implementação | - |

Observação: `pytest backend` sem diretório falha por colisão pré-existente de basename (`tests/unit/test_sync_retest_status.py` x `tests/integration/...`), independente desta mudança; rodar por diretório.

## Validator report

Validador independente (subagente read-only), duas passadas.

- Blocking (1ª passada, **resolvidos e revalidados**): B1 `full_snapshot=True` com leitura parcial removeria documentos indexados (corrigido: `full_snapshot` proibido após leitura parcial; remoções bloqueadas por área; testes `test_clickup_partial_reads_never_become_a_full_snapshot`, `test_clickup_failed_doc_page_read_...`); B2 botão "Reconectar" do modal chamava o OAuth do Google para fonte ClickUp (corrigido no `integrations-screen.tsx`).
- Important (1ª passada, **resolvidos e revalidados**): I1 remoções bloqueadas por tudo-ou-nada; I2 Docs com `parent.type` desconhecido sumiam; I3 seletor sem caminho/kind do ClickUp; I4 biblioteca projetava a árvore inteira (`folders_for_selections`).
- Suggestions aplicadas: guarda de página vazia em `list_tasks`, dedupe por `external_id`, `KeyError`/`SourceItemUnavailable` no callback e no catálogo, `X-RateLimit-Reset` em `http.py` (com piso de 1 s e rejeição de milissegundos após a 2ª passada). Registradas, não aplicadas: lista com 403 permanente bloqueia remoção de tarefas (runbook §4); `X-RateLimit-Reset` também vale para 5xx retryable (aceito); sem teste de renderização do seletor (só tsc + teste da função de caminho).
- Independent evidence: reexecução de pytest (55 e 9 testes), ruff, node:test (12), tsc, mais probes próprios de `discover` (force_full + leitura parcial; known misto de tarefas e Docs; projeção por Folder/List). Nenhuma regressão em Notion/OneDrive/SharePoint/Google nos testes de outros providers.
- Gate decision: **liberar** (2ª passada: sem Blocking nem Important). **Não verificado:** contrato HTTP contra a API real do ClickUp (construído sobre a documentação oficial e testado com respostas simuladas); depende das credenciais do app OAuth (`docs/integracoes/clickup-runbook.md` §3).
