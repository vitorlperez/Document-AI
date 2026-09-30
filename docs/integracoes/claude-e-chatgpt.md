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
