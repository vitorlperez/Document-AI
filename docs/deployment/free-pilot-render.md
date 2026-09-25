# Piloto gratuito temporário: Render, Supabase e Upstash

Este perfil põe a interface e a API online para testes sem depender de uma VM
Oracle. Ele não substitui o perfil Oracle em `docker-compose.production.yml`.
O banco e a fila usam URLs gerenciadas, portanto uma migração posterior para
Oracle ou Google não requer alterar os módulos da aplicação.

## Limites assumidos

- Os dois serviços web gratuitos do Render adormecem após inatividade. A
  primeira requisição depois disso pode demorar aproximadamente um minuto.
- O Render não disponibiliza background workers no plano gratuito. O worker
  Celery roda no Docker deste computador. Com o computador desligado, novas
  sincronizações ficam `queued`; consultas a documentos já indexados continuam
  funcionando.
- Supabase e Upstash têm limites de plano gratuito. Este ambiente serve para
  piloto/teste, não para reter dados de clientes sem um plano de backup e
  operação.

## 1. Defina os dois endereços públicos

Antes de testar login, use dois subdomínios do **mesmo domínio pai**. Exemplo:

```text
app.seudominio.com  -> frontend Render
api.seudominio.com  -> API Render
```

Não use os dois endereços `*.onrender.com` para autenticação. Eles são
cross-site entre si, e a sessão segura do produto usa cookies `SameSite=Lax`.
No Render, adicione cada domínio em **Settings > Custom Domains** do respectivo
serviço e crie no DNS exatamente o registro CNAME solicitado. O Render emite o
certificado TLS após a verificação.

Guarde os dois valores para os passos seguintes:

```text
PUBLIC_APP_URL=https://app.seudominio.com
API_PUBLIC_URL=https://api.seudominio.com
```

## 2. Crie os dados gerenciados

1. No Supabase, crie um projeto PostgreSQL no plano Free e habilite a extensão
   `vector` no SQL Editor:

   ```sql
   create extension if not exists vector;
   ```

   Copie a **connection string direta** e converta o início para o driver da
   aplicação, se necessário:

   ```text
   postgresql+psycopg://... ?sslmode=require
   ```

   Use a URL direta/pooler que aceite migrações e conexões de longa duração;
   não exponha essa URL no frontend.
2. No Upstash, crie um banco Redis no plano Free e copie a URL TLS `rediss://`.
   A API e o worker devem receber exatamente a mesma URL.

## 3. Publique API e frontend no Render

1. Envie esta alteração para o repositório Git que será conectado ao Render.
2. No Render, escolha **New > Blueprint** e selecione o repositório. O arquivo
   [`render.yaml`](../../render.yaml) cria dois web services Docker gratuitos:
   `document-ai-api-pilot` e `document-ai-web-pilot`.
3. Para a API, informe os valores abaixo em **Environment**. Não os coloque no
   Git nem em `render.yaml`:

   | Variável | Valor |
   | --- | --- |
   | `DATABASE_URL` | URL PostgreSQL Supabase com `sslmode=require` |
   | `REDIS_URL` | URL `rediss://` do Upstash |
   | `PUBLIC_APP_URL` | `https://app.seudominio.com` |
   | `OPENAI_API_KEY` | chave do servidor OpenAI |
   | `WORKOS_API_KEY`, `WORKOS_CLIENT_ID` | valores atuais do WorkOS |
   | `WORKOS_REDIRECT_URI` | `https://api.seudominio.com/auth/callback` |
   | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | credencial atual do Google |
   | `GOOGLE_OAUTH_REDIRECT_URI` | `https://api.seudominio.com/data-sources/google/oauth/callback` |
   | `GOOGLE_TOKEN_ENCRYPTION_KEY` | a mesma chave Fernet estável usada localmente |
   | `MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET` | credencial do app registrado no Microsoft Entra |
   | `MICROSOFT_OAUTH_REDIRECT_URI` | `https://api.seudominio.com/data-sources/onedrive/oauth/callback` |
   | `MICROSOFT_TOKEN_ENCRYPTION_KEY` | chave Fernet estável para tokens e cursores OneDrive |
   | `RESEND_API_KEY`, `INVITATION_FROM_EMAIL` | configuração atual de convites |

4. Para o frontend, informe somente:

   ```text
   VITE_API_BASE_URL=https://api.seudominio.com
   ```

   Esse valor é público e é incorporado no build; nunca use uma chave ou senha
   em uma variável `VITE_*`.
5. Depois de os dois deploys ficarem saudáveis, adicione os dois custom domains
   do passo 1 e aguarde a validação TLS.

O container da API executa `alembic upgrade head` no início. Mantenha apenas
uma instância da API neste perfil; assim não há corrida de migrações.

## 4. Atualize os callbacks externos

Somente depois de os domínios HTTPS estarem ativos, altere os painéis:

- **WorkOS**: redirect URI `https://api.seudominio.com/auth/callback`; sign-out
  URI `https://app.seudominio.com`.
- **Google Cloud OAuth**: authorized redirect URI
  `https://api.seudominio.com/data-sources/google/oauth/callback`.
- **Microsoft Entra**: configure o app para contas em qualquer diretório organizacional
  e contas Microsoft pessoais, adicione o redirect URI da API acima e conceda
  permissões delegadas `Files.Read`
  e `User.Read`. O consentimento `openid profile offline_access` é solicitado pelo
  fluxo OAuth para identidade e renovação de tokens.
- **Resend**: mantenha um remetente/dominio já verificado. Nenhuma alteração é
  necessária se o remetente atual estiver válido.

Teste nesta ordem: abrir `https://api.seudominio.com/health/ready`, entrar pelo
frontend, criar/aceitar convite, conectar Google Drive e iniciar uma
sincronização pequena.

## 5. Rode o worker local contra os mesmos serviços

```bash
cp .env.remote-worker.example .env.remote-worker
# Edite .env.remote-worker com os mesmos valores da API no Render.
docker compose -f docker-compose.remote-worker.yml up --build
```

Deixe esse comando rodando enquanto indexa ou reindexa. Para parar, use
`docker compose -f docker-compose.remote-worker.yml down`.

## Retorno para Oracle ou Google

O banco/exportação e a fila não estão acoplados ao Render. Antes de mover,
faça backup do PostgreSQL, crie os serviços equivalentes no destino, atualize
as variáveis de ambiente e execute a migração. Depois mude apenas os callbacks
OAuth e os registros DNS quando o novo ambiente estiver saudável.
