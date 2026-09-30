# ADR-0012: Núcleo HTTP e erros remotos

- **Status:** Aprovado
- **Data:** 2026-09-29
- **Decisor:** produto (usuário); demais defaults do plano

## Contexto

Execução do plano 01; numeração reservada pelo índice §4.

## Decisões

RemoteHttp centraliza backoff, jitter, Retry-After e portão compartilhado. Orçamento em requisição de 90 s; throttling libera job, após 3 retries falha source_rate_limited sem reauth. Drive 401 e 403 desconhecido são auth; rateLimitExceeded/userRateLimitExceeded/sharingRateLimitExceeded são quota; dailyLimitExceeded não repete em requisição. insufficientFilePermissions/appNotAuthorizedToFile/cannotDownloadFile/fileNotDownloadable falham somente o item. Graph mantém 401/403 como auth até plano 02; Notion 401 auth, 403/404 item.

## Consequências

Entregas incrementais com testes primeiro; spikes externos e gates operacionais permanecem explícitos.

## Referências

- specs/plans/integracoes/01-cobertura-e-nucleo.md
- specs/plans/integracoes/00-indice.md §4

- Conferência em 2026-09-29: https://developers.google.com/workspace/drive/api/guides/handle-errors e https://developers.notion.com/reference/status-codes ; Notion request-limits confirma espaçamento médio de 3 req/s. cannotDownloadFile é mantido defensivamente como erro de item; não consta como seção no guia Drive consultado.
