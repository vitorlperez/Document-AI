# Teste local do login Arquivio — 08/10/2026

> Configuração atualizada depois desta evidência: o Docker local agora usa somente `http://localhost:3000` para interface e API via `/api`. O callback atual é `http://localhost:3000/api/auth/callback`; a porta 8000 permanece interna. As instruções de callback direto abaixo descrevem o teste anterior. Consulte [a configuração e validação atuais](../local-single-origin-20261008/LEIA-ME.md), inclusive o callback a cadastrar no WorkOS Staging.

## Resultado efetivo

O alvo é http://localhost:3000/login. Aberto no browser Overclock, pane-496, HTTP 200 e título Arquivio. A porta 3117 não foi usada nesta validação.

Executado neste workspace usando o projeto Compose existente `document-ai`:

```sh
docker compose build api frontend
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 60 api frontend
```

Ambos terminaram com exit 0. Somente API e frontend foram recriados. Os IDs e horários de início de Postgres, Redis, worker e Beat permanecem iguais; os volumes de Postgres/Redis também. Banco antes/depois: migração `20261001_0027`, 4 usuários, 503 documentos, 4 organizações. Nenhuma migração foi executada, pois este login não adiciona migração.

Nenhum código de produto, `.env`, credencial ou configuração Compose foi editado. WorkOS API key e client ID estão presentes e coincidem com a configuração anterior. Ambiente identificado como **Staging** pelo prefixo da API key, sem registrar seus valores. Isso não comprova a validade remota das credenciais nem consulta o Dashboard.

Configuração local efetiva preservada:

```text
ENVIRONMENT=development
PUBLIC_APP_URL=http://localhost:3000
WORKOS_REDIRECT_URI=http://localhost:8000/auth/callback
Frontend: API direta http://localhost:8000 (padrão existente)
```

## Evidências

- `before.json` / `after.json`: IDs, imagens, volumes e contagens agregadas antes/depois; dados pessoais não foram exportados.
- `api-runtime.json`: `/auth/password` presente, ambiente e URLs locais, presença de credenciais sem valores. SDK WorkOS efetivo na imagem: 10.5.0, permitido pelo requisito `>=10.3,<11`.
- `browser-smoke.json`: 3/3 tamanhos passaram (1440×900, 390×844, 320×740). HTTP 200, URL mantida em `/login`, formulário Arquivio e senha presentes, sem requisições externas, erros JavaScript, alertas de sessão ou overflow horizontal. Formulários de cadastro e recuperação abertos sem submit.
- `login-1440.png`, `login-390.png`, `login-320.png`: capturas do alvo real.
- Conexão real do browser com a API, incluindo CORS e credentials: `/me` retornou 401 para sessão anônima; `/health/ready` retornou 200/ready; `POST /auth/password` com `{}` retornou 422 genérico. A validação de corpo interrompe a execução antes da chamada WorkOS.
- `logs-summary.json`, `api-logs.txt`, `frontend-logs.txt`: logs locais sem ERROR/FATAL/Traceback; contador reportado de chamadas de provedor = 0. Arquivos sanitizados.
- Testes frontend de navegação/configuração: 3/3 passaram, exit 0.
- Testes SDK/proxy na venv local 10.3: 34/34 passaram, exit 0.
- `sdk-image-tests.txt`: 34/34 passaram na imagem reconstruída com SDK 10.5, em container temporário `--network none`, sem credenciais reais. A primeira execução da suíte original nessa imagem teve 21 falhas porque a fixture acessa o atributo privado `_client`, removido no SDK 10.5. A cópia operacional `test_sdk_image.py` usa o argumento público `http_client`; todas as asserções originais foram preservadas. Os arquivos de teste de produto não foram alterados. Essa cópia permite validar os contratos da versão instalada, sem afirmar que a fixture original já suporta 10.5.

## Conferir o WorkOS Dashboard antes do teste humano

O estado remoto destas opções **não foi consultado nem alterado**. Com papel Admin, selecione **Staging** e a aplicação correspondente ao `WORKOS_CLIENT_ID` já configurado (compare dentro do Dashboard/arquivo local; não compartilhe a chave).

1. **Applications → aplicação → Redirects → Redirect URIs**: adicione/confirme `http://localhost:8000/auth/callback`, preservando outros callbacks. É o callback do modo direto atual; não use `/api/auth/callback` no local atual.
2. Na mesma aba, **Password reset URL**: `http://localhost:3000/login`. O WorkOS acrescenta o token ao link.
3. **Authentication → Email + Password**: habilitado. Confira a política de senha e a exigência de verificação de e-mail em Authentication.
4. **Emails → Configuration → Manage**: mantenha ligados os e-mails gerenciados de **Password reset** e **Email verification**. Este app não implementa envio alternativo quando essas opções estão desligadas.

Referências oficiais conferidas: [URLs e e-mails](https://workos.com/docs/authkit/custom-emails), [Email + Password](https://workos.com/docs/authkit/email-password), [ambientes separados](https://workos.com/docs/authkit/environments).

## Como testar localmente com sua própria caixa

1. Abra http://localhost:3000/login em janela anônima e use apenas uma conta/caixa que você controla e designa para o teste.
2. Clique **Criar conta**, informe seu e-mail e clique **Criar minha conta**. O cadastro pede somente e-mail; a senha é definida depois de provar posse da caixa.
3. Abra o link recebido no mesmo computador onde localhost funciona, escolha uma senha que atenda à política WorkOS e clique **Salvar nova senha**. A mensagem de solicitação aceita não comprova entrega: confira também spam.
4. Entre com e-mail e senha. Se pedir confirmação, digite o código recebido. SSO/MFA ou desafios adicionais podem abrir o AuthKit hospedado via **Continuar com SSO ou outro método**.
5. Se já tem conta sem senha, ou quer recuperar acesso, use **Esqueceu a senha?**, receba o link, salve a nova senha e entre novamente. Reset bem-sucedido encerra as sessões anteriores; não entra automaticamente.
6. Para convite aberto em outro dispositivo/navegador, reabra o convite original depois de definir a senha.

Não executei cadastro, login válido, reset válido, SSO/MFA ou envio/entrega real de e-mail. Esses passos dependem da conta designada e da configuração remota acima.

## Posteriormente na produção

Nenhum deploy, commit, mudança pública ou operação em produção foi feito nesta tarefa. Após autorizar/publicar as versões novas, use o ambiente WorkOS **Production** e a origem HTTPS real do app. Usuários/credenciais Staging e Production são separados.

| Configuração futura | Valor |
| --- | --- |
| API `PUBLIC_APP_URL` | `https://<origem-real-do-app>` |
| API `WORKOS_REDIRECT_URI` | `https://<origem-real-do-app>/api/auth/callback` |
| Frontend `VITE_API_BASE_URL` | `/api` (novo build necessário) |
| Frontend `API_UPSTREAM_URL` | Endereço real da API acessível ao frontend |
| WorkOS Production → Applications → aplicação → Redirects → Redirect URI | `https://<origem-real-do-app>/api/auth/callback` |
| Na mesma aba → Password reset URL | `https://<origem-real-do-app>/login` |

Configure as chaves Production em segredo, e-mail/senha/verificação e os e-mails gerenciados nesse ambiente. O proxy de produção exige `ENVIRONMENT=production`, `AUTH_CLIENT_IP_SOURCE=railway` no frontend, `AUTH_PROXY_SECRET` compartilhado com os processos que carregam Settings e `AUTH_TRUSTED_PROXY_CIDRS` delimitados na API. Preserve `--no-proxy-headers` no Uvicorn. Os detalhes e a validação do ingress estão em `docs/deployment/railway-production.md` e `backend/docs/custom-workos-login.md`.

Quando a produção estiver preparada, abra sua URL HTTPS + `/login` e repita os passos de cadastro → link → definir senha → entrar → recuperar, com uma caixa designada para Production. A validação feita aqui cobre o Docker local, não comprova runtime/ingress nem entrega de e-mail em produção.

Skills: inline [oc-builder, oc-blackbox, oc-stamp]. Consulta graphify realizada antes da leitura do código.
