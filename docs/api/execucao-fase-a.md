# Evidência — plano 03, Fase 0 restante e Fase A

Worktree: Document-AI-integracoes, branch feat/integracoes. Sem push. Skills: inline [oc-builder, oc-stamp]. Nenhuma mudança em ingestion/extraction/blocks ou sanitize.

## Entregas e commits

| Tarefa | Commit | Entrega |
|---|---|---|
| T0.1 | d8a77e4 | threat model, invariantes e riscos residuais |
| T0.5 | 03a3f9d | invariante servidor/modelo |
| T0.6 | c43dcd9 | auditoria da cerca F6 existente |
| A1 | 3d2a1d7 | modelos e migrações 0022/0023; predecessor confirmado 0021 |
| A2 | d1d4ee3 | geração/parsing de chave; hash do segredo |
| A3 | 66c7543 | Principal, membro ativo, falha uniforme |
| A4 | 83ae629 | rate limit Redis; fail-closed quando indisponível |
| A5 | 430625f | auditoria independente sem conteúdo |
| A6 | 6d9f226 | seleção dentro das raízes da credencial |
| A7 | e7af65a | recuperação lexical FTS e fetch sem geração |
| A8a | bf50765 | fábrica do agente reutilizada por navegador/API |
| A8 | 8f9507d, 9313cf2 | /v1, escopos, limites, auditoria completa, rótulos não confiáveis |
| A9 | 28d13e8, e213ab7 | administração de chaves, revogação, switches, UTC e CORS PUT |
| A10 | e65ccb3 | tela em Integrações, seleção existente de pastas/arquivos, segredo temporário |
| Validação | commit [A] test(access) | ranking FTS real, expectativa do head e lint dos arquivos novos |
| A11 | commit [A11] docs(api) | referência, política, export JSON validado e CI |

## Provas executadas

| Comando | Exit | Resultado |
|---|---|---|
| `cd backend && .venv/bin/python -m pytest -q` com TEST_DATABASE_URL de PostgreSQL descartável | 0 | **741 passed**, 2 avisos de depreciação preexistentes, sem skips |
| `.venv/bin/python -m pytest tests/unit tests/api -q` | 0 | 728 passed |
| `.venv/bin/python -m pytest -m postgres tests/integration -q` | 0 | 13 passed; o teste posterior de ranking também passou e integra os 741 |
| `.venv/bin/python -m pytest tests/api/test_access_admin.py tests/api/test_csrf_origin.py -q` | 0 | 7 passed; UTC e CORS PUT comprovados red → green |
| `.venv/bin/python -m pytest tests/api/test_public_v1.py -q` | 0 | 15 passed; isolamento org/raízes, revogação, auth separada, limites, auditoria, ask seguro |
| `.venv/bin/python scripts/export_openapi.py --check` | 0 | JSON coincide com /v1 e passa openapi-spec-validator |
| `.venv/bin/ruff check` nos módulos e testes novos de acesso/API/recuperação | 0 | All checks passed |
| `.venv/bin/alembic heads` | 0 | 20260930_0023 (head único) |
| `cd frontend && npm run lint && npm run build` | 0 | lint sem erros; build completo |
| `cd frontend && npx tsc --noEmit` | 0 | sem erros |
| `graphify update .` após cada commit | 0 | graph.json/graph.html/GRAPH_REPORT atualizados; artefatos graphify preexistentes sujos não incluídos nos commits |

Testes foram criados antes da implementação dos módulos (falhas por import ou rotas ausentes). A fábrica do agente teve 1 fail/42 pass antes da implementação e 77 pass nas regressões. Auditoria de metadata/422/503 e limite compartilhado tiveram 2 fail antes do ajuste. A tela não grava segredo em localStorage nem estado persistente.

## Pendências e desvios

> Execução: A7b tem gate explícito no plano: embedding canônico vetorial. A F5 atual mantém embedding JSON e adiciona embedding_vec; busca híbrida não habilitada enquanto esse gate não estiver cumprido.

> Execução: revisão independente do threat model não realizada neste worker. MCP pertence à Fase B; Slack/Teams excluídos pelo dono.

> Execução: smoke visual interativo não concluído: conector retornou “Browser is not available: chrome”. Lint/typecheck/build verdes e ciclo criar → autenticar → revogar → 401 coberto pela API; revisão visual permanece pendente.

> Execução: expectativa obsoleta de processing_jobs no teste PostgreSQL atualizada para incluir a FK manual_sync_runs da migração 0018. Só o teste mudou; sem refatoração fora do plano.

> Execução: dependências dataless da .venv/node_modules foram reinstaladas; SQLAlchemy restaurado à versão original 2.0.52 antes dos 741 testes finais. Chaves de teste e banco descartável não fazem parte dos artefatos.
