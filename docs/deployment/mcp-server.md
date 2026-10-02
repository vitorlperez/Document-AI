# Serviço MCP remoto (somente leitura)

Endpoint Streamable HTTP stateless (`/mcp`) que expõe `search`, `fetch` e `list_sources`. É um *resource server* OAuth: o AuthKit (WorkOS) emite os tokens; o Arquivio só os valida.

## Railway (6º serviço)

- Serviço `mcp`, mesmo ambiente e região dos demais. Root Directory `/backend`, Dockerfile `Dockerfile` (mesma imagem da `api`).
- Start: `/bin/sh -c 'exec uvicorn app.mcp_server.asgi:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"'`
- Healthcheck: `/health/live`. Domínio público `mcp.<domínio>` (TLS gerenciado). **Sem pre-deploy**: migrações rodam só na `api`. `restart: Always`; ≥ 2 réplicas quando estável (stateless).

## Variáveis

| Variável | Valor |
|---|---|
| `DATABASE_URL`, `REDIS_URL` | as mesmas da `api` |
| `MCP_RESOURCE_URL` | `https://mcp.<domínio>/mcp` (é o `aud` esperado) |
| `MCP_ISSUER_URL` | `https://<subdomínio>.authkit.app` |
| `MCP_JWKS_URL` | `<issuer>/oauth2/jwks` (confirmar no spike H3b) |
| `MCP_ALLOWED_HOSTS` | `mcp.<domínio>` (outro `Host` ⇒ 421) |
| `MCP_RATE_LIMIT_PER_MINUTE` | opcional, padrão 60 por usuário/chave |
| `MCP_STATIC_KEY_ENABLED` | `false`; `true` só para o Plano C (chave de API como Bearer) |

Não copie `OPENAI_API_KEY` (o MCP v1 não chama LLM). Sem cookie e sem CORS.

Para exibir a conexão na página **Desenvolvedor** (`/companies/{id}/developer`), configure
também `MCP_RESOURCE_URL`, `MCP_ISSUER_URL`, `MCP_JWKS_URL` e `MCP_STATIC_KEY_ENABLED`
no serviço `api`, com os mesmos valores do serviço `mcp`. O Docker Compose já compartilha
essas variáveis. `GET /organizations/{id}/mcp-info` exige Owner/Admin e retorna apenas
metadados de conexão públicos; não expõe JWKS, credenciais ou outras configurações.
O estado “configurado” indica presença das variáveis, não disponibilidade do serviço.
Sem configuração completa, a página informa isso e não gera exemplos com uma URL presumida.

## WorkOS Dashboard (pendente do dono)

Connect → CIMD habilitado; Resource Indicator = `MCP_RESOURCE_URL`; DCR habilitado; redirect URIs do Claude (`https://claude.ai/api/mcp/auth_callback`) e do loopback do Claude Code.

## Limites e observabilidade

- Timeout do proxy ≥ 60 s; resultado de tool ≤ 100.000 caracteres (`MAX_FETCH_CHARS`); tools só fazem SQL.
- Cada chamada gera uma linha em `api_audit_events` (`channel='mcp'`) sem conteúdo. Alerte sobre taxa de 401/403/429 e p95.
- O MCP **não** roda no plano gratuito da Render (adormece): use Railway ou Render pago.
- Habilitação: Owner/Admin liga `PUT /organizations/{id}/mcp-settings {"mcp_enabled": true}`; cada membro vincula sua organização com `PUT /organizations/{id}/mcp-connection`.
