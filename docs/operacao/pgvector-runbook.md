# pgvector — runbook (F5: expand, dual-write, backfill, flag)

Escopo desta entrega: migração `20260930_0020_pgvector_expand`, dual-write em `EmbeddingService`, backfill `scripts/backfill_pgvector.py`, `SimilarityIndex` com backends Python e pgvector e a flag `VECTOR_BACKEND` (padrão `python`). Fora do escopo: o *contract* (próximo id livre, ≥ 7 dias após virar a leitura, D10) e o índice ANN (D7: sem HNSW no primeiro release; decidir só pelo benchmark da T5.8).

## Pré-requisitos por ambiente

- `CREATE EXTENSION IF NOT EXISTS vector` exige superuser ou extensão *trusted* disponível para o usuário da `DATABASE_URL`. Disponibilidade local não prova permissão no destino.
- Local/CI: `docker-compose.yml` usa `pgvector/pgvector:pg16`.
- Railway: template Postgres com pgvector ou imagem `pgvector/pgvector:pg16` (`docs/deployment/railway-production.md`).
- Render: extensão suportada no Postgres gerenciado (`docs/deployment/free-pilot-render.md`).
- Oracle: trocar a imagem no compose de produção, que ainda não está versionado (`docs/deployment/oracle-always-free.md`).
- Conferência: `SELECT extversion FROM pg_extension WHERE extname = 'vector';` (≥ 0.8.0 só é exigido se D7 levar a HNSW).

## Sequência (release R2)

1. Backup: `pg_dump` do banco e teste de restauração em homologação.
2. Deploy com `VECTOR_BACKEND=python` (padrão). O pre-deploy roda `alembic upgrade head`, que cria a extensão e a coluna `document_chunks.embedding_vec vector(1536)` nula e sem índice. `ADD COLUMN` sem *default* altera só metadados e não reescreve a tabela. A coluna JSON `embedding` continua existindo e continua sendo a fonte da leitura.
3. A partir desse deploy, todo embedding novo é gravado nas duas colunas (dual-write).
4. Backfill sem custo de API, em lotes, retomável e idempotente:
   `cd backend && python -m scripts.backfill_pgvector --batch 1000`
   Converte `embedding::text::vector` onde `embedding_vec IS NULL AND embedding IS NOT NULL`, com um commit por lote e `FOR UPDATE SKIP LOCKED`.
5. Conferir `SELECT count(*) FROM document_chunks WHERE embedding IS NOT NULL AND embedding_vec IS NULL;` = 0.
6. Paridade em staging: `tests/integration/test_pgvector_search.py` e `scripts/profile_retrieval_eval.py` antes e depois (as citações não podem piorar).
7. Canário: `VECTOR_BACKEND=pgvector` em um ambiente. A pergunta passa a buscar só `(id, similaridade)` do banco, sem trafegar os vetores.

## Rollback

- Leitura: `VECTOR_BACKEND=python` (o JSON segue íntegro durante toda a fase expand).
- Esquema: `alembic downgrade 20260929_0018` remove `embedding_vec`, depois de fazer downgrade da 0020, que depende da 0019. A extensão fica instalada, o que é inofensivo.

## Evidência de execução (2026-09-30, pane-254)

> Execução: container descartável `pgvector/pgvector:pg16` (extversion **0.8.6**). `alembic upgrade head --sql` exit 0, com `CREATE EXTENSION IF NOT EXISTS vector` e `ALTER TABLE document_chunks ADD COLUMN embedding_vec vector(1536)` e sem `hnsw`. Ciclo `upgrade head` → `downgrade -1` (0020) → `downgrade -1` (0019, current = 20260929_0018) → `upgrade head` com todos os passos exit 0; a coluna volta como `vector(1536)`.

> Execução: `tests/integration/test_pgvector_search.py` 4 passed (tipo e autossimilaridade ≈ 1.0; migração adiciona/remove a coluna sem índice; backfill de 2.500 chunks devolve 2.499 e depois 0, com o chunk sem embedding permanecendo NULL; paridade Python × pgvector em 300 chunks com max|Δ| ≤ 1e-5, top-10 idêntico e 0 chunks de outra organização). O formato `json::text::vector` foi aceito sem `replace` de espaços.

> Execução: `tests/unit` + `tests/api` 606 passed. Os testes rodaram numa cópia do backend no scratchpad porque o worktree fica no iCloud com arquivos `dataless`; os arquivos de OCR não commitados da pane-252 foram substituídos pelo HEAD na cópia. A falha de `tests/integration/test_foundation_migration.py` (a tabela `manual_sync_runs` da 0018 não consta do conjunto esperado) é anterior à F5 e não foi tocada.

> Execução: não houve ensaio de backfill em cópia do banco do piloto (a cópia não foi disponibilizada); medir linhas/s e tempo total antes do R2 em produção. O benchmark e a decisão de HNSW (T5.8) ficam pendentes; D7 mantém "sem ANN".
