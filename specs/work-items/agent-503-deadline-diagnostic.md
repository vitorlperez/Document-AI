# Missão 19 — diagnóstico local do HTTP 503 do agente

**Status:** validating — observabilidade interna implementada e testada; aguarda revisão independente. O 503 de produção continua sem causa técnica correlacionada.

## Fonte e limite da conclusão

- Spec aplicável: `specs/001-mvp-document-intelligence.md` F4, §§7, 10 e 14; `specs/work-items/chat-composer-context.md` (contrato de erro HTTP explícito); `specs/work-items/agent-follow-up-collective-reference.md` (a correção de referência coletiva não trata o 503).
- Handoff Railway `h-6r`: API reportada como implantada no commit `44a6845b4386c28030b4ff27756c98e993f25aea`; `request_complete` 503 em 2026-09-28 23:01:55.201715316Z, `elapsed_ms=25076.15`, request_id `4e3bf3c6-8613-43ed-a933-b73bbc436cd8`. `AGENT_MAX_SECONDS` não apareceu entre as variáveis ativas filtradas; default do código é 25 s. Isto é evidência forte de esgotamento do orçamento total, sem provar qual exceção o causou.
- Três eventos `semantic_question` próximos reportaram `provider_outcome=invalid_output`, mas não têm request_id. Não há traceback, status HTTP do OpenAI nem erro de transporte correlacionado à requisição 503. Não atribuir esses eventos ao 503.

## Trilha localizada

1. `backend/app/api/ingestion.py:356-374` instancia `AgentService` apenas para `scope=selection` com tools habilitadas; `:403-409` traduz `AIProviderUnavailable` para 503. Outros escopos percorrem `QuestionService` diretamente.
2. `backend/app/core/config.py:54-57` define 4 etapas, 48 KB e 25 s por default.
3. `backend/app/knowledge/agent.py:257-310` inicia o relógio antes de resolução/fallback; cada etapa compartilha `started + max_seconds`. Sem tool result, uma checagem após o loop pode lançar `document agent deadline exceeded`; caso contrário o fallback `retrieve_evidence` ainda usa o mesmo prazo. O prazo abrange chamadas sucessivas, não é renovado por etapa.
4. `backend/app/knowledge/questions.py:527-544` calcula `timeout=min(30, deadline - monotonic())` antes de cada HTTP. Se o restante já acabou, lança `AI provider deadline exceeded` sem HTTP. Um `httpx.HTTPError`, inclusive `ReadTimeout`, vira `AI provider is unavailable` com a exceção original em `__cause__`.
5. `backend/app/knowledge/questions.py:1030-1081` classifica geração válida em transporte, mas inválida em conteúdo/citações, como `invalid_generation_output`. Esta via difere de exceções HTTP; o log sozinho não permite vínculo com uma requisição sem request_id.
6. `backend/app/main.py:40-54` acrescenta request_id ao `request_complete`; `backend/app/knowledge/questions.py:1108-1126` emite `semantic_question` sem esse id. `backend/app/core/logging.py:7-27` mantém uma allowlist de campos de log.

## Reprodução sem tráfego externo

`backend/tests/unit/test_agent_deadline_diagnostic.py` usa relógio simulado, `httpx.post` substituído e nenhum banco/provedor real:

- Uma etapa de planejamento consome 25 s, retorna sem tools e ativa a checagem explícita do agente: `document agent deadline exceeded`.
- Uma etapa de planejamento consome 12 s sem chamar tool; o fallback começa uma requisição de embedding com apenas 13 s de timeout HTTP. `ReadTimeout` simulado ao fim desse restante é encapsulado como `AI provider is unavailable`, com `ReadTimeout` preservado em `__cause__`. As duas vias podem chegar à mesma tradução 503 da API.
- Com deadline já expirado, o adapter recusa a requisição antes de chamar `httpx.post`.

Essa reprodução demonstra uma possibilidade técnica no código implantado; não reproduz o estado exato da requisição Railway nem identifica seu ramo real.

## Hipótese e proposta mínima para próxima etapa

Hipótese local: etapas cumulativas (planejamento, tool e fallback de retrieval/geração) podem consumir o mesmo prazo de 25 s; a última chamada HTTP recebe só o restante e termina em 503. O exemplo determinístico confirma o mecanismo, não a causa da ocorrência em produção.

1. Primeiro, correlacionar por request_id em todas as etapas da pergunta e da chamada ao provedor. Registrar apenas `phase` enumerada, `elapsed_ms`, `remaining_ms`/faixa, `failure_kind` enumerado (`agent_deadline`, `provider_deadline_preflight`, `http_timeout`, `http_status`, `transport_error`), status HTTP numérico quando houver e contagem de chamadas. Estender a allowlist do formatter para esses campos; sem prompt, nome/trecho de arquivo, body, URL completa, headers, token ou mensagem de exceção. A instrumentação preserva o contrato de resposta.
2. Depois de obter dados correlacionados, corrigir apenas a etapa comprovada: por exemplo, evitar iniciar fallback que não cabe no orçamento, ou retornar resultado parcial autorizado quando houver evidência suficiente. O limiar, semântica de resultado parcial e eventual orçamento reservado exigem decisão de produto. Não elevar 25 s por tentativa.
3. Adicionar testes de duração cumulativa, mapeamento 503, telemetria sanitizada e escopo autorizado; validar em homologação antes de concluir sobre produção.

## Decisões de comportamento e custo em aberto

| Decisão | Por que a spec não resolve |
| --- | --- |
| Ao esgotar o orçamento, responder 503 ou devolver inventário/resultado parcial já autorizado? | A spec prevê erro explícito do provedor e evidência insuficiente, mas não define sucesso parcial por timeout de agente. |
| Reservar tempo para retrieval/fallback? Quanto e em qual etapa? | Pode reduzir a qualidade da resposta ou alterar quando o provedor é chamado. |
| Quantas chamadas ao modelo/embeddings permitir por pergunta e como contabilizar tentativas sem resposta? | Altera custo/uso e não está quantificado para o agente com tools. |
| Expor categoria de erro ao cliente ou mantê-la somente na telemetria? | Altera contrato público e ação de recuperação. |

Conforme `sdd-feature-delivery`, essas decisões protegidas devem ser confirmadas antes de código que mude comportamento/custo. A instrumentação abaixo não altera essas decisões.

## Implementação de observabilidade para validação

- Ownership desta etapa: `backend/app/core/logging.py`, `backend/app/main.py`, `backend/app/knowledge/agent.py`, `backend/app/knowledge/questions.py` e `backend/tests/unit/test_agent_observability.py`. A revisão independente permanece pendente; o autor não valida o próprio patch.
- `RequestLogMiddleware` cria `RequestTrace` em `ContextVar` por requisição e o restaura ao sair. Esse contexto fornece `request_id` a `semantic_question`, fases do agente e chamadas HTTP, além da contagem de chamadas ao provedor. O evento final da requisição inclui a mesma contagem. Teste com duas requisições sobrepostas verifica isolamento e correlação dos três eventos.
- Fases do agente e adapter HTTP emitem apenas fase enumerada, duração em ms, restante do prazo em ms quando aplicável, categoria enumerada de falha, status HTTP numérico e contagem. `JsonFormatter` inclui esses campos em allowlist. Mensagens de log são constantes; erro textual, prompt, body, cabeçalhos, URL e conteúdo de documento não entram nos novos registros.
- O adapter distingue `read_timeout`, `connect_timeout`, `http_status` (inclusive 429), `network_error` e `provider_deadline_preflight`; o agente registra `agent_deadline` e fases de planejamento, tool, inventário/finalização/fallback. A exceção e o mapeamento HTTP originais continuam iguais.
- Teste inicial de observabilidade falhou na coleta por ausência de `current_request_id` (exit 2), antes da implementação. Testes novos verificam concorrência, correlação entre eventos, categorias, status numérico, prazo/restante e ausência de sentinelas sensíveis.
- Não há alteração de API, escopo de dados, prazo de 25 s, número de chamadas, política de fallback, UI ou configuração Railway. O overhead de logs e contagem ainda não foi medido em produção; a validação independente deve revisar esse limite.

## Evidência local

- `.tools/graphify/bin/graphify query "How do question agent deadline, fallback generation, retrieval and OpenAI HTTP timeout interact?" --budget 1800`: exit 0; localizou `AgentService`, `QuestionService`, `OpenAIQuestionProvider` e os testes de prazo.
- `cd backend && ./.venv/bin/pytest -q tests/unit/test_agent_deadline_diagnostic.py tests/unit/test_document_agent.py tests/unit/test_structured_logging.py`: exit 0, 14 passed (2 avisos de depreciação preexistentes).
- `cd backend && ./.venv/bin/ruff check tests/unit/test_agent_deadline_diagnostic.py`: exit 0.
- `git diff --check`: exit 0 após a atualização do grafo.
- `.tools/graphify/bin/graphify update .`: exit 0; 3551 nós, 9447 arestas. `graphify-out/cache/last_query_stamp` já estava alterado no início do trabalho; a consulta e a atualização geraram outros deltas no diretório.
- Na fase inicial de diagnóstico não houve mudança em código de produção. Em ambas as fases, não houve UI, tráfego ao provedor real, Railway write, push ou deploy.

### Evidência do patch de observabilidade

- `cd backend && ./.venv/bin/pytest -q tests/unit/test_agent_observability.py tests/unit/test_agent_deadline_diagnostic.py tests/unit/test_document_agent.py tests/unit/test_structured_logging.py tests/unit/test_logging.py tests/unit/test_semantic_questions.py`: exit 0, 71 passed.
- `cd backend && ./.venv/bin/pytest -q`: exit 0, 359 passed, 8 skipped; quatro avisos de depreciação existentes.
- `cd backend && ./.venv/bin/ruff check app/core/logging.py app/main.py app/knowledge/agent.py app/knowledge/questions.py tests/unit/test_agent_observability.py tests/unit/test_agent_deadline_diagnostic.py`: exit 0.
- `.tools/graphify/bin/graphify update .`: exit 0 após o patch; 3579 nós, 9557 arestas.
- Revisão independente: pendente. Gate `validating`; não marcar `done` nem declarar o 503 de produção resolvido.
