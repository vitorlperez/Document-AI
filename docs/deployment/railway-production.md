# Preparar a produção na Railway

Este guia prepara o Arquivio para a Railway sem usar o `docker-compose.yml` de desenvolvimento. O projeto Railway contém cinco serviços no mesmo ambiente e região: `frontend`, `api`, `worker`, `Postgres` e `Redis`. Somente `frontend` e `api` recebem domínios públicos (o serviço opcional `mcp`, um 6º serviço com domínio próprio, está em `docs/deployment/mcp-server.md`). PostgreSQL e Redis da Railway são serviços em containers com volumes; habilite e teste os backups antes de armazenar dados de clientes.

## 1. Definir os valores de produção

Antes de criar recursos pagos, escolha a região dos dados, os endereços públicos, o orçamento mensal e a política de retenção dos backups. Os endereços gerados pelo Railway podem ser usados para o primeiro deploy; o frontend faz proxy das requisições em `/api`, mantendo o cookie de sessão no host do frontend. Se comprar um domínio próprio, use `app.seudominio.com` e, caso a API continue pública, `api.seudominio.com`. Separe um ambiente de homologação com banco, Redis, domínio e credenciais próprios; não copie tokens OAuth ou dados reais para ele.

## 2. Criar o projeto e os serviços

1. Crie um projeto Railway e um ambiente de homologação. Selecione a mesma região para os cinco serviços. Desative o autodeploy da branch de produção até concluir esta lista.
2. Adicione `Postgres` e `Redis` pelo menu **New > Database**. Não habilite Public Access/TCP Proxy para eles. Se já houver dados a migrar, planeje um dump e uma janela de corte antes de usar o novo banco.
3. Crie três serviços a partir deste repositório Git. Configure-os em **Settings > Source/Build/Deploy** desta forma:

   - `api`: Root Directory `/backend`; builder Dockerfile (`Dockerfile`); pre-deploy command `alembic upgrade head`; start command `/bin/sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers'`; healthcheck path `/health/ready` com timeout de 300 s; restart policy **Always**.
   - `worker`: Root Directory `/backend`; builder Dockerfile (`Dockerfile`); start command `celery -A app.ingestion.tasks worker --loglevel=INFO --concurrency=1`; restart policy **Always**; sem pre-deploy command e sem domínio público.
   - `frontend`: Root Directory `/frontend`; builder Dockerfile com `RAILWAY_DOCKERFILE_PATH=Dockerfile.production` em Variables; comando de início padrão da imagem; healthcheck path `/` com timeout de 300 s; restart policy **Always**.

   Os dois serviços Python usam `backend/Dockerfile`. O frontend usa `frontend/Dockerfile.production`; `frontend/Dockerfile` inicia o servidor de desenvolvimento e não serve para produção. A migração `alembic upgrade head` roda apenas no **pre-deploy da API**. Mantenha uma réplica da API e uma do worker no primeiro deploy. Antes de aumentar réplicas da API, planeje migrações compatíveis com versões antigas e novas em execução durante o deploy.

4. Configure as variáveis abaixo em **Variables**, de preferência com referências a serviços e variáveis compartilhadas. O nome `Postgres` ou `Redis` na expressão deve corresponder exatamente ao nome do serviço criado. Confira cada ajuste no resumo de alterações antes de clicar **Deploy**.

Os antigos arquivos Railway Config as Code (`railway.json`/`railway.toml`) não são apropriados para serviços novos: a Railway os descontinuou e recomenda [Infrastructure as Code](https://docs.railway.com/infrastructure-as-code). Depois de criar e validar o projeto, use `railway config pull` para gerar `.railway/railway.ts` a partir da configuração efetiva; revise com `railway config plan` antes de passar a gerenciá-la como código. Não use `--include-variables`, pois isso pode gravar segredos no repositório.

## 3. Variáveis da API e do worker

Em ambos, configure:

```text
ENVIRONMENT=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
PUBLIC_APP_URL=https://app.seudominio.com
AUTH_PROXY_SECRET=<segredo aleatório compartilhado com o frontend e processos que carregam Settings>
AUTH_TRUSTED_PROXY_CIDRS=<CIDRs delimitados dos peers do frontend>
OPENAI_API_KEY=<segredo>
TYPESAFE_API_KEY=<segredo; só a API usa, o worker ignora>
GOOGLE_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
MICROSOFT_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
NOTION_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
CLICKUP_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
GOOGLE_OAUTH_CLIENT_ID=<client id>
GOOGLE_OAUTH_CLIENT_SECRET=<segredo>
GOOGLE_OAUTH_REDIRECT_URI=https://app.seudominio.com/api/data-sources/google/oauth/callback
MICROSOFT_OAUTH_CLIENT_ID=<client id>
MICROSOFT_OAUTH_CLIENT_SECRET=<segredo>
MICROSOFT_OAUTH_REDIRECT_URI=https://app.seudominio.com/api/data-sources/onedrive/oauth/callback
MICROSOFT_SHAREPOINT_REDIRECT_URI=https://app.seudominio.com/api/data-sources/sharepoint/oauth/callback
# Opcionais do SharePoint (padrões): SHAREPOINT_DOWNLOAD_WORKERS=2, SHAREPOINT_MAX_FILE_BYTES=52428800, SHAREPOINT_CATALOG_MAX_SITES=200
NOTION_OAUTH_CLIENT_ID=<client id>
NOTION_OAUTH_CLIENT_SECRET=<segredo>
NOTION_OAUTH_REDIRECT_URI=https://app.seudominio.com/api/data-sources/notion/oauth/callback
ACTIVE_DOCUMENT_LIMIT=3000   # API e Worker; padrão do código é 3000 (ver docs/integracoes/clickup-runbook.md §2); omita para usar o padrão
CLICKUP_OAUTH_CLIENT_ID=<client id>
CLICKUP_OAUTH_CLIENT_SECRET=<segredo>
CLICKUP_OAUTH_REDIRECT_URI=https://app.seudominio.com/api/data-sources/clickup/oauth/callback
# Opcional do ClickUp (padrão false): CLICKUP_INCLUDE_CLOSED_TASKS=true indexa também tarefas fechadas
# opcional: API_DOCS_ENABLED=true reabre /docs, /redoc e /openapi.json (todas as rotas, inclusive privadas); sem ela ficam fechados com ENVIRONMENT=production
```

> **Incidente 2026-10-23 — `AUTH_TRUSTED_PROXY_CIDRS` velho derruba cadastro e login por senha.** O IP privado do frontend na Railway muda a cada deploy; um `/32` fixo deixa de casar e `/auth/register`, `/auth/password`, `/auth/verify-email` e `/auth/password-reset` passam a falhar em 2–6 ms, sem chamar o provedor (`provider_call_count=0`). Antes retornava `403 untrusted authentication proxy context` (a UI mostrava "sem permissão"); agora responde `503 authentication unavailable` e registra `auth proxy peer <ip> is outside AUTH_TRUSTED_PROXY_CIDRS` (nível ERROR). Use a faixa privada da Railway, não um IP: `AUTH_TRUSTED_PROXY_CIDRS=10.0.0.0/8,100.64.0.0/10,fd12::/16`. A identidade do proxy continua provada pelo HMAC de `AUTH_PROXY_SECRET`; o CIDR é só a segunda barreira. Teste após cada deploy sem criar conta: `POST /api/auth/password` com e-mail/senha inexistentes deve devolver 400, nunca 403/503.


A API precisa ainda de:

```text
WORKOS_API_KEY=<segredo>
WORKOS_CLIENT_ID=<client id>
WORKOS_REDIRECT_URI=https://app.seudominio.com/api/auth/callback
RESEND_API_KEY=<segredo>
INVITATION_FROM_EMAIL=convites@seudominio.com
```

Cobrança (Stripe, ADR-0023) — somente na API; omita tudo (ou deixe `BILLING_PROVIDER=none`) enquanto a cobrança não estiver pronta, e as rotas de pagamento respondem `501 billing_not_configured`:

```text
BILLING_PROVIDER=stripe
STRIPE_API_KEY=<chave restrita rk_live_…; chaves de teste são recusadas com ENVIRONMENT=production>
STRIPE_WEBHOOK_SECRET=<segredo whsec_… do endpoint de webhook>
STRIPE_API_VERSION=<opcional; padrão pinado no código>
STRIPE_CHECKOUT_INTEGRATION_ID=<opcional; padrão fixo no código>
STRIPE_PORTAL_CONFIGURATION_ID=<opcional; bpc_… criado pelo script de catálogo, se não for o padrão da conta>
STRIPE_PIX_ENABLED=false
# Só para rodar backend/scripts/stripe_sync_catalog.py (a API não lê): STRIPE_CATALOG_API_KEY=<segunda chave restrita, com escrita em Products/Prices/Portal>
```

Use duas chaves restritas distintas: a de runtime (`STRIPE_API_KEY`) e a de catálogo (`STRIPE_CATALOG_API_KEY`). Rode o script de catálogo primeiro com `--dry-run` (padrão) e só depois com `--apply`. Mantenha `STRIPE_PIX_ENABLED=false` até o Pix Automático estar disponível na conta e verificado no sandbox. Passo a passo completo: `docs/stripe-integration-plan.md` § "Ops checklist para go-live (sandbox → produção)".

As URLs de PostgreSQL exportadas pela Railway são aceitas pelo backend, que seleciona o driver `psycopg` instalado. Use a URL privada `DATABASE_URL` do Postgres, nunca `DATABASE_PUBLIC_URL`. As chaves de criptografia precisam continuar iguais às utilizadas para os tokens já salvos; a troca sem migração torna as conexões existentes ilegíveis. Cada chave de provider deve também ser idêntica na API e no worker. Para ClickUp, client ID/secret/redirect são necessários na API para OAuth; o worker sincroniza com o access token salvo e precisa da chave, sem exigir esses três parâmetros no fluxo atual. Uma divergência de chave no worker é corrigida preservando a API e redeployando somente o worker, após validar filas e a descriptografia real. Defina os segredos apenas em Railway Variables, nunca em arquivos versionados. Se alguma integração não estiver pronta para produção, omita suas variáveis e deixe sua conexão indisponível até configurá-la.

O worker não recebe domínio público nem variáveis Resend. Reset de senha revoga as sessões WorkOS automaticamente; não há fila/tarefa Beat de autenticação nem exigência de credenciais WorkOS no worker para esse fluxo. Os processos que carregam o mesmo Settings em produção (incluindo worker e MCP) exigem AUTH_PROXY_SECRET e AUTH_TRUSTED_PROXY_CIDRS válidos na inicialização. Comece com limite de memória adequado para extração de documentos e concorrência Celery igual a 1; aumente somente após medir uso de memória e duração dos jobs.

## 4. Variável e domínio do frontend

Configure antes do primeiro build:

```text
VITE_API_BASE_URL=/api
API_UPSTREAM_URL=https://api.seudominio.com
AUTH_CLIENT_IP_SOURCE=railway
AUTH_PROXY_SECRET=<mesmo segredo configurado na API>
```

`VITE_API_BASE_URL=/api` é incorporado ao JavaScript durante o build e exige novo build/deploy quando alterado. `API_UPSTREAM_URL` é lido pelo servidor do frontend em runtime e aponta para a API; nunca coloque segredos em variáveis `VITE_*`. O proxy em `/api` mantém o cookie de sessão no mesmo host do frontend. Isto é especialmente necessário com dois domínios gerados `*.up.railway.app`, que o navegador trata como sites distintos para cookies `SameSite=Lax`. O container escuta a porta `PORT` fornecida pela Railway e o health check usa `/`.

Confira a fronteira de IP e as opções de e-mail em [Login WorkOS](../../backend/docs/custom-workos-login.md). O frontend deve receber tráfego exclusivamente pelo ingress confiável que substitui X-Real-IP; a API exige HMAC e peer permitido. Settings rejeita produção sem segredo de pelo menos 32 caracteres e CIDRs válidos não vazios (sem /0), antes de servir requisições. Somente /api/auth/* exige IP/contexto assinado no proxy; /api/session e demais rotas continuam disponíveis sem esse contexto. A migração experimental 20261008_0028 nunca aplicada externamente foi removida; o head continua 20261001_0027, sem migração adicional para este login. Este checkout diverge da main quanto ao runtime frontend (Wrangler versus vinext start); valide o runtime final antes do deploy, sem assumir que o smoke Wrangler o cobre.

Adicione os endereços públicos ao frontend e à API. Para domínio próprio, crie os registros CNAME e TXT indicados pela Railway e aguarde a emissão TLS. Confirme que `/api/health/ready` no endereço do frontend retorna 200. Não gere domínio público para worker, banco ou Redis. Se configurar `API_UPSTREAM_URL` com o endereço privado da API e a porta correta, a API pode deixar de ter domínio público após os callbacks OAuth serem transferidos para `/api` no frontend.

## Domínio arquivio.com.br (HostGator DNS)

Topologia: frontend em `https://www.arquivio.com.br` (origem canônica única = `PUBLIC_APP_URL`; `CookieOriginMiddleware` e CORS aceitam só essa origem), a raiz `arquivio.com.br` redireciona 301 para o `www` (redirecionamento do cPanel, pois a HostGator não aceita CNAME na raiz) e a API tem o subdomínio público `https://api.arquivio.com.br` (CNAME `api` → domínio `*.up.railway.app` da API e TXT `_railway-verify.api`, ambos na HostGator; o domínio `*.up.railway.app` é mantido). As rotas `/v1` ficam na raiz desse host (ex.: `https://api.arquivio.com.br/v1/whoami`, `/health/ready`) e são a URL base da documentação pública `/docs/api`. O navegador continua usando `/api` no `www` (proxy do frontend) para a sessão por cookie; a origem canônica de cookies/CORS não muda. Registros `*.mail.arquivio.com.br` e `_dmarc` (Resend) não são alterados.

Rede de segurança no app: se a raiz `arquivio.com.br` chegar ao frontend (domínio anexado no serviço Frontend ou DNS ainda em cache), `next.config.ts` responde 308 para `https://www.arquivio.com.br` (`frontend/app/canonical-host.mjs`, o caminho é preservado). Sem isso, o cadastro/login na raiz envia `Origin: https://arquivio.com.br` e a API responde 403 `origin not allowed` (incidente 2026-10-23, `/auth/register`).

Troca de envs após o DNS responder (Frontend e API/Worker, nessa ordem; `PUBLIC_APP_URL` e redirect URIs em API+Frontend+Worker):

```text
PUBLIC_APP_URL=https://www.arquivio.com.br
WORKOS_REDIRECT_URI=https://www.arquivio.com.br/api/auth/callback
GOOGLE_OAUTH_REDIRECT_URI=https://www.arquivio.com.br/api/data-sources/google/oauth/callback
MICROSOFT_OAUTH_REDIRECT_URI=https://www.arquivio.com.br/api/data-sources/onedrive/oauth/callback
NOTION_OAUTH_REDIRECT_URI=https://www.arquivio.com.br/api/data-sources/notion/oauth/callback
CLICKUP_OAUTH_REDIRECT_URI=https://www.arquivio.com.br/api/data-sources/clickup/oauth/callback
```

Cadastre os mesmos callbacks (e o logout/reset URL `https://www.arquivio.com.br/login`) em WorkOS, Google, Microsoft, Notion e ClickUp antes de trocar as envs, mantendo os antigos até validar.

## 5. Atualizar os provedores externos

Depois de HTTPS funcionar, cadastre os callbacks exatos:

- WorkOS: redirect `https://app.seudominio.com/api/auth/callback`; retorno após logout e Password reset URL `https://app.seudominio.com/login`; e-mail/senha e verificação obrigatória habilitados, e-mails gerenciados de verificação/reset ligados.
- Google Cloud OAuth: `https://app.seudominio.com/api/data-sources/google/oauth/callback`.
- Microsoft Entra: `https://app.seudominio.com/api/data-sources/onedrive/oauth/callback` e os tipos de conta/permissões aprovados para OneDrive pessoal e corporativo.
- Microsoft Entra (SharePoint, mesmo app multi-tenant): `https://app.seudominio.com/api/data-sources/sharepoint/oauth/callback` e a permissão delegada `Sites.Read.All`. O valor deve casar caractere por caractere com `MICROSOFT_SHAREPOINT_REDIRECT_URI`. Veja `docs/integracoes/sharepoint-runbook-consentimento-admin.md`.
- Notion: `https://app.seudominio.com/api/data-sources/notion/oauth/callback`.
- ClickUp (app OAuth em Settings > Apps): `https://app.seudominio.com/api/data-sources/clickup/oauth/callback`. Veja `docs/integracoes/clickup-runbook.md`.
- Resend: verifique o domínio do remetente de convites.
- Stripe (Workbench > Webhooks): endpoint `https://api.seudominio.com/webhooks/billing/stripe` (domínio público da API), com `api_version` `2026-09-30.endive` e exatamente os eventos listados no ops checklist de `docs/stripe-integration-plan.md` (inclui `mandate.updated`); copie o segredo de assinatura para `STRIPE_WEBHOOK_SECRET`. Use um endpoint e chaves separados para homologação (sandbox).

Se um provedor aceita apenas um callback por aplicação, use credenciais de homologação separadas para evitar substituir o callback já usado por produção.

## 6. Verificar e liberar

1. Publique primeiro em homologação, nesta ordem: Postgres/Redis, API com migração concluída, worker e frontend. Confira os logs do pre-deploy: migração concluída uma vez, API saudável em `/health/ready`, worker conectado ao Redis e frontend com a URL correta da API. Em deploys futuros, só atualize o worker após a migração da API quando ele depender do novo esquema.
2. Teste login, logout, convite, acesso de admin, conexão e reconexão de Google Drive/Notion/OneDrive/ClickUp, sincronização de um conjunto pequeno, embeddings, resposta com referências e reprocessamento após reinício do worker. Confira que o worker registra estado terminal do job e que segredos/texto integral não aparecem nos logs.
3. Ative backups agendados do volume do Postgres, mantenha `pg_dump` periódico em armazenamento **fora do projeto Railway** e restaure um dump em homologação. Registre tempo de restauração e idade do backup. Backups do volume são úteis para erros locais; o dump externo cobre perda do projeto/volume.
4. Configure alertas de falha de deploy, serviço indisponível, memória, volume do banco e gasto. Compare CPU, RAM, tempo de sincronização e fatura na primeira semana com o orçamento definido.
5. Só então replique a configuração no ambiente de produção, mantenha os serviços na mesma região, rode uma sincronização controlada e habilite autodeploy após o primeiro deploy validado.

## Rollback

Para falha de código, reverta o deploy da API/frontend/worker. Para falha de dados, restaure o último backup testado ou use recuperação por ponto no tempo se habilitada. Uma migração de banco nem sempre é reversível apenas com rollback de imagem: faça backup antes de migrações que alteram dados e confira a compatibilidade de esquema entre versões.

Referências Railway: [monorepo](https://docs.railway.com/deployments/monorepo), [Dockerfiles e variáveis de build](https://docs.railway.com/builds/dockerfiles), [pre-deploy](https://docs.railway.com/deployments/pre-deploy-command), [rede privada](https://docs.railway.com/networking/private-networking), [domínios](https://docs.railway.com/networking/domains/working-with-domains), [backup e restauração](https://docs.railway.com/guides/postgres-backups-restores).

## pgvector (F5)

A migração `20260930_0020_pgvector_expand` executa `CREATE EXTENSION IF NOT EXISTS vector`. Crie o Postgres a partir do template com pgvector (https://railway.com/deploy/postgres-with-pgvector-engine) ou da imagem `pgvector/pgvector:pg16`; o Postgres padrão sem a extensão faz o pre-deploy falhar. Confira com `SELECT extversion FROM pg_extension WHERE extname = 'vector';`. `VECTOR_BACKEND=pgvector` é o padrão: trechos ainda sem `embedding_vec` são convertidos do JSON na própria consulta, então a busca fica correta antes do backfill; o backfill só a deixa mais rápida. `VECTOR_BACKEND=python` volta ao cálculo em Python (ver `docs/operacao/pgvector-runbook.md`).

## OCR (docling-serve com `por`)

O sidecar de OCR **não** usa a imagem upstream: ela não inclui o modelo Tesseract `por`. Crie o serviço `docling` (sem domínio público, rede privada) a partir de `infra/docling/Dockerfile` (base `docling-serve-cpu:v1.35.0` fixada por digest + `tessdata_best` verificado por SHA-256) ou de uma imagem publicada desse Dockerfile. Reserve ≥ 2 GB de RAM (pico medido ≈ 1,6–1,9 GB) e aponte `DOCLING_SERVE_URL` do worker para o endereço privado. Detalhes e escolha `best`/`fast`: `docs/operacao/ocr-runbook.md`.
