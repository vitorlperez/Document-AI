# ai-answer-assessment-20261007 - Avaliação da resposta, judge offline e feedback

**Status:** validating

## Source and outcome
Fonte: pedido autorizado do pane-470 e spec 001 (F4, qualidade, isolamento). Fluxo fixo classify → execute/synthesize → cite → assess → finish. JEV TypeSafe já existe em `knowledge/jev.py`; o auditado usa HTTP, não SDK. Não criar dependência.

## Decisions
Autorização: usuário permite seguir recomendações sem perguntas. Correção de privacidade: off/false é padrão; shadow exige opt-in duplo e jamais troca a resposta; off evita chamadas; enforce é opt-in e não será ativado. JEV usa credencial/modelo já existentes, timeout HTTP configurado em 2 s por operação, sem garantia de timeout total, estado limitado a 24 KB, nenhuma repetição ou regeneração. LLM judge apenas offline, opt-in usando OpenAI existente. Feedback substituível por mensagem, apenas dono ativo da conversa; persistir no JSON context já existente sem migração, conteúdo/response imutáveis. Não mudar retenção. Rollout seguro autorizado após validação independente, a partir de worktree limpo sobre origin/main; nunca push/deploy do checkout compartilhado.

## Ownership
Worker pane-474: knowledge/agent.py, knowledge/answer_assessment.py, knowledge/agent_eval.py, api/answer_feedback.py, app/main.py (router), UI chat (tipos feedback locais; types-and-api pertence ao ClickUp), novos testes e este dossier. Não editar config.py, ingestion.py, conectores, Dockerfiles/Railway (outras frentes). Validator: piloto deve atribuir revisão independente após implementação.

## Ready checklist
- [x] Critérios, dono, escopo, isolamento e falhas conhecidos.
- [x] Decisões protegidas autorizadas no pedido.
- [x] Shadow preserva resultado e ausência de citação; offline opt-in separa custo.

## Acceptance criteria and test matrix
1. Depois de cite, assess roda antes de finish em qualquer caminho; shadow preserva resposta, citações e metadata anterior.
2. JEV aprova somente três decisões finitas [0,1] acima dos limiares; missing/malformed/timeout/oversize ficam indisponíveis, sem vazamento de conteúdo em logs; enforce recusa com evidência insuficiente.
3. Orçamento e input são limitados; sem chave/off/sem resposta não fazem HTTP.
4. Judge offline gera scores grounding/relevance/completeness válidos com prompt não confiável isolado; falha registrada e não transforma erro em aprovação. agent_eval usa a factory real (inclui JEV) e rollback após julgar.
5. 👍/👎 persistem por mensagem; repetir substitui voto; negar outra organização, usuário, mensagem user e conversa ausente. UI usa ID persistente da mensagem, accessible labels, busy/error.
6. Verificar regressão de unit/api, frontend types/lint, graphify AST update, revisão independente pelo piloto.

## Data validation
Credenciais OpenAI/TypeSafe presentes no .env local (valores nunca impressos); DATABASE_URL ausente. Provar contrato com chamadas reais limitadas e fixture pública/sintética; consultar banco local se disponível, sem inferir que credencial equivale a deployment configurado.

## Commands and results
- pytest red inicial: coleta falhou por módulo assessment ausente (exit 2), antes da implementação.
- Suite compartilhada anterior (inclui 36 testes ClickUp fora do commit): `cd backend && .venv/bin/pytest tests/unit tests/api -q --tb=short` → 1466 passed, 4 warnings, 29.35 s, exit 0. Output completo em ai-answer-assessment-20261007/backend-tests.txt. Uma expectativa legada de igualdade de resolved_context foi atualizada para incluir assessment, sem alterar answer/citações.
- Foco: 65 passed/exit 0 (antes do último teste de whitelist; final suite inclui todos).
- Ruff em todos os módulos Python/testes/probe próprios: exit 0, All checks passed.
- Frontend final: `tsc --noEmit` completo exit 0 e eslint do chat exit 0, reproduzidos por pane-474 e pane-476. Job frontend do CI 37703106636 success. O bloqueio inicial de leitura de dependências (interrupção exit 130) foi superado na release; não é limitação atual.
- `agent_eval --help`: flags llm-judge, judge-model, feedback-output presentes, exit 0.
- Probe APIs reais: fonte sintética suportada JEV pass, grounded .97/relevant .93/safe .96, 600.41 ms; fonte com data inventada JEV reject, .02/.07/.8, 450.12 ms. Judge OpenAI grounding 1/0, relevance 1/1, completeness 1/0, 3.960/2.928 s. Resultado em live-probe.json; não é medição de corpus de cliente/p95/calibração estatística.
- `graphify update .` AST exit 0; grafo compartilhado atualizado, labels semânticos exigem refresh separado. Grafo não entra no commit desta frente para não misturar outputs concorrentes.
- `git diff --check`: exit 0.
- Contrato JEV confirmado com implementação existente, probe real e docs primárias https://docs.typesafe.ai/introduction (Noul retorna 0–1; múltiplos juízos independentes).
- Nenhum arquivo de config/ingestion/conectores/Railway editado; retirados os únicos dois hunks de types-and-api ao detectar ClickUp naquele arquivo, preservando suas mudanças.
- Skills aplicadas: graphify, sdd-feature-delivery; skills: inline [oc-builder, oc-stamp].

## Validator report
Pane-476 aprovou 88441a0 e release fc0b64b sem findings bloqueantes; validação independente reproduziu 1356 unit/api na release, Ruff com excludes do CI, export_openapi --check e uma única alembic head (20261001_0027). Adversariais confirmaram HTTP zero com chave existente em defaults/opt-in incompleto/config inválida; falha de serialização preserva resposta.


## Limitações e rollout
Validação independente e smoke de produção concluídos. Rollout registrado abaixo. Não havia DATABASE_URL nem serviço de banco local ativo neste pane; faltam avaliação com corpus autorizado atual, p95 em tráfego real do piloto e teste visual de UI em browser; lint/full frontend passaram na release e CI. A aplicação mantém off/false por padrão; não promover enforce com esses dois casos. PDFs/Canvas não necessários: entregáveis são código e evidência textual, nenhum artefato visual independente.


## Revisão pane-476 e correções (2026-10-07)
Revisão 702e959: 0 críticos/5 avisos, aprovado com condições. Contagens independentes: working tree 1466 (inclui 36 ClickUp não commitados), commit isolado 1430, cherry-pick sobre origin/main 1349. Tsc completo/eslint passaram na revisão. Não confundir com baseline de release.
1. Settings inválidas: cache por processo; ValidationError degrada off/false com log sem valores; teste via factory/ask com MODE=bogus.
2. Default off + external_enabled=false; chave existente não basta. Mesmo mode=shadow isolado não envia. Estrutura local e feedback permanecem disponíveis. Runbook novo descreve dados/provedor e variáveis para Railway/Render/Docker; docs gerais/config/compose estão fora do ownership e não são sobrescritas.
3. Opt-in externo continua síncrono: adiciona latência/custo; timeout herdado é por fase. P95/custo do piloto são gate antes de mantê-lo ligado. Padrão desligado não tem chamada extra.
4. Montagem/json.dumps dentro do try; TypeError/AttributeError preservam shadow. Offline judge já tem exceções registradas por run_case, sem erro do provedor em relatório.
5. Standalone_query usada quando disponível. Sem standalone, relevância de follow-ups requer calibração antes de enforce.
Regressão red→green: quatro testes novos falharam no código anterior (transferência automática e config inválida); versão corrigida passa. Validação independente da correção aprovada pane-476; gate cumprido antes do rollout.

Correção: suite compartilhada atual 1488 passed (34.06s, exit0); contagem inclui outras frentes e não será usada como baseline de release. Ruff próprio exit0; default inspecionado off/false; graphify AST exit0. Novo relatório completo optin-tests.txt.

## Release e exceção de integração (2026-10-07)
- Release isolada em `/tmp/document-ai-assessment-release`: e2edfb5 + fc0b64b sobre main 4b5d2ae, árvore limpa, sem arquivos ClickUp/config.py/ingestion.py/Railway. Conteúdo da feature equivalente a 88441a0 aprovado.
- Checks locais frescos: unit/api 1356 passed, 4 warnings, 28.08 s (exit 0); Ruff com excludes do CI, export_openapi --check, tsc completo e eslint do chat exit 0. Contagem 1488 aplica ao checkout compartilhado/commit com ClickUp; não à release.
- CI GitHub do SHA exato fc0b64b14617edb987798c2a306daacf552c228f: run 37703106636, backend success + frontend success. Revisão independente pane-476 sem blockers.
- Decisão explícita do piloto dentro da autorização do usuário: exceção ao PR por ausência de autenticação HTTPS/GitHub; integrar por fast-forward SSH somente SHA exato aprovado com CI verde. Não usar force push, ignorar proteção ou integrar mudanças após CI sem revalidar. A skill sdd-feature-delivery e references/workflow.md exigem revisão/evidências, sem proibição normativa desta exceção.
- `git merge-base --is-ancestor origin/main fc0b64b...` exit 0 e `git push origin fc0b64b14617edb987798c2a306daacf552c228f:refs/heads/main` exit 0: main avançou 4b5d2ae → fc0b64b. Sem push do checkout compartilhado.
- Produção API: AGENT_ASSESSMENT_MODE=off, AGENT_ASSESSMENT_EXTERNAL_ENABLED=false, confirmados após integração. Worker sem overrides usa os mesmos defaults. ACTIVE_DOCUMENT_LIMIT=1500 em API/Worker foi preparado por pane-471 e entrou neste deploy; nenhuma alteração nossa nas otimizações de Railway.
- Autodeploy API/Worker/Frontend/Beat success, SHA fc0b64b; `/api/health/ready` público HTTP 200. ClickUp foi avisado do SHA e rebasará depois deste smoke; não há espera circular.
- Este registro documental posterior não altera o SHA de código aprovado/integrado. Não promover avaliação externa/shadow/enforce; legado classificador JEV continua sendo fluxo independente preexistente.

## Smoke da release em produção
- Container API de fc0b64b, configurações reais; TestClient sobre o ASGI implantado, autenticação real por cookie de sessão sintético (sem override de current_user), tenant sintético exclusivo e PostgreSQL real. Session factory ligada a transação externa com savepoints: commits da API e releituras SQL funcionam; rollback final remove toda fixture. Não ler documentos/tenants existentes.
- Pergunta sintética “Olá!” em selection/google_drive: HTTP 200; assessment.reason=disabled, external_enabled=false. Transporte externo do assessor instrumentado para falhar se chamado: 0 chamadas. O classificador JEV legado permanece configurado; a pergunta sintética pode usar esse fluxo preexistente, sem documento de cliente.
- PUT feedback up e down: 200/200, votos confirmados no transcript e por novas sessões SQL após commit em savepoint; resposta original preservada. Mensagem persistida mantém disabled/false. Rollback final confirmado por conexão SQL independente: usuário e tenant sintéticos ausentes, nenhuma fixture persistente. Script reproduzível em ai-answer-assessment-20261007/production-smoke.py; evidência compacta em production-smoke.json.
- Limite: pergunta/votos exercitados no ASGI dentro do container com PostgreSQL real, não no browser/proxy público; readiness atravessou proxy público com HTTP 200. Não afirmar teste visual de 👍/👎 nem persistência sobrevivendo rollback deste smoke.
- Primeiro ensaio devolveu 422 por selection sem providers; fixture corrigida para google_drive, sem alteração no produto. Primeiro SSH por nomes não conectou; IDs explícitos conectaram.
- pane-471 recebeu “smoke ok” e pode integrar ClickUp após revisão/CI verdes do SHA exato.

## Ressalvas da prova pontual
- production-smoke.py é reprodução descartável ligada a fc0b64b e às variáveis do container, não ferramenta reutilizável. Não mudar o gate para testar outro SHA sem validação nova.
- Consulta read-only pós-run por prefixes dos fixtures: organizations `Synthetic assessment rollout smoke%` = 0; users `assessment-smoke-%@example.test` = 0. Conexão independente confirmou ausência de resíduos PostgreSQL dos ensaios. Redis de rate limit/uso não está coberto pelo rollback SQL e não foi inspecionado/limpo neste smoke; não extrapolar ausência de resíduo para Redis.
- Revisão independente pane-476 aprovou dossier e artifacts para commit documental; ressalvas baixas incorporadas. Arquivos graphify (incluindo .rebuild.lock) não entram neste commit, para preservar fronteiras com outputs concorrentes.

## Complemento local e incidente confirmado (2026-10-07)

Pedido adicional: não confundir ausência de HTTP com avaliação semântica. A versão v2 oferecia somente três booleans estruturais; shadow/external=false produz skipped/external_disabled, não escores. Novo avaliador local v3 após cite: diagnósticos determinísticos de integridade de citações, pass/warn + issues, sem texto/IDs em metadados, sem HTTP nem alteração da resposta. semantic_grounding=not_evaluated é obrigatório: não concluir verdade/relevância/segurança com pass estrutural. Saudações/inventário/insuficiência honesta não requerem fonte documental. Tipos de marcadores: [N] e (fonte/fontes N), incluindo grupos e índices enormes sem int conversion excessiva.

Critérios adicionais: diagnosticar [99]/(fontes 1 e 99), trecho vazio, resposta documental apoiada sem fonte e resposta vazia; aprovar integridade válida; preservar resposta/citações; executar mesmo off/config inválida e sem provider; não vazar conteúdo. Red: 8 testes falharam por local_evaluation ausente. Green: 41 foco; suite isolada sobre ClickUp d48571d: 1422 passed, 4 warnings, 36.74 s. Ruff excludes CI e export_openapi --check exit0. Novo diff é answer_assessment.py, test_local_answer_quality.py, ADR/runbook/dossier; nenhum arquivo ClickUp/config.py/ingestion.py/Railway alterado. Revisão independente pendente antes de publicar o código.

Produção após deploy ClickUp d48571d: shadow/external=false foi configurado sem deploy extra e entrou no restart; smoke HTTP200, motivo external_disabled, checks probabilísticos vazios, somente local_checks. PUT up/down200 e rollback PostgreSQL confirmados. Isso NÃO foi prova de judge semântico. Novo local_evaluation será demonstrado após rollout aprovado desta correção.

Incidente confirmado pelo responsável pane-476: valores completos das chaves de produção OpenAI (projeto padrão, não admin) e TypeSafe expostos em uma saída de ferramenta de sua auditoria, transcript/contexto da sessão. Nenhum indício conhecido de uso indevido; não reabrir/reproduzir valores. Responsável verificou ausência no repo e não tem mecanismo autorizado de redação retrospectiva. Rotação é necessária, não opção hipotética.

Dependentes: mesma chave OpenAI em API/Worker/Frontend; Beat sem ambas. TypeSafe somente API; cópia no .env local usa mesma TypeSafe e deve ser substituída ou removida após revogação. OpenAI local diferente, não incluído neste incidente. Sem acesso admin de provider: OpenAI painel403/browser, nenhuma OPENAI_ADMIN_KEY no ambiente (API admin requer essa credencial); TypeSafe console/login sem sessão e nenhum mecanismo de rotação no MCP. Não inventar endpoint/admin ou usar chave padrão como admin.

Contenção aplicada com skip-deploys: API AGENT_INTENT_ENGINE=llm para cortar fluxo legado TypeSafe no próximo restart, external=false preservado. Revogar remotamente exige ação humana; retirar chave local não revoga o segredo já exposto. Não remover OpenAI de serviços ativos sem replacement e provocar indisponibilidade.

Ação humana mínima: criar novas chaves nos painéis OpenAI e TypeSafe e atualizar, via UI segura do Railway (não chat/log), OPENAI_API_KEY em API/Worker/Frontend e TYPESAFE_API_KEY em API. Avisar que replacements estão aplicados; operador executa restart/verifica readiness, pergunta e dependentes; revogar antigas nos dois painéis em seguida e conferir uso no período. Overlap minimiza downtime mas exposição só termina com revogação. AGENT_INTENT_ENGINE=llm é contenção de provider legado; habilitar TypeSafe shadow/external não é necessário para entrega local e permanece uma opção dependente de consentimento específico. Judge semântico OpenAI offline já existe; torná-lo online é evolução separada com custo/latência/calibração explícitos.

Fontes primárias: https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/projects/subresources/api_keys/methods/delete (admin key necessária); https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety (rotacionar chave exposta); https://docs.typesafe.ai/introduction/quickstart (chave no dashboard). Nenhum valor, fingerprint ou segredo neste registro.

Revisão independente fe70334: 1422 unit/api, 41 foco, Ruff CI e OpenAPI OK; adversariais confirmam off/shadow/enforce external=false HTTP0 e diagnósticos locais pass/warn. Aviso de robustez excerpt=None reproduzido red (AttributeError em off); correção protege avaliação local com captura de exceção e outcome=error/evaluation_failed sem conteúdo, preserva entrega; teste inclui default off. Baixos documentados: [2024] ambíguo pode dar warn, grupo [1,99] não reconhecido pelo contrato. Rotação ainda exige painel humano; status permanece validating até concluir incidente.
