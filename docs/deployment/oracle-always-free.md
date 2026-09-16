# Deploy do piloto na Oracle Always Free

Esta topologia executa frontend, API, worker Celery, Postgres e Redis na mesma VM ARM Always Free. Somente Caddy publica as portas `80` e `443`; banco, Redis e API permanecem na rede privada do Docker.

## Pré-requisitos

1. Uma VM Oracle Linux ou Ubuntu ARM Always Free com Docker Engine e o plugin Docker Compose.
2. Um domínio ou subdomínio público, por exemplo `app.seudominio.com`, com registro A apontando para o IP público da VM.
3. Regras de entrada da Oracle e firewall da VM liberando somente TCP `80` e `443`. Mantenha SSH restrito ao seu IP quando possível.
4. Contas e segredos do WorkOS, Google OAuth, Resend e OpenAI. Nunca copie o `.env.production` para o Git.

## Configuração inicial

Na VM, clone o repositório e crie o arquivo de produção:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

Preencha todos os valores. `POSTGRES_PASSWORD` faz parte da URL de conexão e precisa ser hexadecimal (para não quebrar a URL com caracteres reservados). Gere-o com `openssl rand -hex 32`. Mantenha o valor de `GOOGLE_TOKEN_ENCRYPTION_KEY` estável: trocá-lo depois impede a leitura das credenciais Google já criptografadas.

Inicie os serviços:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

Acompanhe a primeira migração e o worker:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml logs -f migrate api worker
```

Para checar se o worker Celery responde após o primeiro deploy:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec worker celery -A app.ingestion.tasks inspect ping
```

## URLs de OAuth e autenticação

Com `APP_DOMAIN=app.seudominio.com`, configure exatamente:

- WorkOS redirect URI: `https://app.seudominio.com/api/auth/callback`
- WorkOS sign-out URI: `https://app.seudominio.com`
- Google OAuth authorized redirect URI: `https://app.seudominio.com/api/data-sources/google/oauth/callback`

O frontend chama a API através de `/api`, no mesmo domínio. Isso preserva cookies `Secure` e elimina a necessidade de expor uma origem adicional de CORS.

## Atualização e rollback

Para atualizar, faça `git pull` e repita o comando `up -d --build`. O serviço `migrate` executa Alembic antes de API e worker.

Antes de atualizar, faça um backup do Postgres:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec -T postgres pg_dump -U document_intelligence document_intelligence > backup.sql
```

O rollback de código pode usar o commit Git anterior e reconstruir os containers. Nunca faça downgrade de migração em produção sem validar se os dados posteriores são compatíveis.

## Limites do piloto

Esta é uma topologia de custo fixo zero, não uma arquitetura com alta disponibilidade. Uma queda ou manutenção da VM interrompe todos os serviços. Configure alarmes de CPU, memória e disco na Oracle e mantenha backups externos periódicos do banco. Antes de armazenar dados reais de clientes, defina um destino externo e a frequência desse backup (por exemplo, Object Storage ou outro provedor sob seu controle).

O frontend é construído pelo Vinext e servido pelo comando de produção `vinext start` dentro de um container dedicado. Esta topologia ainda é de piloto: uma única VM não oferece alta disponibilidade ou SLA.
