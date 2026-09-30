# Spike B0 — AuthKit como servidor de autorização do MCP

Status: **parcial**. O que dependia só de código foi verificado; o go/no-go real do AuthKit **depende do dono** (credenciais WorkOS reais e clientes Claude/ChatGPT) e está registrado como pendência.

## Verificado sem credenciais (2026-09-30)

| Hipótese | Resultado | Evidência |
|---|---|---|
| H1 — SDK/spec | `mcp==2.2.0` (Python 3.12), `from mcp.server import MCPServer` (não `FastMCP`). `streamable_http_app(stateless_http=True, json_response=True, transport_security=…)`. Fixado em `pyproject.toml` como `mcp>=2.2,<3`. Cabeçalho `MCP-Protocol-Version: 2025-11-25` aceito. | `tests/api/test_mcp_server.py` (16 testes) |
| H2 — Stateless | `tools/list` e `tools/call` funcionam sem sessão (`Mcp-Session-Id` não é usado). Nenhum estado no processo ⇒ réplicas atrás de round-robin. Rate limit é Redis (`RedisRateLimiter`). | idem; teste com o Inspector e 2 réplicas continua pendente |
| Anotações | 3 tools com `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false`. | `test_only_three_read_only_tools_are_listed` |
| Formato de resultado | `structuredContent` e `content[0].text` (JSON) idênticos. | `test_search_result_is_structured_content_and_json_text` |
| Validação de token | RS256 apenas; `aud`, `iss`, `exp`, `sub` obrigatórios; HS256/`none` rejeitados; falha de JWKS = 401. Token nunca é repassado. | `tests/unit/test_mcp_auth.py` (15 testes, JWKS local) |

Desvio do plano: a autenticação roda em um middleware ASGI próprio (`McpAuthMiddleware`), não em `AuthSettings`/`TokenVerifier` do SDK. Motivo: resolver o `Principal` e aplicar o rate limit **a cada requisição** (revogação vale na chamada seguinte) e devolver `WWW-Authenticate: Bearer resource_metadata=…` de forma controlada. O PRM é servido manualmente em `/.well-known/oauth-protected-resource/mcp`.

## Pendente do dono (não foi possível sem credenciais)

- [ ] **H3** — Habilitar no Dashboard WorkOS: CIMD, Resource Indicators (recurso = `MCP_RESOURCE_URL`, `aud` = essa URL) e DCR. Obter um token real e registrar `iss`, `aud`, `sub`, `exp`, `scope`. **Confirmar `sub` == `AuthIdentity.provider_subject`** (`identity/auth.py`). Se não coincidir, o `McpPrincipalResolver` precisa de tabela de vínculo (só `resolve()` muda) ou vai-se ao Plano B.
- [ ] **H3b** — Confirmar a URL do JWKS (`<issuer>/oauth2/jwks`) para `MCP_JWKS_URL`.
- [ ] **H4** — Confirmar que o token não carrega a `Organization`; o vínculo `mcp_connections` (uma organização ativa por usuário) é o mecanismo suficiente. Verificar o login AuthKit para usuário com sessão no app.
- [ ] **H5** — "Hello world"/servidor real conectado ao Claude (custom connector, callback `https://claude.ai/api/mcp/auth_callback`) e ao ChatGPT (developer mode). Anotar `tools/list`, `structuredContent` e refresh de token.
- [ ] **H6** — Confirmar se o ChatGPT tolera o campo extra `text` em `search`. Se não: remover `text` em `tools.run_search` (uma linha; `test_search_matches_the_chatgpt_shape` já checa só `id/title/url`).

## Decisão

**GO condicional** para a arquitetura (servidor + verificação atrás de interface, testado com JWKS local). O **go/no-go do AuthKit real fica pendente** (H3–H6). Ordem de fallback:

1. **Plano C — já funcional:** `MCP_STATIC_KEY_ENABLED=true` faz o endpoint aceitar uma chave de API da organização (`arq_…`, Fase A) como Bearer. Serve o Claude (credencial estática) e o Claude Code; **não** serve ao ChatGPT. Desligado por padrão (falha fechada); a chave respeita escopos, restrição de pasta, revogação e `public_api_enabled`.
2. **Plano B (AS próprio, +5–8 d)** só se H3/H4 falharem de forma irreparável. A interface `AuthKitTokenVerifier`/`McpPrincipalResolver` isola a mudança.
