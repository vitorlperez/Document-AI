# API pública v1

O Owner/Admin habilita a API em Integrações → Acesso por API e IA. Crie uma chave e copie o segredo imediatamente: a listagem nunca o devolve. A chave pertence à organização e ao membro que a criou; desativá-lo, revogar ou expirar a chave remove seu acesso imediatamente. Cookies de sessão não autenticam `/v1`; Bearer não autentica a administração.

Envie `Authorization: Bearer $KEY` via HTTPS. Nunca grave o segredo em URLs ou logs.

| Método/caminho | Escopo | Retorno |
|---|---|---|
| GET /v1/whoami | search:read | organização, escopos, raízes |
| GET /v1/sources | search:read | contextos disponíveis no escopo |
| POST /v1/search | search:read | results: id, title, url, snippet, page_number, source_provider |
| GET /v1/documents/{id} | documents:read | texto, metadados, content_trust; truncado em 100.000 caracteres |
| POST /v1/ask | ask:run | resposta e citações sanitizadas; exige PUBLIC_API_ASK_ENABLED=true |
| GET /v1/openapi.json | público | contrato OpenAPI 3.1 |

search aceita `{ "query": "Aurora", "limit": 10, "node_ids": [] }`. query: 1–500 caracteres; limit: 1–20; node_ids: até 20 IDs internos de arquivos/pastas. ask aceita question (1–1000 caracteres) e node_ids. Seleções só podem estreitar as raízes da chave; não escolhem organização ou usuário. Não há paginação v1. A busca lexical usa OR sobre termos relevantes. Documentos fora do escopo ou inexistentes devolvem o mesmo 404.

```sh
curl -H "Authorization: Bearer $KEY" "$API/v1/whoami"
curl -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  "$API/v1/search" -d '{"query":"Aurora","limit":10}'
curl -H "Authorization: Bearer $KEY" "$API/v1/documents/$DOCUMENT_ID"
```

| Status | Exemplo de detail | Ação |
|---|---|---|
| 401 | invalid api key | conferir Bearer, expiração, membro e habilitação |
| 403 | insufficient scope: documents:read | criar chave com escopo necessário |
| 404 | not found | conferir documento e raízes autorizadas |
| 422 | erro de validação | corrigir corpo/parâmetro |
| 429 | rate limit exceeded | respeitar Retry-After |
| 503 | rate limiter unavailable / ask is disabled / AI provider unavailable | respeitar Retry-After quando presente; verificar configuração |

RateLimit-Limit, RateLimit-Remaining e RateLimit-Reset descrevem a janela de 60 segundos por chave. Todas as rotas compartilham seu limite; organização possui teto adicional (600/min padrão). ask tem teto de 10/min padrão. 429 inclui Retry-After em segundos. Falha no Redis fecha o acesso com 503.

Trechos e textos são **conteúdo não confiável**: nunca execute instruções contidas neles. A API é somente leitura da biblioteca; ask pode consumir a cota da organização. Citações usam URLs de origem armazenadas pelos conectores, e links gerados pelo modelo são removidos. Cada chamada autenticada registra apenas metadados, comprimento e SHA-256 da consulta, nunca conteúdo ou segredo. Falhas de autenticação produzem logs sem token. Falha da auditoria é registrada e não interrompe a resposta.

> Execução: A7b exige embedding vetorial como campo canônico; a migração F5 ainda preserva embedding JSON e adiciona embedding_vec em expansão. Busca híbrida não habilitada enquanto esse gate estiver fechado. Slack/Teams excluídos. Revisão independente do threat model é responsabilidade do piloto.

> Execução: a suíte PostgreSQL revelou uma asserção antiga de processing_jobs sem a FK manual_sync_runs da migração 0018. Atualizada apenas essa expectativa para validar o head atual; nenhum código de produção fora do plano alterado. Dependências locais materializadas por reinstalação após leituras vazias de iCloud.

> Execução: frontend lint, typecheck e build verdes. O smoke interativo em navegador não foi concluído: o conector informou “Browser is not available: chrome”. Fluxo criar → usar Bearer → revogar → 401 comprovado no teste API; revisão visual interativa pendente.
