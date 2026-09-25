# Preparar a produção na Railway

Este guia prepara o Arquivio para a Railway sem usar o `docker-compose.yml` de desenvolvimento. O projeto Railway contém cinco serviços no mesmo ambiente e região: `frontend`, `api`, `worker`, `Postgres` e `Redis`. Somente `frontend` e `api` recebem domínios públicos. PostgreSQL e Redis da Railway são serviços em containers com volumes; habilite e teste os backups antes de armazenar dados de clientes.

## 1. Definir os valores de produção

Antes de criar recursos pagos, escolha a região dos dados, o domínio, o orçamento mensal e a política de retenção dos backups. Reserve os subdomínios `app.seudominio.com` e `api.seudominio.com` sob o **mesmo domínio registrável**: os cookies de sessão usam `SameSite=Lax`, e o navegador envia requisições autenticadas do app para a API. Separe um ambiente de homologação com banco, Redis, domínio e credenciais próprios; não copie tokens OAuth ou dados reais para ele.

## 2. Criar o projeto e os serviços

1. Crie um projeto Railway e um ambiente de homologação. Selecione a mesma região para os cinco serviços. Desative o autodeploy da branch de produção até concluir esta lista.
2. Adicione `Postgres` e `Redis` pelo menu **New > Database**. Não habilite Public Access/TCP Proxy para eles. Se já houver dados a migrar, planeje um dump e uma janela de corte antes de usar o novo banco.
3. Crie três serviços a partir deste repositório Git. Configure-os em **Settings > Source/Build/Deploy** desta forma:

   - `api`: Root Directory `/backend`; builder Dockerfile (`Dockerfile`); pre-deploy command `alembic upgrade head`; start command `/bin/sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'`; healthcheck path `/health/ready` com timeout de 300 s; restart policy **Always**.
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
OPENAI_API_KEY=<segredo>
GOOGLE_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
MICROSOFT_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
NOTION_TOKEN_ENCRYPTION_KEY=<chave Fernet estável>
GOOGLE_OAUTH_CLIENT_ID=<client id>
GOOGLE_OAUTH_CLIENT_SECRET=<segredo>
GOOGLE_OAUTH_REDIRECT_URI=https://api.seudominio.com/data-sources/google/oauth/callback
MICROSOFT_OAUTH_CLIENT_ID=<client id>
MICROSOFT_OAUTH_CLIENT_SECRET=<segredo>
MICROSOFT_OAUTH_REDIRECT_URI=https://api.seudominio.com/data-sources/onedrive/oauth/callback
NOTION_OAUTH_CLIENT_ID=<client id>
NOTION_OAUTH_CLIENT_SECRET=<segredo>
NOTION_OAUTH_REDIRECT_URI=https://api.seudominio.com/data-sources/notion/oauth/callback
```

A API precisa ainda de:

```text
WORKOS_API_KEY=<segredo>
WORKOS_CLIENT_ID=<client id>
WORKOS_REDIRECT_URI=https://api.seudominio.com/auth/callback
RESEND_API_KEY=<segredo>
INVITATION_FROM_EMAIL=convites@seudominio.com
```

As URLs de PostgreSQL exportadas pela Railway são aceitas pelo backend, que seleciona o driver `psycopg` instalado. Use a URL privada `DATABASE_URL` do Postgres, nunca `DATABASE_PUBLIC_URL`. As chaves de criptografia precisam continuar iguais às utilizadas para os tokens já salvos; a troca sem migração torna as conexões existentes ilegíveis. Defina os segredos apenas em Railway Variables, nunca em arquivos versionados. Se alguma integração não estiver pronta para produção, omita suas variáveis e deixe sua conexão indisponível até configurá-la.

O worker não recebe domínio público nem variáveis WorkOS/Resend. Comece com limite de memória adequado para extração de documentos e concorrência Celery igual a 1; aumente somente após medir uso de memória e duração dos jobs.

## 4. Variável e domínio do frontend

Configure antes do primeiro build:

```text
VITE_API_BASE_URL=https://api.seudominio.com
```

Esse valor é público e é incorporado ao JavaScript durante o build. Qualquer troca da URL exige novo build/deploy do frontend. Nunca coloque segredos em variáveis `VITE_*`. O container escuta a porta `PORT` fornecida pela Railway e o health check usa `/`.

Adicione os domínios públicos `app.seudominio.com` ao frontend e `api.seudominio.com` à API. Crie os registros CNAME e TXT indicados pela Railway, aguarde a emissão TLS e confirme que `https://api.seudominio.com/health/ready` retorna 200. Não gere domínio público para worker, banco ou Redis.

## 5. Atualizar os provedores externos

Depois de HTTPS funcionar, cadastre os callbacks exatos:

- WorkOS: redirect `https://api.seudominio.com/auth/callback`; retorno após logout `https://app.seudominio.com/login`.
- Google Cloud OAuth: `https://api.seudominio.com/data-sources/google/oauth/callback`.
- Microsoft Entra: `https://api.seudominio.com/data-sources/onedrive/oauth/callback` e os tipos de conta/permissões aprovados para OneDrive pessoal e corporativo.
- Notion: `https://api.seudominio.com/data-sources/notion/oauth/callback`.
- Resend: verifique o domínio do remetente de convites.

Se um provedor aceita apenas um callback por aplicação, use credenciais de homologação separadas para evitar substituir o callback já usado por produção.

## 6. Verificar e liberar

1. Publique primeiro em homologação, nesta ordem: Postgres/Redis, API com migração concluída, worker e frontend. Confira os logs do pre-deploy: migração concluída uma vez, API saudável em `/health/ready`, worker conectado ao Redis e frontend com a URL correta da API. Em deploys futuros, só atualize o worker após a migração da API quando ele depender do novo esquema.
2. Teste login, logout, convite, acesso de admin, conexão e reconexão de Google Drive/Notion/OneDrive, sincronização de um conjunto pequeno, embeddings, resposta com referências e reprocessamento após reinício do worker. Confira que o worker registra estado terminal do job e que segredos/texto integral não aparecem nos logs.
3. Ative backups agendados do volume do Postgres, mantenha `pg_dump` periódico em armazenamento **fora do projeto Railway** e restaure um dump em homologação. Registre tempo de restauração e idade do backup. Backups do volume são úteis para erros locais; o dump externo cobre perda do projeto/volume.
4. Configure alertas de falha de deploy, serviço indisponível, memória, volume do banco e gasto. Compare CPU, RAM, tempo de sincronização e fatura na primeira semana com o orçamento definido.
5. Só então replique a configuração no ambiente de produção, mantenha os serviços na mesma região, rode uma sincronização controlada e habilite autodeploy após o primeiro deploy validado.

## Rollback

Para falha de código, reverta o deploy da API/frontend/worker. Para falha de dados, restaure o último backup testado ou use recuperação por ponto no tempo se habilitada. Uma migração de banco nem sempre é reversível apenas com rollback de imagem: faça backup antes de migrações que alteram dados e confira a compatibilidade de esquema entre versões.

Referências Railway: [monorepo](https://docs.railway.com/deployments/monorepo), [Dockerfiles e variáveis de build](https://docs.railway.com/builds/dockerfiles), [pre-deploy](https://docs.railway.com/deployments/pre-deploy-command), [rede privada](https://docs.railway.com/networking/private-networking), [domínios](https://docs.railway.com/networking/domains/working-with-domains), [backup e restauração](https://docs.railway.com/guides/postgres-backups-restores).
