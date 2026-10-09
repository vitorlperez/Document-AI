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

## Atualização: publicação por pane-500 e verificação independente por pane-501

Verificação em 2026-10-09 entre 01:38 e 01:53 UTC (noite de 08/10 em São Paulo). Fontes de coordenação: fullText `h-l4` e `h-l7`. O bloqueio de ativação descrito acima é **histórico**: o callback está ativo. A validação completa de operação/ingress continua parcial pelos achados abaixo. Pane-501 manteve a configuração, os segredos e os deploys de h-l7; alterou somente documentação.

### Implantação de h-l7, conferida independentemente

| Serviço | Deployment ativo | Commit | Estado | Readiness configurada |
| --- | --- | --- | --- | --- |
| Frontend | `18cbbdd1-9996-4d0b-af4b-3ef375fbc483` | `2112c8a` | SUCCESS | nenhuma |
| API | `f8311dd2-0bed-4154-8245-2d8b0887444d` | `2112c8a` | SUCCESS | `/health/ready` |
| Worker | `0774aa91-4b74-4afb-8f3e-718c316a7ddb` | `2112c8a` | SUCCESS (processo Celery; não comprova execução de tarefas) | não aplicável |
| Beat | `59db34fa-e2bf-4bb4-b2f9-213eddf10e4e` | `2112c8a` | SUCCESS (agendador) | não aplicável |

Pane-500 criou segredo novo com 48 bytes aleatórios (`token_urlsafe`) e publicou frontend/API. A configuração preparada tem o mesmo segredo de 64 caracteres nos quatro serviços, `ENVIRONMENT=production`, `AUTH_CLIENT_IP_SOURCE=railway` no frontend e somente 2 hosts privados reais nos serviços Python, /32 e /128. Nenhum segredo foi colocado em variáveis públicas. Releitura de DNS privado e conexão TCP frontend→API confirmou igualdade exata entre os dois hosts atuais e os CIDRs configurados, e que a conexão usa um deles. Nenhum `/0` ou range de rede foi introduzido. Valores secretos e endereços privados não são armazenados neste relatório.

No runtime API, `get_settings()` carrega, o callback corresponde exatamente a `PUBLIC_APP_URL + /api/data-sources/clickup/oauth/callback` e `alembic current` retorna `20261001_0027 (head)`. Não há migração nova de autenticação. `UVICORN_PROXY_HEADERS=false` está ativo. O start override ainda não contém `--no-proxy-headers` literal; uma execução CliRunner da CLI uvicorn **instalada no container**, interceptando somente a função `run` nesse processo de diagnóstico, comprova `proxy_headers=False`, o comportamento equivalente. Não foi iniciada outra API nem alterado o processo servidor.

### Provas independentes de HTTP, browser, build e testes

| Comando/prova | Exit | Resultado |
| --- | --- | --- |
| `cd backend && .venv/bin/python -m pytest tests/unit/test_auth_proxy_config.py tests/unit/test_auth_log_redaction.py tests/unit/test_clickup_integration.py tests/api/test_auth_and_invitations.py -q --tb=short` | 0 | 104 passed, 1 warning |
| `node --test frontend/tests/proxy-headers.test.mjs frontend/tests/dockerfile-production.test.mjs frontend/tests/auth-runtime-env.test.mjs frontend/tests/auth-navigation.test.mjs` | 0 | 9 tests, 9 pass, 0 fail |
| `cd frontend && npm run build` | 0 | 5 estágios concluídos; artefato vinext para `vinext start` |
| Python `urllib` + releitura Railway, 8 assertions HTTP seguras | 0 | 8/8 passed; tabela abaixo |
| Chromium anônimo, DOM hidratado em `/login`, 1280 e 390 px | 0 | e-mail/senha/SSO visíveis; 0 alerts, 0 page errors, sem overflow, header/meta no-referrer; nenhum formulário enviado |
| SSH Frontend: DNS + socket real para readiness upstream | 0 | 2 hosts DNS exatamente confiáveis; source TCP permitido; upstream 200 |
| SSH API: Settings, callback, ambiente, CIDRs, Alembic | 0 | runtime correto; 2 host CIDRs; callback ativo; schema head |
| SSH API: CliRunner uvicorn com `run` interceptado | 0 | cli_exit=0; effective_proxy_headers=false |
| SSH Worker: `python -c 'from app.core.config import get_settings; get_settings()'` | 1 (processo testado) | falta contrato proxy no ambiente do processo ativo |
| `railway logs --service Worker --lines 120`, filtragem sem segredos | 0 | 9 ocorrências do erro de validação de produção |
| SSH Beat: construção direta de Settings | falha de validação | `DATABASE_URL` ausente; módulo agendador não chama Settings na importação |
| SSH API: pedido privado ao frontend + contagem Redis antes/depois | 0 (reprodução confirmada) | status 400; bucket do IP falso 0→1; ver seção de confiança |

Seleção inicial de testes a partir da raiz importou `.env` local com OCR incompleto: 59 passed, 1 failed e 44 errors de configuração. Reexecutar no diretório backend, como no contrato do projeto, resolveu essa contaminação sem mudar código ou afrouxar produção. A rodada válida é a de 104 passed acima. Scripts temporários de verificação e uma tentativa de montagem de documentação tiveram erros de sintaxe antes de executar qualquer alteração de produção; foram corrigidos. A CLI 4.10.0 falhou em SSH; CLI oficial 5.64.1 autenticou com chave temporária posteriormente revogada. A chave privada temporária foi removida; nenhum acesso diagnóstico ficou aberto.

| Caminho/prova HTTP | Status | Significado |
| --- | --- | --- |
| Frontend `/api/health/ready` | 200 | API ativa e banco/Redis prontos |
| Frontend `/api/session` | 200 | sessão anônima normal |
| Frontend `/api/data-sources/clickup/oauth/callback?code=f212-safe&state=f212-invalid` | 401 | JSON API `authentication required`; chega à rota, antes de OAuth; não testa state autenticado |
| Frontend `/data-sources/clickup/oauth/callback?...` | 404 | rota antiga continua incorreta |
| Frontend `/login` + browser hidratado | 200 | login personalizado entregue e utilizável em desktop/celular |
| Frontend `/api/auth/password`, senha vazia | 400 | `Confira a senha informada.`; assinatura/peer passam; WorkOS não chamado |
| Mesmo pedido público com X-Real-IP/XFF/contexto forjado | 400 | ingress substitui o IP forjado, comprovado pela observação abaixo |
| API pública `/auth/password`, contexto forjado | 403 | `untrusted authentication proxy context` |

### Pendência de confiança reproduzida na rede privada

Observação temporária **somente de leitura** dos eventos HTTP do Node do frontend capturou três pedidos marcados, sem logar cookies, senhas, assinaturas ou tokens. No pedido público de controle e no público com `X-Real-IP: 203.0.113.66`, o IP recebido era idêntico ao controle e diferente do valor falso; o peer era o edge. O pedido originado via SSH no container API diretamente ao domínio **privado** do frontend recebeu peer privado e preservou `X-Real-IP: 203.0.113.66`. O listener de diagnóstico foi restaurado e o inspector em loopback foi encerrado e conferido inacessível depois do teste.

Reprodução adicional sem instrumentação: no processo de diagnóstico API, ler Redis, enviar POST ao frontend privado em `/api/auth/password` com Origin pública correta, `X-Real-IP: 203.0.113.212`, e-mail sintético e **senha vazia**. Não enviar `x-auth-ip-signature`. Resultado: HTTP 400 `Confira a senha informada.`, bucket `rl:auth:ip:203.0.113.212:<janela atual>` ausente antes, contagem 1 depois. Esse bucket tem TTL curto normal; nenhuma chave de dados ou credencial foi alterada. A senha vazia interrompe a execução **antes da chamada WorkOS** (`backend/app/api/auth.py:211`).

Conclusão localizada: `frontend/app/api/proxy-headers.mjs:22-34` pressupõe ingress exclusivo, mas assina o `X-Real-IP` recebido sem checar a origem TCP. A API valida corretamente o HMAC e o peer **frontend** em `backend/app/identity/client_ip.py:20-34`; ela não distingue que o frontend recebeu o pedido por uma entrada privada. Logo, a verificação de h-l7 de não forjabilidade é válida para o edge público testado, e **não** para clientes com acesso ao ambiente privado Railway. Não foi demonstrado bypass pela internet nem exploração por usuário comum. Não assumir que headers ou só os CIDRs API eliminam essa entrada. Uma correção de segurança exige delimitar/verificar a entrada do frontend e ser revisada independentemente antes de publicar. Nenhuma validação foi relaxada e nenhum código novo de segurança foi implementado nesta continuação.

Consultas atuais da API Railway confirmam 0 TCP proxies em frontend/API/worker/Beat. Isso elimina essa modalidade de exposição pública, mas não impede a comunicação interna documentada pela Railway. Fontes oficiais atuais: [headers de ingress](https://docs.railway.com/networking/public-networking/specs-and-limits), [isolamento e comunicação privada](https://docs.railway.com/networking/private-networking/how-it-works).

### Pendências dos processos e limites de publicação

- Worker tem variáveis corretas **preparadas**, porém o processo ativo anterior não as recebeu. A construção de Settings retorna exit 1, e os logs comprovam falhas reais. `backend/app/ingestion/tasks.py:216`, `:228` e `:242` usam Settings para agendamento executado no worker, purge e reconciliação. É necessário um deploy/restart **controlado somente do Worker**, com as variáveis atuais e validação de execução, em atividade autorizada posterior; não foi feito após a orientação de manter os deploys.
- Beat está em production com proxy preparado, sem `DATABASE_URL`. `backend/app/ingestion/tasks.py:71` configura o agendamento sem Settings; suas tarefas executam no Worker. Não atribuir a Beat a falha de reconciliação do Worker. Se exigir construção de Settings nesse serviço, ele precisa receber o contrato completo, inclusive banco, antes de executar esse caminho. Nenhum serviço MCP implantado foi encontrado; o processo opcional MCP deve cumprir o mesmo gate caso seja criado.
- Frontend não tem healthcheck configurado. API tem `/health/ready`. A documentação Railway só promete manter a versão anterior até a nova passar readiness **quando o healthcheck está configurado**: [healthchecks](https://docs.railway.com/deployments/healthchecks). O frontend está saudável agora; proteção de readiness para um próximo deploy frontend é pendência operacional.
- Um novo deployment frontend pode alterar os hosts privados. Reobservar DNS e conexão real antes de atualizar CIDRs da API/Worker/Beat. Nunca usar a máscara ampla da interface nem `/0` para evitar essa manutenção.
- Main possui repo triggers GitHub ativos, `checkSuites=false`, e `watchPatterns=[]` para frontend/API. Push de documentação em main não foi considerado seguro para a ordem de não republicar: [autodeploys](https://docs.railway.com/deployments/github-autodeploys), [watch paths](https://docs.railway.com/deployments/monorepo). Documentação publicada somente em `docs/f212-production-verification`; merge para main depende de proteger a operação contra autodeploy e troca de peers. A branch local compartilhada não foi trocada.

### Rollback e próximo teste do usuário

Não houve falha de novo deployment nesta verificação e não foi executado rollback. O bloqueio original mantinha API `b0510ad7-f9ca-4eb4-ad37-feb54d668baa` saudável enquanto o predeploy novo falhava. Depois do deploy bem-sucedido, a versão ativa é `f8311dd2` e o schema continua no head anterior, sem alteração de dados. Se uma próxima publicação falhar, preservar a versão que atende até readiness; abortar a candidata e conferir a saúde da anterior. Rollback Railway restaura imagem **e variáveis**; por isso, re-preparar via `--skip-deploys` o callback correto e o contrato seguro após rollback, sem imprimir valores, antes de nova ativação. Referência oficial: [deployment actions](https://docs.railway.com/deployments/deployment-actions).

URL exata a permitir no app OAuth ClickUp:

`https://frontend-production-e02d.up.railway.app/api/data-sources/clickup/oauth/callback`

O usuário deve iniciar uma autorização nova por **Conectar** na sua sessão; link antigo pode carregar o redirect_uri antigo. A lista permitida do app ClickUp não foi alterada nem verificada no painel. Nenhuma conta de teste autorizada foi fornecida/identificada e não se usou conta autenticada de terceiros. Não houve troca de código/token, e-mail, cadastro ou OAuth ponta a ponta. [Referência oficial ClickUp](https://developer.clickup.com/docs/authentication).

Resultados estruturados sem segredos: `TASK/evidence/f212-production-checks.json`. skills: inline [oc-builder, oc-blackbox, oc-stamp].
