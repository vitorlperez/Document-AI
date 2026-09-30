# Conecte o Arquivio ao Claude e ao ChatGPT

O Arquivio expõe um servidor MCP **somente leitura** (`search`, `fetch`, `list_sources`). Ele nunca escreve, apaga nem envia dados a terceiros: o texto dos documentos só sai para o cliente que você conectou.

## Para o Owner/Admin

1. Ative o acesso MCP da organização (`mcp_enabled`).
2. Peça aos membros que vinculem a própria conta à organização (um vínculo ativo por pessoa; vincular a outra organização revoga o anterior).

## Para o usuário

- **Claude (web/desktop):** Configurações → Conectores → *Adicionar conector personalizado* → URL `https://mcp.<domínio>/mcp` → conclua o login (OAuth). Pergunte, por exemplo, "o que diz o contrato do cliente X sobre prazo?": o Claude usa `search` e `fetch` e cita o link do documento.
- **Claude Code:** `claude mcp add --transport http arquivio https://mcp.<domínio>/mcp` e autentique.
- **ChatGPT:** modo desenvolvedor → conectar o mesmo URL → a mesma pergunta; a citação é clicável quando o documento tem URL.
- **Alternativa (Plano C):** se o Owner habilitar `MCP_STATIC_KEY_ENABLED`, uma chave de API da organização pode ser usada como credencial estática (não serve ao ChatGPT).

## Testar sem domínio próprio (túnel ngrok)

O Claude e o ChatGPT chamam o MCP a partir da nuvem deles, então precisam de uma URL HTTPS pública. Com um domínio estático do ngrok (`<nome>.ngrok-free.app`):

1. Defina no `.env` (o host é o do túnel; issuer e JWKS continuam os do AuthKit, não mudam com o túnel):
   ```
   MCP_RESOURCE_URL=https://<nome>.ngrok-free.app/mcp
   MCP_ALLOWED_HOSTS=<nome>.ngrok-free.app
   MCP_ISSUER_URL=https://<subdomínio>.authkit.app
   MCP_JWKS_URL=<issuer>/oauth2/jwks
   ```
   Se `MCP_ALLOWED_HOSTS` ficar vazio, o host é derivado de `MCP_RESOURCE_URL`; outro `Host` recebe 421.
2. Suba o serviço `mcp` (perfil opt-in do `docker-compose.yml`, `uvicorn app.mcp_server.asgi:app --port 8001`): `docker compose --profile mcp up mcp`.
3. Abra o túnel: `ngrok http --url=<nome>.ngrok-free.app 8001`.
4. No WorkOS, registre o Resource Indicator igual a `MCP_RESOURCE_URL`. O redirect do login do app (`WORKOS_REDIRECT_URI`) não muda; o que o WorkOS aceita no fluxo MCP são os redirects dos clientes (`https://claude.ai/api/mcp/auth_callback`, loopback do Claude Code, CIMD do ChatGPT).
5. Conecte o cliente em `https://<nome>.ngrok-free.app/mcp` e confira com o MCP Inspector antes.

O usuário precisa estar vinculado (`PUT /organizations/{id}/mcp-connection`) e o Owner precisa ter ativado `mcp_enabled`. Não use o túnel em produção.

## Privacidade e revogação

- Cada chamada exige um token OAuth cujo destinatário (`aud`) é este servidor; tokens de outro serviço são recusados (401).
- Você só enxerga documentos da organização vinculada (e das pastas permitidas, se houver restrição).
- Toda chamada é auditada sem conteúdo (apenas contagem, tamanho e hash da consulta).
- Revogar: `DELETE /organizations/{id}/mcp-connection` ou o Owner desativa o MCP; vale na chamada seguinte, sem esperar o token expirar.

## Checklist de conformidade (pendente do dono — precisa de WorkOS e clientes reais)

- [ ] MCP Inspector: `tools/list` (3 tools, anotações) e `tools/call`.
- [ ] Claude: conectar, OAuth, pergunta com citação do link do Drive.
- [ ] Claude Code autenticado.
- [ ] ChatGPT (modo desenvolvedor): conectar e citar.
- [ ] Usuário da organização B no mesmo cliente não vê dados da A.
- [ ] Revogar o vínculo: a próxima chamada falha.
