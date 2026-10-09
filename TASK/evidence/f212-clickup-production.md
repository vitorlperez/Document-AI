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

## Consolidação operacional — pane-502 (2026-10-09 UTC)

Esta seção substitui as pendências Worker e a classificação de confiança do relatório histórico h-l8 acima. Skills aplicadas: inline [oc-builder, oc-stamp]. Card reivindicado por pane-502 na branch main; nenhum código de aplicação alterado.

### Worker ativado com configuração existente

Leitura direta do Worker anterior reproduziu get_settings() inválido, exit 1. Antes da intervenção, Settings com as variáveis preparadas passou (exit 0), e Celery anterior respondeu pong com 0 tarefas ativas e 0 reservadas. `railway deployment redeploy --service Worker --yes --json` (CLI oficial 5.64.1) criou `67b3c265-f0c4-4c1f-b7a0-b4dc53e5ee10`: SUCCESS, imagem/código existente `2112c8a`. Nenhum frontend/API/Beat foi reiniciado; nenhum segredo rotacionado.

No container novo, `get_settings()` válido em production, presença de banco/Redis/chave e client WorkOS sem valores, segredo HMAC >=32 e dois CIDRs host-only; SELECT 1 no banco em transação read-only, Redis PING, Celery pong (1 worker) e registro de reconcile/schedule/purge passam. URI OAuth WorkOS ausente no Worker: não é exigida por Settings e nenhuma tarefa do Worker inicia login. A primeira assertion de diagnóstico exigia indevidamente essa URI e foi corrigida; não houve segundo redeploy nem alteração de configuração para satisfazê-la.

Verificação segura real: UUID `d827d67b-47a1-4836-a1c4-ffe1b2f1acfb` comprovadamente ausente em processing_jobs por SELECT read-only. Enviado somente reconcile para esse UUID, task `90d832f6-23f1-424c-9780-39f18247ffa5`. Logs do Worker real comprovam received e succeeded; `IngestionService.claim` (`backend/app/ingestion/service.py:442`) afeta 0 linhas e retorna None; `reconcile_workspace_folder` (`backend/app/ingestion/tasks.py:250`) sai antes de qualquer provedor. A sessão fecha com rollback; nenhum registro de cliente criado/modificado, e nenhum schedule/purge disparado pelo diagnóstico. Logs da candidata, 150 linhas consultadas: 0 falhas do contrato Settings, 0 tracebacks, 1 ready. Isso prova o caminho seguro com Settings/banco/Celery, não a sincronização real de terceiros.

Rollback disponível foi conferido no deployment anterior e na candidata. Não foi necessário: a candidata passou todos os gates. Um rollback Railway restaura imagem e variáveis antigas; a anterior tinha Celery operacional, mas Settings inválido. Não seria correto chamar essa versão de plenamente saudável para tarefas. Em eventual falha, restaurar o processo anterior, re-preparar as mesmas variáveis seguras via skip-deploys e validar antes de nova tentativa, preservando dados. Não houve migração, limpeza de filas/cache ou alteração de banco/Redis.

### Reavaliação da fronteira de confiança

A observação de h-l8 é real: um POST API→frontend privado pode fornecer X-Real-IP que o frontend assina. O caller observado era a própria API, um serviço explicitamente confiável do mesmo ambiente. API/Worker/Beat já recebem em configuração o mesmo segredo HMAC; não existe nessa observação uma passagem de atacante externo não privilegiado para serviço confiável. Os CIDRs continuam exigindo peer frontend; possuir o segredo não permite ignorar esse gate diretamente, mas serviços internos já acessam o frontend privado e têm privilégios de banco/broker. HMAC identifica o frontend, sem garantir honestidade de um serviço interno confiável que o chama. Nenhum novo poder de atacante externo foi demonstrado.

O edge público foi provado seguro em h-l8, e os checks públicos foram repetidos: X-Real-IP/contexto forjado no frontend encontra o gate normal; contexto forjado na API direta é recusado 403. Não repetir o rótulo “bypass externo” ou exigir novo código/deploy como condição desta correção operacional. A premissa no comentário `frontend/app/api/proxy-headers.mjs:22` de ingresso exclusivamente edge é incompleta para rede privada: isso permanece uma limitação documentada.

Risco condicional: um componente privado sem confiança equivalente, SSRF comandável externamente ou comprometimento de serviço poderia ampliar essa entrada. Esses cenários não foram provados. Remediação proporcional: controlar membros/serviços e distribuição de segredos do ambiente, inventariar os clientes internos explicitamente confiáveis e rever isolamento/validação de entrada privada antes de admitir componentes não confiáveis. Código de segurança novo exige revisão independente antes de deploy. Nenhum código de segurança novo nesta operação.

### Docs main sem alteração de peers

Investigadas formas oficiais: [desativar autodeploy](https://docs.railway.com/deployments/github-autodeploys) e [watch paths](https://docs.railway.com/deployments/monorepo). Selecionados watch paths positivos por root para manter autodeploy de código ligado e evitar mudanças de TASK/docs dispararem publicação. Atualizados via serviceInstanceUpdate e reconsultados: Frontend `/frontend/**`, `/railway.json`, `/railway.toml`; API/Worker/Beat `/backend/**`, `/railway.json`, `/railway.toml`. Os Dockerfiles leem apenas seus roots. Se adicionar arquivos compartilhados de build no root, incluir os caminhos correspondentes. Configuração de paths não reiniciou serviços; conferido por IDs ativos.

Frontend `18cbbdd1`, API `f8311dd2`, Beat `59db34fa` preservados SUCCESS. Callback correto 401 API; readiness/session/login 200; caminho antigo 404; senhas vazias pública normal/forjada 400 antes de WorkOS; API direta forjada 403: **8/8 HTTP assertions**, exit 0. Chromium anônimo hidratado em 1280/390 px: inputs e SSO visíveis, 0 alertas/pageErrors/overflow, no-referrer header/meta, sem formulários enviados. API Settings/callback/proxy_headers continuam válidos, DNS frontend corresponde exatamente aos dois hosts confiáveis. OAuth real/state autenticado e lista permitida ClickUp continuam pendentes do usuário; painel não alterado.

Limitações preservadas: Beat não tem DATABASE_URL e não constrói Settings no agendamento atual; frontend não tem healthcheck Railway; MCP não implantado. Nenhuma dessas limitações demandou reiniciar serviços nesta operação. O resultado de publicação remota e a limpeza do acesso SSH temporário serão registrados após a conferência final.

### Prova de publicação e encerramento

Commit `d3352c523714341454203d8890b0c1d01fb70c45` publicado em origin/main, contendo ed0aaf6 e 6469c85. Railway registrou **SKIPPED para esse commit nos quatro serviços**: Frontend `a4da204f-a330-4353-8bb5-901a18886a3f`, API `4dae38cc-c458-479c-8be5-f928eec18d0d`, Worker `4a66e9af-6f06-437f-a92d-fb03fa45fbb7`, Beat `830ac675-5de0-4ae2-812d-877b001b2566`. IDs ativos/commit de código preservados como na tabela e Worker candidata 67b3c265. Não houve redeploy decorrente de docs, nem necessidade de atualizar CIDRs.

Frontend DNS com dois hosts exatamente confiáveis e **socket real frontend→API com source permitido + readiness 200** reverificados (exit 0). Configuração de variáveis dos quatro serviços comparada por digest antes/depois: igualdade completa; segredos reais conferidos ausentes nas três docs. Chave SSH temporária registrada somente para diagnóstico foi revogada, presença conferida ausente e arquivos privado/público removidos. Nenhum listener/inspector novo foi aberto. JSON e git diff --check passaram; alterações somente nestes três arquivos de documentação. Esta prova também é publicada como docs, sujeita aos mesmos watch paths; a última conferência remota fica no handoff.
