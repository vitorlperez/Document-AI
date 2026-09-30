# ADR-0013: Chave por provider

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

Chave própria de Notion obrigatória em produção quando Notion habilitado; chaves preenchidas de providers distintos não podem ser iguais. MultiFernet cifra com primária e lê legadas. Fallback Google para Notion somente durante migração, controlado por NOTION_TOKEN_ENCRYPTION_LEGACY_FALLBACK; rekey dry-run por padrão, aplicar, conferir e desligar fallback. Base OAuth compartilha validação de sessão/state com FOR UPDATE, admin e disconnect; contratos públicos preservados.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4
