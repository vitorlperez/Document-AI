# Revisão independente de c059e1a — integração Notion

Revisor: pane-299. Data: 2026-10-01. Base: `c059e1ac471d06f18c3331da40ee4190bb39a43c`.
skills: inline [oc-conveyor, oc-stamp]

O modelo de página/conteúdo/agrupamento é adequado ao pedido, mas o commit original
não estava completo: três defeitos funcionais reproduzidos foram corrigidos nesta revisão,
conforme autorização explícita para ajustar problemas encontrados. A aprovação é local,
com as limitações abaixo; nenhuma implantação ou sincronização de dados reais foi feita.

## Achados confirmados no commit original

- `backend/app/ingestion/tasks.py:335` — F-203: o reparo dependia de um `LibraryNode`
  compartilhado ainda ser pasta. Depois de outro espaço converter esse nó em arquivo,
  o índice legado do espaço seguinte era considerado inalterado. Correção: versão de
  extração persistida por documento; descoberta completa enquanto houver índice antigo.
- `backend/app/integrations/notion.py:533` — F-204: `child_page`/`child_database` com
  outro pai real eram corretamente excluídos da descendência, mas também perdiam sua
  referência textual. Correção: preservar título/URL na origem sem ler/importar o alvo.
- `backend/app/library/service.py:918` — F-205: a poda global de pastas vazias deletava
  agrupamentos de outros espaços. Correção: capturar a hierarquia anterior das seleções
  e dos documentos do espaço atual e limitar a poda aos candidatos desse escopo.

Contagem do commit revisado: **0 critical, 3 warnings** (todos funcionais, severidade média).
Os três foram corrigidos localmente.
Os registros F-203/F-204/F-205 ficam em `corrigido`, disponíveis para nova verificação independente.

## Evidência nova e regressões

Diretório backend: `backend/`; frontend: `frontend/`.

| Comando | Resultado observado |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/unit tests/api`, antes das alterações | 1253 passed, 4 warnings; reexecução confirma a contagem declarada pelo autor |
| `node --import tsx --test tests/*.test.mjs` | 40 passed, 0 failed, exit 0; reexecutado também após as correções |
| Pytest dos 3 novos casos de versão/reparo/ingestão antes da correção | 3 failed, exit 1; reparo sem `force_full`, documento sem versão e ingestão sem suporte à versão |
| Pytest de `test_notion_synced_child_links_preserve_reference_without_importing_target` antes da correção | 2 failed, exit 1; página e base referenciadas faziam desaparecer o documento de origem |
| Pytest de `test_notion_projection_preserves_empty_database_of_another_space` antes da correção | 1 failed, exit 1; agrupamento de B deletado no sync de A |
| `.venv/bin/python -m pytest -q tests/unit/test_company_library.py tests/unit/test_sync_worker_discovery.py tests/unit/test_notion_integration.py tests/unit/test_ingestion_service.py` | 74 passed, exit 0 |
| `.venv/bin/python -m pytest -q tests/unit tests/api`, estado final | **1259 passed**, 4 warnings, **exit 0**, 43.70 s |
| `.venv/bin/ruff check .` | All checks passed, exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npx eslint app/new-space-options.ts app/product-app.tsx` | exit 0 |
| `npm run build` | as cinco etapas Vinext concluídas, exit 0 |
| `.venv/bin/python scripts/export_openapi.py --check` | OpenAPI export matches /v1, exit 0 |
| `git diff --check` | exit 0 |
| `graphify query "Integração Notion: páginas com conteúdo próprio, subpáginas, referências, bases e documentos na biblioteca; alterações no commit c059e1a"` | exit 0; consulta inicial ao grafo |
| `graphify update .` | exit 0; atualização AST após mudanças de código, sem LLM |

## Matriz contra o pedido

| Caso | Evidência verificada |
| --- | --- |
| Página com corpo e filhos | `test_notion_selection_indexes_descendants_and_uses_distinct_container_ids`: pai/filho separados, corpo do filho ausente do pai, IDs de agrupamento distintos, rótulo “Conteúdo de Parent” |
| Fronteira de página e blocos internos | `test_notion_child_pages_are_boundaries_not_parent_content` e `test_notion_page_blocks_include_nested_children`: não lê corpo do filho no pai; toggles continuam lidos |
| Referências sem importar/duplicar corpo do alvo | seleção anterior inclui `link_to_page` fora do escopo; `test_notion_rich_text_links_are_references_not_descendants`; novo teste parametrizado de referência de página/base em bloco sincronizado |
| Página vazia ou editada para vazio | `test_notion_discover_skips_empty_metadata_pages`, `test_notion_page_edited_to_empty_content_is_removed_from_index`: sem documento artificial; índice antigo é removido |
| Página só com filhos | fronteira de blocos gera texto vazio próprio; seleção projeta o pai pela ancestralidade dos filhos sem criar conteúdo artificial |
| Bases com múltiplas coleções, paginação, propriedades sem corpo | `test_notion_database_rows_and_block_children_are_paginated_without_flattening`: duas coleções, duas páginas de registros, duas páginas de blocos, número zero e status preservados |
| Metadados incrementais, novo filho fora da busca e página conhecida omitida | `test_notion_unchanged_pages_still_refresh_library_metadata`, `test_notion_new_child_of_unchanged_page_is_discovered_before_search_indexes_it`, `test_notion_search_absence_does_not_remove_a_still_accessible_known_page` |
| Dados legados, identidade e exclusões | `test_notion_legacy_folder_collision_is_repaired_without_changing_document_id`, `test_notion_legacy_folder_exclusions_apply_to_new_descendants`, novos testes de versão e reparo após outro espaço alterar o catálogo |
| Biblioteca e ressincronização de agrupamento | `test_notion_tree_browses_content_and_children_and_resyncs_its_real_selection`; API `test_notion_catalog_exposes_page_hierarchy_and_saves_provider_specific_scope_name`; frontend “Notion page paths disambiguate equal titles and preserve item types” |
| Agrupamentos vazios e vários espaços | novo teste SQLite preserva B no sync de A e remove a projeção obsoleta de A sem afetar B |

## Limitações

- Testes unitários/API com Notion/HTTP simulados e SQLite. Não comprovam latência,
  permissões e formatos de todos os objetos de um workspace Notion real; não houve
  teste visual no navegador da biblioteca autenticada.
- O reparo ocorre em cada espaço no seu próximo sync: corrigir o código não modifica
  imediatamente os índices persistidos. A primeira releitura completa pode consumir
  processamento/embeddings; a versão impede repetir a migração em índices já atualizados.
- Anexos binários/OCR não são importados; a biblioteca recebe nome/legenda quando existem.
  Relações truncadas mantêm indicação de referências adicionais, sem buscar os alvos.
- Páginas vazias não produzem arquivo; bases/coleções podem continuar como agrupamentos vazios.
- Blocos internos de páginas conhecidas ainda são consultados no incremental para descobrir
  filhos ausentes da busca. Portanto, a otimização poupa indexação e não todas as chamadas HTTP.
- Os quatro warnings backend são depreciações preexistentes (Starlette/AnyIO/Alembic).

## Referências oficiais conferidas

- [Parent object](https://developers.notion.com/reference/parent-object): hierarquia
  página/bloco/base/coleção; registros usam pai `data_source_id` na versão moderna.
- [Block object](https://developers.notion.com/reference/block): tipos de bloco,
  fronteiras de child pages/databases e blocos sincronizados.
