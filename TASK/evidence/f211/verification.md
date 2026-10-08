# F-211 — Evidência final (h-ks/h-kr/h-kq, pane-491)

Correção local concluída e verificada em 08/10/2026. Handoffs h-ks, h-kr e h-kq lidos integralmente; o fullText h-ks contém **duas médias**, ambas corrigidas. Nenhum commit, publicação, configuração externa, rebase ou e-mail real. skills: inline [oc-builder, oc-blackbox, oc-stamp]. Este relatório substitui a evidência anterior de fila durável, removida nesta correção.

## Resumo de código para a última revisão independente

| Superfície | Resultado e ponto de revisão |
| --- | --- |
| backend/app/api/auth.py | Reset confirma a senha no WorkOS, procura o subject estável na AuthIdentity, revoga todas as UserSession desse usuário e persiste antes da resposta. Sem revogação adicional no WorkOS, marcador ou bloqueio de login/callback. Mantém force_reauthentication, limpeza dos cookies, retorno seguro e não autentica no reset. |
| backend/app/identity/auth.py | Remove gateway.revoke_user_sessions redundante. Mantém revoke_provider_session no logout e IdentityService.revoke_user_sessions local. Inclui Radar email/SMS e nomes do SDK, além de desafio 4xx com token pendente. Credenciais/código inválidos, 429 e 5xx são erros, com prioridade sobre fallback. |
| backend/app/identity/models.py, revocations.py, alembic/0028, ingestion/tasks.py | Modelo, módulo de fila, migração nunca aplicada externamente e tarefa/Beat removidos. models.py/tasks.py e testes de migração/Beat voltam ao estado anterior à fila. Head único 20261001_0027. |
| backend/app/core/config.py | Model validator exige segredo e CIDRs não vazios em produção na inicialização. Field validators rejeitam segredo curto/branco, CIDRs inválidos e /0. Erros escondem input/segredos. O padrão local development permanece; ENVIRONMENT=production deve ser explícito. Settings compartilhado exige essas variáveis também nos demais serviços de produção que o carregam. |
| frontend/app/api/proxy-headers.mjs | Só assina/exige contexto para caminho upstream /auth/*. Allowlist continua descartando headers forjados em qualquer caminho; /api/session → /me, healthcheck e demais APIs não exigem ingress IP. route.ts não foi alterado nesta correção. |
| frontend/app/product/custom-login.tsx, product-app.tsx | Remove apenas estado/resultado/mensagem/query de revogação pendente. Não muda layout, estilo, cadastro sem senha, reenvio, fallback, no-referrer ou token em memória. |
| testes | Cobertura de múltiplas sessões locais, inclusive expirada, previamente revogada, duas ativas, outra conta intacta e login novo por senha/callback após reset; reset sem identidade local; produção na importação real da API; Radar via SDK 10.3/HTTP interceptado; isolamento de rotas do proxy. Fixtures de produção receberam configuração válida para preservar o objetivo de CSRF/CORS/keyring/intent. Testes keyring isolados do .env local. |
| docs | Contrato permanente sem dados efêmeros de demo, sem fila/migração exigida, com configurações da inicialização e limitação do runtime. Dados locais somente neste diretório de evidência. |

Diff focado desta rodada: [final-correction.diff](final-correction.diff), incluindo arquivos previamente não rastreados e a remoção de 0028. Não inclui o grafo gerado nem reconta todo o login anterior; compare-o com h-kr. Resumo de arquivos: [final-diff-files.json](final-diff-files.json). Não há commit a revisar; a entrega é a árvore compartilhada atual.

## Verificações frescas

Comandos exatos, cwd, saída e exit code de pytest/Node/tsc/ESLint/Ruff: [final-checks.json](final-checks.json).

| Comando | Exit | Resultado |
| --- | --- | --- |
| Pytest nos 15 arquivos pertinentes listados em final-checks.json | 0 | **179 passed**, 0 falhas; aviso de depreciação AnyIO/Starlette preexistente |
| Node nos 5 arquivos de auth/proxy/session/landing | 0 | **15 pass**, 0 fail |
| cd frontend && npx tsc --noEmit | 0 | Sem erros |
| ESLint nos arquivos frontend de auth/proxy/runtime/testes | 0 | Sem erros |
| Ruff nos arquivos backend modificados e fixtures de produção | 0 | All checks passed |
| cd frontend && VITE_API_BASE_URL=/api npm run build | 0 | Build complete, 5 etapas; aviso informativo vinext de classificação estática de rotas |
| cd backend && DATABASE_URL=postgresql+psycopg://test:test@localhost/test .venv/bin/python -m alembic heads | 0 | **20261001_0027 (head)**; SQL offline também coberto pelo pytest |
| backend/.venv/bin/python TASK/evidence/f211/proxy_smoke.py | 0 | Cliente 1: 60 tentativas 400, seguinte 429 com Retry-After; cliente 2 continua 400; ausência ingress em auth 503; direto forjado 403; session 200/null, health 200, me 401 sem ingress |
| node TASK/evidence/f211/browser_smoke.mjs | 0 | **6 fluxos**, 1280/390/320 px reais sem overflow, chunks funcionais, nenhuma falha de sessão inicial |
| graphify update . | 0 | AST-only: **7678 nós, 21752 arestas, 512 comunidades**; aviso de rótulos de comunidade desatualizados; sem chamada LLM |
| git diff --check | 0 | Sem whitespace errors |

Antes da correção, os novos testes produziram 17 falhas de Settings/Radar/reset (mais 2 erros de teardown decorrentes de pytest.fail na chamada redundante). O comando inicial red usou redirecionamento + tail, cujo wrapper saiu 0; a saída pytest registrou as falhas. Node reproduziu a exigência indevida de IP em /me com 1 fail/4 pass, exit 1. As mesmas regressões passam no código final. Um erro inicial de fixture de cookie sem domínio foi corrigido usando o domínio real do TestClient; não foi defeito do app.

Durante a preparação: Alembic chamado do cwd errado (255) e preview sem PYTHONPATH (1) foram corrigidos nos comandos. Ruff exigiu check=False no subprocess de startup; corrigido e reexecutado (0). As duas primeiras tentativas da sonda auxiliar tiveram ReadTimeout ao consultar /api/session; uma terceira foi iniciada antes de a API estar pronta e recebeu 502. A causa dos timeouts não foi confirmada. A reprodução isolada da mesma sequência e 66 probes de sessão seguidos passaram; a sonda completa final após readiness também passou. Nenhuma correção de runtime foi feita; mantenha esta ocorrência registrada para a revisão, sem atribuir-lhe causa comprovada. Os servidores auxiliares 3118/8118 foram encerrados.

## Contratos e limites

A referência oficial confirma que reset revoga automaticamente todas as sessões ativas WorkOS; por isso a segunda revogação/fila foi removida. O app continua responsável pelas sessões locais opacas, que não são sessões gerenciadas pelo provedor. [Password reset](https://workos.com/docs/reference/authkit/password-reset).

Os nomes documentados de Radar são radar_email_challenge e radar_sms_challenge; nomes do SDK e desafios pendentes seguem para o AuthKit hospedado. Isso só permite iniciar o fluxo hospedado, não conclui/valida Radar real. [Authentication errors](https://workos.com/docs/reference/authkit/authentication-errors).

Sem migração de autenticação nova: 0028 nunca foi aplicada externamente, conforme autorização recebida. Não há tabela/fila/job de revogação para instalar ou operar. O scheduler Beat de ingestão existente foi preservado.

## Prévia funcional e reprodução

**http://localhost:3117/login**, build reconstruído; frontend e API de demonstração reiniciados para carregar o código final. Frontend Wrangler em 3117 e preview_gateway.py em 8117, com logs fora do repositório em /tmp/f211-preview-frontend.log e /tmp/f211-preview-api.log. Gateway determinístico/SQLite: **sem WorkOS real, sem envio de e-mails**.

Para subir em terminais separados na raiz do projeto:

```sh
PYTHONPATH=backend backend/.venv/bin/python TASK/evidence/f211/preview_gateway.py > /tmp/f211-preview-api.log 2>&1
```

```sh
cd frontend
API_UPSTREAM_URL=http://127.0.0.1:8117 npm run start -- --port 3117 > /tmp/f211-preview-frontend.log 2>&1
```

Antes dos smokes, aguarde /health/live da API e /login do frontend retornarem 200. Não rode build novamente sem reiniciar a prévia: Wrangler pode manter referência aos chunks antigos.

Dados **somente de demonstração local**: demo@example.com + preview-password; verify@example.com + mesma senha e código 123456; radar@example.com + mesma senha demonstra fallback; reset ?token=preview-only. browser_smoke.mjs usa o Playwright do runtime Codex instalado e Google Chrome em /Applications, caminhos declarados no script; não há e-mail externo.

Reprodução da sonda assinada, em terminais separados:

```sh
PYTHONPATH=backend PREVIEW_SIGNED_PROXY=1 PREVIEW_API_PORT=8118 PREVIEW_FRONTEND_URL=http://localhost:3118 backend/.venv/bin/python TASK/evidence/f211/preview_gateway.py > /tmp/f211-proxy-api.log 2>&1
```

```sh
cd frontend
API_UPSTREAM_URL=http://127.0.0.1:8118 AUTH_CLIENT_IP_SOURCE=railway AUTH_PROXY_SECRET=test-only-proxy-secret-at-least-32-chars npm run start -- --port 3118 > /tmp/f211-proxy-frontend.log 2>&1
```

Depois da readiness dos dois servidores, rode proxy_smoke.py uma vez; reinicie a API para zerar limites antes de repetir. Contexto Railway é simulado. Não use esse segredo fictício na infraestrutura.

Screenshots desktop/mobile/320 atualizados e desktop/390 inspecionados: [1280](login-1280.png), [390](login-390.png), [320](login-320.png). Resultados: [browser-smoke.json](browser-smoke.json), [proxy-smoke.json](proxy-smoke.json). Cadastro sem campo de senha, reenvio simulado, token retirado antes do submit e ausente no Referer; credencial inválida permanece alerta e desafio Radar oferece fallback sem sessão.

## Pendências externas precisas

1. **Admin WorkOS** no ambiente do WORKOS_CLIENT_ID para conferir e-mail/senha habilitado, verificação obrigatória, Emails → Configuration → e-mails gerenciados de verificação/reset ligados; Applications → Redirects → Password reset URL = origem pública + /login; callback existente preservado. O app não implementa remetente alternativo para AuthKit.
2. **Conta de teste e caixa controlada/designada** para provar entrega, cadastro/endereço existente, código e reenvio com o mesmo token pendente, reset e invalidação de sessões antigas. A compatibilidade do código reenviado com o token pendente continua lacuna de contrato, exige teste real. Conta/organização com MFA, IdP/usuário SSO e Radar habilitado conforme política para os métodos avançados. A nova rodada não chamou nenhuma API WorkOS real nem enviou e-mail; GET da rodada anterior só provou leitura/conectividade.
3. **Infraestrutura**: ENVIRONMENT=production explícito; segredo aleatório ≥32 caracteres igual no frontend/API e configurado nos processos que carregam Settings em produção; AUTH_TRUSTED_PROXY_CIDRS válidos e estritamente delimitados dos peers do frontend; AUTH_CLIENT_IP_SOURCE=railway no frontend; API_UPSTREAM_URL, PUBLIC_APP_URL e Redis corretos. Validar ingress que substitui X-Real-IP, impossibilidade de bypass, peers reais e logs que não gravem ?token=. Start command ASGI, inclusive override Railway, com --no-proxy-headers. Nada configurado externamente nesta rodada.
4. **Runtime/branch**: checkout frontend Wrangler diverge da main que usa vinext start. Não foi feito rebase, nem alterado Dockerfile/package.json/sites-env/runtime por essa divergência. Reexecutar smoke no artefato/runtime final antes de produção. Não há migração 0028 nem dependência de credenciais WorkOS/Beat para reset; serviços existentes de ingestão continuam com suas exigências próprias.

Outras baixas do fullText h-ks fora do escopo escolhido (por exemplo granularidade IPv6 e UX de recarregar reset) não foram ampliadas nesta correção.
