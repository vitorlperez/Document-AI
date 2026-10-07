# ai-answer-assessment-20261007 - Avaliação da resposta, judge offline e feedback

**Status:** validating

## Source and outcome
Fonte: pedido autorizado do pane-470 e spec 001 (F4, qualidade, isolamento). Fluxo fixo classify → execute/synthesize → cite → assess → finish. JEV TypeSafe já existe em `knowledge/jev.py`; o auditado usa HTTP, não SDK. Não criar dependência.

## Decisions
Autorização: usuário permite seguir recomendações sem perguntas. Shadow é padrão: jamais troca a resposta; off evita chamadas; enforce é opt-in e não será ativado. JEV usa credencial/modelo já existentes, timeout até 2 s dentro do orçamento global, estado limitado a 24 KB, nenhuma repetição ou regeneração. LLM judge apenas offline, opt-in usando OpenAI existente. Feedback substituível por mensagem, apenas dono ativo da conversa; persistir no JSON context já existente sem migração, conteúdo/response imutáveis. Não mudar retenção. Sem rollout remoto nesta tarefa.

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
- Suite final: `cd backend && .venv/bin/pytest tests/unit tests/api -q --tb=short` → 1466 passed, 4 warnings, 29.35 s, exit 0. Output completo em ai-answer-assessment-20261007/backend-tests.txt. Uma expectativa legada de igualdade de resolved_context foi atualizada para incluir assessment, sem alterar answer/citações.
- Foco: 65 passed/exit 0 (antes do último teste de whitelist; final suite inclui todos).
- Ruff em todos os módulos Python/testes/probe próprios: exit 0, All checks passed.
- Typecheck focado com flags equivalentes ao componente e tipos react/node/vite/client: exit 0. Typecheck de projeto e ESLint ficaram bloqueados lendo dependências (sample do processo aponta node::fs::Read/uv_fs_read/read); interrompidos, exit 130, não declarados limpos. Não alterar node_modules ou código alheio para contornar.
- `agent_eval --help`: flags llm-judge, judge-model, feedback-output presentes, exit 0.
- Probe APIs reais: fonte sintética suportada JEV pass, grounded .97/relevant .93/safe .96, 600.41 ms; fonte com data inventada JEV reject, .02/.07/.8, 450.12 ms. Judge OpenAI grounding 1/0, relevance 1/1, completeness 1/0, 3.960/2.928 s. Resultado em live-probe.json; não é medição de corpus de cliente/p95/calibração estatística.
- `graphify update .` AST exit 0; grafo compartilhado atualizado, labels semânticos exigem refresh separado. Grafo não entra no commit desta frente para não misturar outputs concorrentes.
- `git diff --check`: exit 0.
- Contrato JEV confirmado com implementação existente, probe real e docs primárias https://docs.typesafe.ai/introduction (Noul retorna 0–1; múltiplos juízos independentes).
- Nenhum arquivo de config/ingestion/conectores/Railway editado; retirados os únicos dois hunks de types-and-api ao detectar ClickUp naquele arquivo, preservando suas mudanças.
- Skills aplicadas: graphify, sdd-feature-delivery; skills: inline [oc-builder, oc-stamp].

## Validator report
Pendente: revisão independente; não declarar done até validação.


## Limitações e rollout
Piloto deve atribuir validação independente do commit e repetir testes relevantes. Dossiê permanece validating, não done. Não houve deploy. Não havia DATABASE_URL nem serviço de banco local ativo neste pane; faltam avaliação com corpus autorizado atual e tráfego real do piloto, testes de UI em browser e resultados de lint/full frontend. A aplicação mantém shadow e registra indisponibilidade sem credencial; não promover enforce com esses dois casos. PDFs/Canvas não necessários: entregáveis são código e evidência textual, nenhum artefato visual independente.
