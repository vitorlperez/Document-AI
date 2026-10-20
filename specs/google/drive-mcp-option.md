# MCP é uma opção para conectar o Google Drive sem verificação/CASA?

Data: 2026-10-13 · Pesquisa somente leitura (sem código, prd ou commit) · Complementa [`drive-alternatives.md`](drive-alternatives.md) e [`drive-file-poc-result.md`](drive-file-poc-result.md).
Pergunta do dono: *"MCP é uma opção?"* e *"fiz um teste no ChatGPT e conectei meu Google Drive lá, como eles fazem?"*

## 0. Conclusão em 30 segundos

- **MCP (Model Context Protocol) é um protocolo de transporte** (como as IAs chamam ferramentas). Ele **não muda as regras do Google**: quem lê o Drive continua usando a API do Drive com OAuth e escopos. Quem controla escopo restrito + verificação + CASA é o **app OAuth que obtém o token**, não o formato da conversa entre IA e servidor.
- **Se o ArquivIO hospedar um servidor MCP de Drive para vários clientes, o app OAuth é do ArquivIO** → mesma verificação + CASA de hoje. Não há ganho.
- **ChatGPT e Claude fazem exatamente o caminho "app OAuth próprio + escopo de leitura do Drive"**. A diferença é que eles já têm a estrutura para isso; o ArquivIO teria de percorrer o mesmo caminho. **O token que o usuário deu ao ChatGPT/Claude pertence a esses apps e não pode ser reaproveitado pelo ArquivIO.**
- **Onde MCP ajuda de verdade:** (a) o ArquivIO **ser fonte** para ChatGPT/Claude (já existe, §5); (b) um cenário opcional "cliente roda o próprio MCP com o próprio projeto Google Cloud" (§4) para clientes que se importam muito com isso — viável, mas péssimo para B2B de massa.

## 1. Seção em destaque: "Conectei meu Drive no ChatGPT. Como eles fazem?"

**Resposta curta (leigo):** ChatGPT e Claude são, para o Google, "apps de terceiros" como qualquer outro. Quando você clicou em "Conectar Google Drive", abriu-se a tela de consentimento do Google **de um app da OpenAI (ou da Anthropic)**, pedindo permissão para **ler** seus arquivos. O token resultante é guardado por eles e usado só por eles. Não é um atalho especial: é o caminho normal (OAuth + escopo de leitura do Drive).

**O que as fontes oficiais confirmam**

| Ponto | ChatGPT (OpenAI) | Claude (Anthropic) |
|---|---|---|
| Como conecta | Conector "Google Drive" no ChatGPT; **cada usuário conecta a própria conta Google**; conexão pessoal dá **acesso ao vivo** (não cria índice pessoal); admin elegível de workspace pode configurar **sync gerenciado pelo admin**, que cria uma base indexada — [Google Drive app and setup in ChatGPT](https://help.openai.com/en/articles/10929079-google-drive-app-and-setup-in-chatgpt) *(via resumo de busca; a página retornou 403 no fetch direto)* | "Você precisa autenticar direto com sua conta Google"; Claude **"espelha suas permissões existentes"**; Team/Enterprise: Owner precisa habilitar os conectores antes — [Using the Google Drive integration](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration) |
| Escopos do Drive | Lista de escopos para o app Drive: `drive.readonly`, `drive.metadata.readonly`, `drive.activity.readonly` e o amplo `drive` (este permite criar/editar/compartilhar/mover/excluir) — conforme resumo da página da OpenAI em [ChatGPT Google Apps: Data Permissions, OAuth Scopes, and Admin Setup](https://knightli.com/en/2026/06/20/chatgpt-google-app-data-controls-oauth-scopes/) (**fonte de terceiro**; a página oficial [Google app data controls FAQ](https://help.openai.com/en/articles/10408842-google-app-data-controls-faq) retornou 403 ao fetch) | A página oficial **não lista os escopos**; só diz que a tela do Google menciona envio de e-mail e que Claude só envia/compartilha/move/exclui com aprovação por padrão — [Claude Help](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration) |
| Admin do cliente | Admin deve conferir no Admin console se o app ChatGPT/OpenAI é confiável ou se os escopos foram aprovados; sem isso o usuário vê erro de "aprovação do administrador" — [knightli](https://knightli.com/en/2026/06/20/chatgpt-google-app-data-controls-oauth-scopes/) (terceiro) | Se o Workspace bloquear, o admin precisa marcar Claude como app confiável em "API controls" — [Claude Help](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration) |
| Anexar arquivo vs conector | — (não confirmei na página oficial) | **Dois modos:** (1) **anexo no chat** via "+ → Add from Google Drive" (escolhe arquivo/cola URL; o documento é processado no chat); (2) **conector** (busca/age no Drive quando você pede); arquivos de Drive em Projetos ficam sincronizados — mesma [Claude Help](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration) |
| Conta Gmail pessoal | O sync de admin exige domínio Google Workspace (gmail.com/googlemail.com não); a conexão pessoal ao vivo é outra coisa — [Google Drive app and setup in ChatGPT](https://help.openai.com/en/articles/10929079-google-drive-app-and-setup-in-chatgpt) (via resumo de busca) | — |

**O que a tela de consentimento que você viu indica (inferência, sem ver sua tela):** o nome do app era o da OpenAI/ChatGPT, e os escopos pedidos eram de **leitura** do Drive (`drive.readonly` e afins). Se ela mostrou "ver e baixar todos os seus arquivos do Google Drive", é o texto do Google para `drive.readonly` — mesmo texto que a sua tela de consentimento mostraria hoje. Não consegui confirmar o nome exato do app nem a lista exata por documento oficial acessível.

**Eles usam `drive.file` + Picker?** Não encontrei evidência de que o conector use `drive.file`; os escopos listados acima são de leitura ampla. O modo "anexar arquivo" do Claude (Add from Google Drive) parece um seletor de arquivo; **não encontrei na documentação oficial** qual escopo ele usa por baixo (não afirmo que seja `drive.file`/Picker).

**O que eu NÃO consegui provar:** nenhum documento acessível da OpenAI ou da Anthropic diz explicitamente "passamos pela verificação do Google e pelo CASA". Isso é **consequência** das regras do Google (qualquer app público com escopo restrito que acesse dados via servidor de terceiros precisa de verificação + avaliação de segurança, renovada a cada 12 meses — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)), mas tratei como inferência. O estado exato de verificação/CASA deles não foi confirmado por fonte oficial.

**Por que isso importa para o ArquivIO:** o ArquivIO faria **exatamente o mesmo**: app OAuth próprio + `drive.readonly` + verificação + CASA anual. A única diferença é que OpenAI e Anthropic já passaram (ou pagam e mantêm) esse processo; o ArquivIO ainda não.

## 2. Servidores MCP de Google Drive existentes e como autenticam

| Servidor | Quem mantém | Auth | Observação |
|---|---|---|---|
| **Drive MCP oficial do Google** (`https://drivemcp.googleapis.com/mcp/v1`) | Google | **OAuth 2.0 com cliente OAuth do próprio desenvolvedor** (tipo Web application), escopos `drive.readonly` e `drive.file` na tela de consentimento; exige **Google Workspace Developer Preview Program** — [Configure the Drive MCP server](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server) | Redirect URI de exemplo para Claude: `https://claude.ai/api/mcp/auth_callback`. A página **não menciona verificação de escopo restrito** (só consentimento Internal/External e test users). Aberto em preview público desde 1º/05/2026, com "modelo de tiers" para controlar abuso/egresso — [Workspace Updates](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html) |
| Servidor de referência `modelcontextprotocol/servers` gdrive | Anthropic/comunidade | OAuth local com `drive.readonly` por padrão | **Arquivado** (sem manutenção nem correção de segurança) e com bug de refresh de token em fontes de terceiros — [Glama: servers-archived/gdrive](https://glama.ai/mcp/servers/@modelcontextprotocol/servers-archived/blob/9be4674d1ddf8c469e6461a27a337eeb65f76c2e/src/gdrive/README.md) |
| Comunidade (ex.: `taylorwilsdon/google_workspace_mcp`) | Terceiros | OAuth do próprio projeto Google Cloud do usuário | Auto-hospedado, pessoal; não resolve B2B multi-cliente |

**Todos usam OAuth com escopos do Drive** (leitura ampla ou `drive.file`). O servidor MCP só repassa chamadas à API do Google; a pergunta "esse app foi verificado?" continua sendo sobre quem registrou o cliente OAuth.

**O MCP oficial do Google muda algo para o ArquivIO?** Provavelmente não. A doc manda criar **seu próprio** cliente OAuth e declara `drive.readonly` — que é exatamente o escopo restrito que hoje exige verificação/CASA para app público. A doc não afirma isenção. O fato de a página omitir "verificação" **não** significa dispensa; as regras gerais valem. *(Inferência minha: não vi texto oficial que isente ou exija.)*

## 3. Cenário "o cliente traz o próprio conector" (Claude/ChatGPT)

Em geral **não dá para o ArquivIO aproveitar**:

- O token OAuth é emitido **para o app da OpenAI/Anthropic** e fica guardado no servidor deles. Um terceiro (ArquivIO) não recebe esse token, e o MCP proíbe o servidor de repassar tokens: *"O servidor MCP NÃO DEVE repassar o token que recebeu do cliente MCP"* e tokens têm de ter o servidor como audiência — [MCP Authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) (seções "Token Audience Binding" e "Access Token Privilege Restriction").
- O que o usuário pode fazer é ficar na direção oposta: **a IA do cliente consulta o ArquivIO** (§5) ou **a IA do cliente lê o Drive e o usuário cola/anexa o resultado**. Isso não alimenta o índice do ArquivIO nem acompanha arquivos novos.
- Um conector de IA só acessa o Drive **quando o usuário pergunta** ([Claude Help](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration)), o oposto de um indexador contínuo.

## 4. Cenário "cliente roda MCP local com o PRÓPRIO projeto Google Cloud"

**Viabilidade técnica:** sim. O cliente cria um projeto Google Cloud próprio, registra um cliente OAuth (uso interno/pessoal/dev-test são isentos de verificação — [Restricted scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification), conforme [`drive-alternatives.md`](drive-alternatives.md) §1) e o ArquivIO conversa com esse MCP/agente.

**Mas, para B2B:**
| Aspecto | Avaliação |
|---|---|
| UX | **Ruim** para clientes não técnicos: criar projeto Cloud, ativar API, tela de consentimento, instalar/hospedar o servidor, manter chaves. Ok só para cliente técnico ou enterprise com TI. |
| Segurança | O token fica no ambiente do cliente (bom). Mas o ArquivIO precisa alcançar o MCP do cliente (túnel/porta aberta/agente de saída) — nova superfície de ataque e suporte. |
| Isenção | Vale **para o projeto do cliente** (uso interno dele), não para o ArquivIO — mas "uso interno" fala de apps usados por pessoas da própria organização; um terceiro consumindo os dados via servidor próprio pode ser lido como zona cinzenta (inferência). |
| Esforço de produto | Agente/CLI instalável, instruções, atualizações, suporte a 3 sistemas: **semanas** (já listado como "agente desktop" em [`drive-alternatives.md`](drive-alternatives.md) §6). |
| Quando faz sentido | Segundo modo opcional para cliente enterprise que **proíbe** apps de terceiros no Drive dele. |

## 5. O ArquivIO já expõe MCP — como fonte para IAs

**Fato (verificado no repo):** existe um servidor MCP próprio, **somente leitura**, em Streamable HTTP, que expõe as informações **já indexadas no ArquivIO** — não o Drive.

| Local | O que é |
|---|---|
| `backend/app/mcp_server/server.py:28-45` | `build_server`: tools `search`, `fetch`, `list_sources` (todas `READ_ONLY`) |
| `backend/app/mcp_server/asgi.py:1,38-102` | ASGI Starlette; "resource server only"; `McpAuthMiddleware` valida Bearer, resolve principal por requisição, aplica rate limit (falha fechado) e auditoria; bloqueia se `mcp_enabled` da org for falso |
| `backend/app/core/config.py:126-131` | `mcp_resource_url`, `mcp_issuer_url` (AuthKit/WorkOS), `mcp_jwks_url`, `mcp_allowed_hosts`, `mcp_rate_limit_per_minute`, `mcp_static_key_enabled` (plano C: chave de API da org como Bearer) |
| `frontend/app/developer-mcp-config.ts:2-9` | Exemplos de configuração para Cursor e Claude Code (`claude mcp add --transport http arquivio <url>`) |
| `backend/app/main.py:32,183` | Router `mcp_admin_router` (admin do MCP por organização) |

O MCP do ArquivIO **autentica no ArquivIO** (OAuth via AuthKit; o MCP exige tokens com audiência própria), **não** pede escopo nenhum ao Google. É exatamente o uso certo do protocolo: ArquivIO como **fonte** para Claude/ChatGPT/Cursor. Para o Google Drive, quem tem de ter escopo continua sendo o conector de ingestão (`backend/app/integrations/google_drive.py`).

## 6. Quando MCP poderia ajudar (e quando não)

| Situação | MCP ajuda? |
|---|---|
| Evitar verificação/CASA com MCP hospedado pelo ArquivIO | **Não** — o app OAuth é do ArquivIO, escopo restrito igual |
| Usar o MCP oficial do Google no lugar do nosso conector | **Não** — exige cliente OAuth próprio + `drive.readonly`; preview; mesma regra do Google |
| Aproveitar conector do Claude/ChatGPT do cliente | **Não** — token pertence ao app deles; MCP proíbe repasse |
| Cliente com TI forte roda MCP próprio e o ArquivIO consome | **Sim, como modo opcional enterprise** (esforço grande, ver §4) |
| ArquivIO ser fonte para IAs de qualquer cliente | **Sim, e já existe** (§5) |
| Dar ao cliente uma saída "sem Google" | Não é MCP; veja upload direto/e-mail/agente em [`drive-alternatives.md`](drive-alternatives.md) §6 |

**Recomendação:** MCP não substitui os caminhos de `drive-alternatives.md` (cotar CASA; PoC de service account; upload direto). Tratar MCP como **canal de saída** (ArquivIO → IAs), o que já está pronto, e como curiosidade de um modo "cliente traz o próprio MCP" só se algum cliente enterprise exigir.

## 7. Não coberto / limites

- Não consegui abrir as páginas da OpenAI (`help.openai.com` retornou 403 ao fetch); as informações do ChatGPT vêm de resumos de busca e do artigo [knightli](https://knightli.com/en/2026/06/20/chatgpt-google-app-data-controls-oauth-scopes/) (terceiro) — a lista de escopos do ChatGPT deve ser conferida na página oficial.
- Não confirmei o **status de verificação/CASA** de OpenAI nem Anthropic por fonte oficial; é inferência das regras do Google.
- Não confirmei o escopo usado pelo modo "Add from Google Drive" do Claude nem se algum deles usa Picker/`drive.file`.
- Não testei o Drive MCP oficial do Google; está em preview e a doc pode mudar.
- Não alterei código nem fiz commit.

## Fontes

- [Configure the Drive MCP server (Google)](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server)
- [Configure the Google Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Updates: agent tools and security updates (Google)](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html)
- [Restricted scope verification (Google)](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [MCP Authorization spec (modelcontextprotocol.io)](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [Using the Google Drive integration (Claude Help)](https://support.claude.com/en/articles/10166901-using-the-google-drive-integration)
- [Building custom connectors via remote MCP servers (Anthropic)](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers)
- [Google Drive app and setup in ChatGPT (OpenAI Help)](https://help.openai.com/en/articles/10929079-google-drive-app-and-setup-in-chatgpt)
- [Google app data controls FAQ (OpenAI Help)](https://help.openai.com/en/articles/10408842-google-app-data-controls-faq)
- [Glama: gdrive reference server (archived)](https://glama.ai/mcp/servers/@modelcontextprotocol/servers-archived/blob/9be4674d1ddf8c469e6461a27a337eeb65f76c2e/src/gdrive/README.md) (terceiro)
- [knightli: ChatGPT Google Apps scopes](https://knightli.com/en/2026/06/20/chatgpt-google-app-data-controls-oauth-scopes/) (terceiro)
