# F-212 — Evidência de diagnóstico e ajuste de configuração

Data: 2026-10-08. Worker: pane-500. Ambiente: Railway production. Domínios e segredos omitidos.

## Causa e teste antes da alteração

- Leitura de `railway variables --service API --json`: `CLICKUP_OAUTH_REDIRECT_URI` usa o frontend com o caminho `/data-sources/clickup/oauth/callback`, sem `/api`.
- GET anônimo no frontend, com `code=test&state=test`: caminho sem `/api` = 404; com `/api` = 401 JSON da API.
- GET direto na API: `/data-sources/clickup/oauth/callback` = 401; `/api/data-sources/clickup/oauth/callback` = 404. A assimetria é intencional: o proxy remove `/api`.
- Implementação existente: `backend/app/api/integrations.py:376` e `frontend/app/api/[...path]/route.ts:24`. O runbook já recomenda o prefixo quando o callback está no frontend.
- Documentação oficial confirma que o ClickUp retorna ao `redirect_uri` enviado na autorização: https://developer.clickup.com/docs/authentication.

## Alteração e verificação

- Executado via Python, sem imprimir valores: `railway variables --service API --set CLICKUP_OAUTH_REDIRECT_URI=<PUBLIC_APP_URL>/api/data-sources/clickup/oauth/callback --skip-deploys`: exit 0.
- Releitura: valor corresponde exatamente ao esperado. Nenhum deploy foi disparado.
- Verificação fresca com Python/urllib e Railway CLI: **4/4 diagnostic checks passed**, exit 0 (valor corrigido, rota incorreta 404, rota correta 401, bloqueio de implantação confirmado).
- Não houve alteração de código de produção, troca de tokens, chamada autenticada ao ClickUp ou consumo de código OAuth real. O 401 anônimo confirma o roteamento, não uma conexão OAuth completa.

## Bloqueio de ativação independente

- `railway status --json`: último deploy da API, commit `2112c8aec84a2aede800a36879f02f27984e0daa`, status `FAILED`; a API anterior ainda responde `/health/ready` com 200.
- `railway logs --service API --deployment --lines 70 <latestDeploymentId>`: exit 0; pre-deploy Alembic falha com `Production requires valid AUTH_PROXY_SECRET and AUTH_TRUSTED_PROXY_CIDRS before startup`.
- As duas variáveis estão ausentes na API. `AUTH_PROXY_SECRET` e `AUTH_CLIENT_IP_SOURCE` também estão ausentes no frontend. Não criar um CIDR permissivo nem contornar o gate para publicar.
- Próxima ação: configurar a confiança real do ingress/proxy conforme `docs/deployment/railway-production.md`, validar a URL permitida no ClickUp, realizar deploy saudável da API e repetir conexão real. A alteração fica preparada no Railway; ainda não está ativa no processo que atende produção.

skills: inline [oc-builder, oc-blackbox, oc-stamp].
