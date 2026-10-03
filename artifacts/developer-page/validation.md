# Página Desenvolvedor — validação

Implementado em `/companies/[companyId]/developer`, no menu desktop e no drawer mobile.
Acesso para Owner/Admin, igual ao acesso anterior da seção de API. Membros recebem
“Acesso restrito”; a página não carrega chaves nem metadados MCP para eles.
Trocar organização mantém a rota `/developer`.

## API movida

`AccessSettings` saiu de Integrações e é reutilizado sem alterações na nova página.
Inclui habilitação da API pública, lista/prefixos/escopos/último uso/expiração,
criação com escopos e seleção de pastas/arquivos, chave exibida uma vez e revogação.
Não havia documentação ou exemplos adicionais no painel anterior.
As alterações preexistentes em `access-settings.tsx` foram preservadas.

## MCP real

Já existe servidor em `backend/app/mcp_server/asgi.py`, executado separadamente do
FastAPI, com transporte Streamable HTTP e autenticação OAuth/WorkOS. Ferramentas:
`search`, `fetch`, `list_sources` (somente leitura). O caminho vem de
`MCP_RESOURCE_URL`, com fallback interno `/mcp`; a página nunca presume esse URL.
Chaves de API são aceitas somente quando `MCP_STATIC_KEY_ENABLED` é verdadeiro.

O novo `GET /organizations/{id}/mcp-info` exige Owner/Admin e usa a configuração
runtime da API, retornando URL do recurso, emissor OAuth, transporte, aceitação
opcional de chaves e nomes das ferramentas. Não retorna JWKS nem credenciais.
O estado configurado confirma presença das variáveis, não saúde/deploy do servidor.

A página exibe explicação de autenticação, ferramentas, habilitação MCP e vínculo
pessoal (com confirmação de troca de organização e escopo completo), além de
exemplos para Claude Code/Cursor e instruções para Claude Desktop quando configurado.
Sem configuração completa, informa isso honestamente e omite exemplos de conexão.
A inspeção local com `Settings` confirmou que URL/emissor/JWKS não estão definidos
neste ambiente e o modo chave está desligado. Não foi feita conexão a MCP publicado.
As variáveis agora são compartilhadas com a API no Docker Compose; em deploys
separados devem ter os mesmos valores nos serviços `api` e `mcp` (documentado).

Referências oficiais dos clientes consultadas:
- https://code.claude.com/docs/en/mcp
- https://cursor.com/docs/mcp
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

## Arquivos desta entrega

- `frontend/app/companies/[companyId]/developer/page.tsx` (novo)
- `frontend/app/product/developer-screen.tsx` (novo)
- `frontend/app/developer-mcp-config.ts` (novo)
- `frontend/app/product-app.tsx` (alteração pontual sobre mudanças preexistentes)
- `frontend/app/product/types-and-api.tsx` (adiciona Screen)
- `frontend/app/product/shell.tsx` (menu e classificação da tela)
- `frontend/app/mobile-nav.tsx` (item do drawer; arquivo preexistente não versionado)
- `frontend/tests/developer-mcp-config.test.mjs` (novo)
- `backend/app/api/mcp_admin.py` (metadados públicos autenticados)
- `backend/tests/api/test_developer_mcp_info.py` (novo)
- `docker-compose.yml` (variáveis MCP compartilhadas com API)
- `docs/deployment/mcp-server.md` (orientação da configuração)
- `artifacts/developer-page/visual-check.cjs`, `visual-results.json`, screenshots e este registro
- `graphify-out/graph.json`, `graph.html`, `GRAPH_REPORT.md`, `manifest.json`, `.graphify_labels.json`, `.graphify_labels.json.sig` (atualização gerada; já estavam dirty)

Nenhum commit, staging, reset ou reversão de arquivos alheios foi realizado.
Diffs dos arquivos compartilhados foram comparados com cópias capturadas no início.

## Verificações finais

Executadas nesta sessão, sem falhas finais:

| Diretório | Comando | Exit | Resultado |
|---|---|---:|---|
| raiz | `graphify query "Onde ficam a seção de API em Integrações e a navegação das páginas do produto?"` | 0 | Localizou AccessSettings antes da busca de código |
| frontend | `npx tsc --noEmit` | 0 | Sem erros |
| frontend | `npm run lint` | 0 | Sem erros ou avisos de lint |
| frontend | `npm run build` | 0 | Build vinext completo; rota developer listada |
| frontend | `node --import /tmp/document-ai-onboarding-tools/node_modules/tsx/dist/loader.mjs --test --test-reporter=spec tests/*.test.mjs` | 0 | 73/73 testes, 0 falhas |
| backend | `.venv/bin/ruff check app/api/mcp_admin.py tests/api/test_developer_mcp_info.py` | 0 | All checks passed |
| backend | `.venv/bin/pytest tests/api/test_developer_mcp_info.py tests/api/test_access_admin.py tests/api/test_mcp_connection.py tests/api/test_mcp_server.py tests/unit/test_mcp_auth.py tests/unit/test_mcp_tools.py -q` | 0 | 69 passed; 1 warning de depreciação Starlette/AnyIO |
| raiz | `docker compose config --quiet` | 0 | Configuração válida |
| raiz | `NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/developer-page/visual-check.cjs` | 0 | 5/5 cenários desktop/mobile |
| raiz | `graphify update .` | 0 | 6317 nós, 18917 arestas, 370 comunidades; AST sem LLM |
| raiz | `git diff --check` | 0 | Sem erros de whitespace |

Testes novos começaram vermelhos: backend (4 falhas/404, exit 1) e exemplos frontend
(módulo ainda inexistente, exit 1); ambos passaram após implementação.
O comando frontend sem loader (`node --test tests/*.test.mjs`) teve exit 1 por TSX
na suíte existente; o comando correto com loader passou 73/73. Falhas intermediárias
de lint/ruff foram corrigidas. A primeira tentativa visual usava `.check()` em
checkbox controlado com atualização assíncrona e procurava o título antigo de
Integrações; o script foi corrigido com espera por estado e título real do catálogo.

## Validação visual

Dev server iniciado por `npm run dev -- --port 5183`. Chrome headless/Playwright
com respostas HTTP simuladas: Owner e Admin, desktop 1440px/mobile 390px,
MCP configurado/não configurado e Member desktop/mobile. Incluiu:
criar/revogar chave, habilitar API, habilitar MCP, vincular/desvincular conta,
URL com caminho personalizado, navegação e troca de organização na rota developer,
remoção da seção de API de Integrações, nenhum erro JS ou overflow horizontal da página.
Capturas desktop/mobile e estado não configurado foram inspecionadas visualmente.
Não houve validação de OAuth/cliente MCP contra ambiente publicado.

Screenshots (fixtures, sem dados reais):
- `artifacts/developer-page/desktop-configured.png`
- `artifacts/developer-page/mobile-configured.png`
- `artifacts/developer-page/desktop-unconfigured.png`
- `artifacts/developer-page/desktop-member.png`
- `artifacts/developer-page/mobile-member.png`
- `artifacts/developer-page/desktop-configured-integrations.png`
- `artifacts/developer-page/mobile-configured-integrations.png`
- `artifacts/developer-page/desktop-unconfigured-integrations.png`

skills: inline [oc-builder, oc-stamp]
