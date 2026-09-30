# ADR-0014: pgvector

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

Primeiro release sem ANN: busca exata filtrada por tenant. HNSW somente após benchmark justificar. Expand/dual-write/backfill precedem mudança de leitura; contract somente após 7 dias de produção sem divergência e dump de rollback. Migrações seguem próximo número livre e down_revision de alembic heads, nunca revisão duplicada.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
