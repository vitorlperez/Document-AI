# Docker local na mesma origem — 08/10/2026

O app está disponível em http://localhost:3000 e o login em http://localhost:3000/login. Todas as requisições da interface passam por `/api` nessa mesma origem. A API atende internamente em `http://api:8000` na rede Docker; a porta 8000 não está publicada no host.

Configuração persistente em `docker-compose.yml`: frontend com `VITE_API_BASE_URL=/api`, `NEXT_PUBLIC_API_BASE_URL=/api` e `API_UPSTREAM_URL=http://api:8000`. Em desenvolvimento, `frontend/vite.config.ts` transporta o upstream do processo Node para o binding do Worker Cloudflare. Essa passagem ocorre somente no comando `serve`, sem embutir o upstream no build de produção ou no cliente. `.env` local foi atualizado somente nas URLs de retorno; credenciais foram preservadas.

| Callback local | URL |
| --- | --- |
| WorkOS | `http://localhost:3000/api/auth/callback` |
| Google | `http://localhost:3000/api/data-sources/google/oauth/callback` |
| OneDrive | `http://localhost:3000/api/data-sources/onedrive/oauth/callback` |
| SharePoint | `http://localhost:3000/api/data-sources/sharepoint/oauth/callback` |
| Notion | `http://localhost:3000/api/data-sources/notion/oauth/callback` |
| ClickUp | `http://localhost:3000/api/data-sources/clickup/oauth/callback` |

## Dashboard WorkOS Staging

No ambiente correspondente às credenciais locais existentes, confira **Applications → aplicação → Redirects**:

- **Redirect URIs:** adicione `http://localhost:3000/api/auth/callback`, preservando os callbacks existentes.
- **Password reset URL:** `http://localhost:3000/login`.

O Dashboard remoto não foi consultado ou alterado. A autorização gerada pela API já solicita o novo callback; sem cadastrá-lo no WorkOS, o provedor pode rejeitar SSO/AuthKit hospedado. Cadastre também as URLs novas nos provedores de integrações que estiverem habilitados antes de reconectá-los. A tela de login permanece no localhost; SSO e métodos avançados continuam usando o AuthKit hospedado.

## Verificação executada

- Antes da configuração, `/api/health/live`, `/api/session` e `/api/auth/callback` retornavam 503 por upstream ausente. Somente adicionar a variável ao processo Node ainda retornou 503; o Worker tinha ambiente separado. Após transportá-la como binding de desenvolvimento, as rotas reais passaram.
- `docker compose config --quiet`: exit 0.
- `docker compose up -d --no-deps --force-recreate --wait --wait-timeout 60 api frontend`: exit 0; somente API/frontend recriados. Depois da correção do binding, `docker compose build frontend` e recriação somente do frontend: exit 0.
- `python3 artifacts/local-single-origin-20261008/runtime-smoke.py`: 8/8 verificações HTTP. Sessão anônima 200/null; healthcheck e readiness 200; `/api/me` e callback com state inválido 401; `/api/auth/login` 302 com novo callback e cookie HttpOnly. Sem seguir o redirect remoto.
- `node artifacts/local-single-origin-20261008/browser-smoke.mjs`: 3/3 larguras, 1440/390/320. Nenhuma requisição fora da origem 3000, erro JavaScript, alerta de sessão ou overflow. Formulários de cadastro/recuperação abertos sem submit; corpo vazio de login devolve 422 antes de chamar o WorkOS.
- `node --test tests/proxy-headers.test.mjs tests/auth-navigation.test.mjs tests/auth-runtime-env.test.mjs`, no frontend: 8/8, exit 0.
- `npx tsc --noEmit` e `npx eslint vite.config.ts`, no frontend: exit 0.
- `graphify update .`: exit 0.

`runtime-checks.json` comprova IDs, horários de início e mounts preservados de Postgres, Redis, worker e Beat, credenciais WorkOS preservadas e API sem porta publicada. O smoke não executa autenticação real nem envio de e-mail. Os arquivos de evidência anteriores descrevem o estado anterior.

Skills: inline [oc-builder, oc-blackbox, oc-stamp]. Sem deploy ou commit; permanece a árvore compartilhada com as alterações de login anteriores.
