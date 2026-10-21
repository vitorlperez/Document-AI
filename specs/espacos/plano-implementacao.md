# Espaços com acesso por pessoa + visão unificada — Plano de Implementação

> **STATUS (2026-10-19): implementado na branch `feat/espacos`; integrado e verificado.** O texto abaixo é o plano original; o que a implementação mudou está em **"Estado da implementação"**, logo após o índice. `enforce` só deve ser ligado por organização, com `python -m app.spaces.rollout` (T-J1), depois de uma janela `shadow` sem divergência.
>
> **ATUALIZAÇÃO (2026-10-20): não existem mais os modos `off`/`shadow`.** Decisão do dono: Espaços sempre em `enforce` (ver ADR-0021, “Decisão de 2026-10-20”). Tudo neste plano sobre `spaces_resolver_mode`, rollout por modo, `shadow`/divergência, `403` legado em `off` e `SPACES_NEW_ORG_MODE` é histórico: a coluna foi removida pela migração 0038 (que também garante “Geral” com todas as pessoas e pastas sem Espaço) e o CLI `python -m app.spaces.rollout` agora só tem `report`.

**Goal:** o admin da empresa (ou o responsável pelo Espaço) habilita/desabilita pessoas em Espaços específicos, e quem tem acesso a vários Espaços enxerga **uma visão única** — biblioteca, busca e chat/agente sobre a **união** dos seus Espaços — com filtro opcional por Espaço e selo de Espaço em cada documento/citação.

**Architecture:** três tabelas novas (`spaces`, `space_members`, `space_folder_grants`) ligam pessoas a **escopos de sincronização já existentes** (`WorkspaceFolder`, N:M, sem copiar conteúdo). Um **resolvedor único** `SpaceAccessResolver` devolve, em uma consulta, o conjunto de `workspace_folder_id` que a pessoa pode ler (e, para cada pasta, *quais* dos Espaços dela a concedem); `LibraryService.question_contexts` e `WorkspaceService.require_member_access` passam a delegar a ele, de modo que chat, agente, API pública, MCP, automações, evidência e árvore herdam o filtro sem reescrever a recuperação. Conteúdo derivado já gravado (histórico, `last_answer`, notificações, resultados de automação) é **ocultado na leitura pela proveniência** (`document_id` das citações) e purgado por job.

**Stack:** FastAPI + SQLAlchemy 2 + Alembic (backend, `pytest`, SQLite nos unitários/Postgres opcional via `TEST_DATABASE_URL`), Next.js/React (frontend, testes `node --test tests/*.test.mjs`), `graphify update .` depois de cada tarefa de código.

Data: 2026-10-19 · Base: `main` @ `62062cc` · **Este documento é só plano: nenhum código de produção foi alterado e nenhum commit foi feito.**
Ponto de partida: `specs/research/comunicacao-espacos-viabilidade-2026-10-15.md` (daqui em diante **[VIAB]**). Convenções iguais às de [VIAB]: **[FATO]** = verificado em código (`path:linha` de hoje); **[INFERÊNCIA]** = dedução; **[ESTIMATIVA]** = julgamento.

## Índice

0. Decisões do dono e escopo
1. Resposta curta: como resolvemos a visão unificada
2. Estado atual ancorado no código (o que muda em relação a [VIAB])
3. Modelo de dados e migrações
4. Resolvedor único e todos os pontos que precisam usá-lo
5. Papéis
6. Drive: pastas do robô viram fontes atribuíveis a Espaços
7. UX: visão unificada, filtro, gestão de membros
8. Revogação e ocultação de derivados
9. API pública / MCP / chaves de API
10. Escala da biblioteca (spike)
11. Migração dos dados existentes
12. Plano de tarefas
13. Ordem, dependências e estimativa
14. Riscos e autorrevisão
15. Handoff de execução
Anexo A. Rascunho do ADR-0021 (versão canônica em `specs/adr/ADR-0021-espacos-acesso-por-pessoa.md`)


## Estado da implementação (desvios do plano)

Todos os blocos A–J foram entregues na branch `feat/espacos`. Diferenças em relação ao texto do plano:

- **Teto de documentos:** 3.000 documentos ativos por organização (`Settings.active_document_limit`), não 500. O teto agora bloqueia a ingestão (`[LIM-0][M8]`).
- **Modos do resolvedor (`off`/`shadow`/`enforce`):** em `shadow` o legado nunca quebra (erro ou `space_ids` desconhecido do caminho novo só é registrado); o filtro `space_ids` estreita também em `off`/`shadow` e filtros aninhados se **intersectam**; valor vazio ou desconhecido é tratado como `enforce` (falha fechada). Divergência em `shadow` vai para o log (`spaces.shadow_divergence`, só contagens).
- **404 uniforme em pastas:** `403` vira `404` para pasta inalcançável apenas em `shadow`/`enforce`; em `off` o contrato legado (403) permanece (B3).
- **`access` obrigatório:** `documents_for_nodes`, `workspace_provenance`, `document_provenance` exigem `access`; `None` é visão de sistema e só existe em `indexed_documents_under(system_view=True)` (administração, depois da checagem de admin). Teste `test_spaces_call_sites.py` proíbe `access=None` em código de aplicação (T-J2).
- **Catálogo (A1):** `catalog_file_snapshots` e `validate_references` passam a exigir a pasta do nó em `access.folder_ids`.
- **`reach` das chaves de API:** `POST` e `GET /api-keys` devolvem `reach: {spaces: [{id, name}], documents: N}` calculado para o **criador** de cada chave (chaves revogadas não trazem `reach`). `GET /organizations/{id}/people` devolve só `{user_id, email}`.
- **Convites e arestas (C7):** convite com `space_ids` inválidos cai no Espaço padrão; o último responsável de um Espaço não pode ser removido nem rebaixado; inserções concorrentes de membro/concessão são idempotentes.
- **Backfill 0036** completa "Geral" de forma idempotente (também após `downgrade -1` + `upgrade`), com inserções em lote. Migração 0037 acrescenta `pg_trgm` em nomes da biblioteca e índice em `documents(organization_id, external_file_id)`.
- **Escala (T-D0):** a CTE recursiva (v1) cumpre o orçamento até 50k arquivos; **T-D6 (`library_node_folders`) não foi liberada** (ver §10.3).
- **T-J1 (`python -m app.spaces.rollout`):** comandos `status`, `report`, `off|shadow|enforce --organization`, `enforce --all-clean`. `enforce` é recusado (exit 2) se houver pasta sem Espaço ou pessoa ativa sem Espaço, salvo `--force`; `report` calcula a divergência legado×Espaços na hora (só contagens). A troca de modo é registrada em log estruturado (a tabela de auditoria exige um usuário autor, que a CLI não tem).
- **T-J2:** a lista viva é `specs/espacos/call-sites.md` (por arquivo, não por linha).
- **Fora do que foi entregue:** coluna "Espaços" por pasta na tela de Integrações; nomes de pastas do escopo de uma automação ainda são exibidos sem filtro por Espaço (só nomes, sem conteúdo).

---

## Global constraints

- **Vocabulário:** "Espaço" = o **novo** agrupamento com pessoas (D-3 de [VIAB]). O conceito atual que a UI chama de "espaço" (`WorkspaceFolder`, escopo de sincronização) passa a ser "**Pasta conectada**" na tela; no código continua `WorkspaceFolder`. Nas tabelas novas: `spaces`, `space_members`, `space_folder_grants`.
- **Fail-closed (I1 de [VIAB]):** sem resolução de Espaço, zero conteúdo; erro do resolvedor nunca "abre".
- **Acesso a conteúdo** = membership ativa na organização ∧ membership ativa no Espaço ∧ concessão da pasta ao Espaço não revogada ∧ pasta consultável (`folder_is_queryable` e o filtro de `access_lost` de `api/evidence.py:31`, que **continuam como hoje**). **Papel de admin não entra na fórmula** (D-2).
- **Sem cópia:** um Espaço *referencia* `WorkspaceFolder` (N:M). Nenhuma tabela de conteúdo ganha `space_id`.
- **Revogação:** leitura viva = efeito no próximo request; derivados persistidos = ocultos na leitura imediatamente e purgados em ≤ 24 h (premissa de [VIAB] §6).
- **Existência não vaza (I7):** fora do alcance responde 404/ausente, nunca "sem permissão para o Espaço X".
- **Migração no dia do deploy não muda comportamento:** um Espaço "Geral" com todos os membros ativos e todas as pastas.
- **Limites** (`Settings.active_document_limit=3000` — antes `ACTIVE_DOCUMENT_LIMIT=500` —, `MONTHLY_LIMITS`; commit `[LIM-0][M8]`) continuam por organização; consumo por Espaço só informativo.
- **Revisões Alembic:** próxima = `20261019_0035` (head atual `20261014_0034`, `backend/alembic/versions/20261014_0034_drive_link_parents.py`); padrão de arquivo `YYYYMMDD_NNNN_nome.py`, `revision`/`down_revision` como string.
- **ADRs ficam em `specs/adr/`**, formato `ADR-00NN-slug.md`; último usado = **ADR-0020**; **0021 está livre** (verificado: não existe arquivo `ADR-0021-*`; apenas [VIAB] já o reserva para estas decisões).
- **Fora de escopo (decisão do dono):** CASA/OAuth `drive.readonly` (o Drive em produção segue com o robô — conta de serviço com quem o cliente compartilha pastas) e integrações de comunicação (WhatsApp/Slack/Teams). **Não** alterar código de produção neste plano de planejamento; **não** commitar.

---

## 0. Decisões do dono e escopo

| # | Decisão | Efeito neste plano |
|---|---|---|
| P-1 | Drive em produção segue **por enquanto** com o robô (service account; o cliente compartilha pastas com o robô). CASA/OAuth `drive.readonly` fica fora. | A unidade atribuível a Espaço no Drive é a **pasta compartilhada com o robô** (`DriveFolderLink` ↔ `WorkspaceFolder`). Ver §6. A granularidade é a do compartilhamento, porque o robô **rejeita sub-pasta de pasta já ligada** (`NestedInLinked`, `google_drive_sa_service.py:230-243`). |
| P-2 | WhatsApp/Slack/Teams ficam para depois. | Nada de `source_item_acl`, `chat_units`, `public_in_source` etc. de [VIAB] Fases 2–4. O modelo deixa espaço para eles (concessão por *pasta/escopo de sync*, `disclosure` JSON), sem implementá-los. |
| P-3 | Requisito central: **quem está em vários Espaços não pode ficar trocando de Espaço.** | A visão é **unificada por padrão** (§1): biblioteca, busca e chat operam sobre a união; Espaço é **filtro opcional + selo**, nunca um "modo" que o usuário precisa escolher antes de procurar. |

Decisões herdadas de [VIAB] §13 que este plano **assume** (aceitas por padrão; o ADR-0021 as registra): D-2 admin ≠ leitor; D-3 nome "Espaço" para o novo conceito e renomear o legado; D-4 sem cópia (N:M); D-7 limites por organização. D-0/D-1/D-5/D-6 (chat) estão fora de escopo por P-2.

---

## 1. Resposta curta: como resolvemos a visão unificada

**Proposta.** Não existe "Espaço ativo". Existe o **conjunto acessível** `U(pessoa)` = ⋃ das pastas conectadas concedidas aos Espaços em que a pessoa é membro. Todas as superfícies leem `U` **por padrão**; o **filtro por Espaço** é um estreitamento opcional (`space_ids`) que o servidor sempre intersecta com os Espaços da pessoa; e cada documento/citação traz o **selo dos Espaços da pessoa** que o concedem.

| Superfície | Comportamento unificado | Filtro opcional | Indicação de Espaço |
|---|---|---|---|
| **Biblioteca** (árvore) | Uma árvore só, como hoje (raiz por ferramenta); só aparecem nós com pelo menos um arquivo em `U`. | Chips de Espaço no topo; alternativa "Agrupar por Espaço" (raízes virtuais = Espaços). | Selo(s) no arquivo/pasta e no painel de detalhes. |
| **Busca** | Uma caixa de busca sobre `U` (nomes hoje; conteúdo via recuperação, mesmo conjunto). | Mesmo filtro (chips) + sintaxe visível "em: RH". | Selo em cada resultado. |
| **Chat/agente** | Pergunta sobre `U`; faixa fixa "Procurei em: todos os meus Espaços (3)". | Seletor multi-Espaço ao lado do seletor de ferramenta; menções (`@arquivo`) já estreitam. | Selo em cada citação; resposta que cruza Espaços diz quais. |
| **API pública / MCP** | Chave/conexão vinculada a um usuário ⇒ `U(usuário) ∩ node_ids da credencial`. | Parâmetro opcional `space_ids` (só estreita). | Campo `spaces` em `/sources`, `/search`, citações. |

**Por que é a melhor solução (justificativa):**

1. **A recuperação já é "uma consulta sobre um conjunto de pastas".** [FATO] `QuestionService.ask` e `RetrievalService._scoped` filtram por `workspace_folder_id IN (...)` (`knowledge/retrieval.py:52-64`, `knowledge/questions.py:1138-1198`), e o chat com "todas as ferramentas" **já** consulta a união de todos os escopos da organização. Espaços só redefinem *quais* pastas entram no conjunto — a união sai de graça e **sem N consultas**. Trocar de Espaço e refazer a pergunta é um problema de produto, não de motor.
2. **Um "Espaço ativo" cria exatamente o erro que o dono quer evitar:** a pessoa procura no Espaço errado, não acha e conclui que o documento não existe. Com `U` por padrão, não achar significa não existir *para ela*.
3. **O filtro nunca amplia.** O servidor calcula `U` e só depois aplica `space_ids ∩ espaços_da_pessoa`; um `space_id` alheio é descartado (ou 404 na rota de detalhe) — mesma regra "credencial ⊆ usuário" que as chaves de API já usam (`library/service.py:1158-1183`).
4. **Selo calculado na leitura, por pessoa.** O Espaço de um documento é derivado de `pasta → concessões → membros`, então (a) não há duplicação de dados, (b) revogação reflete no próximo request e (c) o selo só lista Espaços **da própria pessoa** (nunca revela a existência de um Espaço de que ela não participa).
5. **Conversas não ficam presas a um Espaço.** O histórico é ocultado pela proveniência das citações (§8), então a mesma conversa pode atravessar Espaços sem criar um segundo mecanismo de segurança.

**Alternativas rejeitadas:** (a) *alternar Espaço* — rejeitado pelo dono; (b) *uma organização por Espaço* ([VIAB] §5.6) — serve de ponte sem código, mas duplica fontes/quota e não combina Espaços; (c) *N consultas, uma por Espaço, mescladas* — o spike mostra que a pergunta org-wide já custa 417 ms com 44 instruções SQL para só 10 escopos (§10), N chamadas multiplicariam isso; (d) *copiar documentos por Espaço* — duplica chunks/embeddings e o teto de documentos.

**Ressalva de desempenho que muda o desenho (§10):** o caminho "união" paga hoje uma consulta de `Membership` **por pasta** (`WorkspaceService.require_member_access` dentro de um laço em `questions.py:1137-1143`; o spike registra a mesma forma repetida em `repeated_shape` da linha "org-scope question"). O resolvedor único elimina isso (uma consulta para todas as pastas); é requisito, não otimização opcional.

---

## 2. Estado atual ancorado no código (o que muda em relação a [VIAB])

Releitura focada nos pontos que o plano toca. Tudo **[FATO]** de hoje (working tree em `62062cc`).

| Fato | Evidência | Consequência para o plano |
|---|---|---|
| O "ponto de estrangulamento" de acesso é `question_contexts`: todas as pastas da organização, sem filtro de pessoa, com `require_member` só checando membership. | `library/service.py:911-964` (query sobre `WorkspaceFolder`⋈`DataSource` por `organization_id`) e `:162-171` | Trocar a origem de `WorkspaceFolder` por "pastas do resolvedor" resolve chat, agente, API, MCP, evidência, automação — 4 chamadas internas (`library/service.py:776,1015,1080,1129`) e 8 externas em 7 arquivos (`questions.py:1063,1145`, `overview.py:67`, `api/library.py:121`, `api/public_v1.py:181`, `api/evidence.py:25`, `automations/executor.py:53`, `mcp_server/tools.py:71`). |
| `WorkspaceService.require_member_access/folders` checam só `Membership.is_active`; usados por perguntas de pasta única, busca por pasta, consultas salvas. | `workspaces/service.py:34-45`; `knowledge/questions.py:1138`; `knowledge/search.py:61`; `audit_usage/service.py:26,29,44` | Segundo ponto de entrada que **precisa** delegar ao resolvedor (hoje ele ignoraria Espaços e abriria tudo). |
| **A árvore da biblioteca e a busca por nome NÃO passam por `question_contexts`.** `roots`, `children`, `search_page` só filtram por organização (e `children` ainda mescla raízes da mesma ferramenta via `_same_tool_roots`). | `library/service.py:173-184, 230-254, 542-559` | É o **maior trabalho novo**: a UI de biblioteca vaza tudo mesmo que o chat seja filtrado. Precisa de filtro próprio (§4.3, §10). |
| `catalog_*`, `authorized_catalog`, `mention_candidates`, `resolve_question_selection` já derivam de `question_contexts` + nós carregados em memória (`_selection_nodes` carrega **todos** os nós da organização). | `library/service.py:985-1031, 1073-1156` | Herdam o filtro de pastas; porém o carregamento integral de nós é um custo de escala (§10). |
| Chave de API exige Owner/Admin; MCP aceita qualquer membro; ambos usam `node_ids` como **estreitamento** e passam por `ScopedAccess` → `resolve_question_selection`. `GET /sources` e MCP `list_sources` usam `question_contexts`. | `access/principal.py:76-86`; `mcp_server/auth.py:84-93`; `access/scope.py`; `api/public_v1.py:181`; `mcp_server/tools.py:71` | O alcance de qualquer credencial vira `U(usuário vinculado) ∩ node_ids` **automaticamente** assim que `question_contexts` mudar; falta só o teste (admin ≠ leitor) e expor `spaces`. |
| Sem concessões: `uniform_access_confirmed` é um booleano gravado e exigido na seleção de escopo, **nunca lido** como regra de acesso. | `workspaces/service.py:80-81, 94`; `workspaces/models.py` | Mantém-se a coluna; muda o *texto de ciência* ("todos os membros do(s) Espaço(s) de destino poderão ver"). |
| `SavedQuery` é presa a **uma** `workspace_folder_id` (herança de antes das perguntas multi-escopo). `refresh_followed_queries` re-pergunta como o usuário e grava `last_answer` (texto + `document_ids`). | `audit_usage/models.py` (`SavedQuery`); `notifications/followed.py:55-90` | Derivado a ocultar/limpar (§8). Consulta salva com pasta fora de `U` deixa de listar/rodar. Migrar consultas salvas para escopo multi-pasta/Espaço é **fora do MVP** (anotado como follow-up). |
| `ConversationMessage.context/response` guardam `mentions`, `providers`, `references` e `citations` (com `document_id`). `GET …/conversations/{id}` devolve tudo sem reavaliar. | `knowledge/models.py` (`ConversationMessage`); `api/ingestion.py:409-434`; `knowledge/agent.py:1455-1475` (`_answer_provenance`) | A proveniência para ocultar **já existe** nas citações; basta reconferir na leitura. |
| `serialize_question_result` monta `citations[]` (document_id, chunk_id, nome, trecho, página, `source_url`, `source_provider`) — ponto único para acrescentar `spaces`. | `knowledge/presentation.py:38-66` | Selo de Espaço por citação entra aqui (e em `public_v1`/MCP). |
| `LibraryContext`/`GET /library/question-contexts` já alimentam o seletor de ferramentas do chat (`QuestionScopePicker`). | `library/service.py:43-52`; `api/library.py:108-136`; `frontend/app/question-scope.tsx` | Estender com `spaces: [{id,name}]` por contexto: o seletor de Espaço do chat sai do **mesmo** payload (zero chamada extra). |
| O robô do Drive cria **um `WorkspaceFolder` por pasta compartilhada** (1:1 com `DriveFolderLink`) via `select_scope(... uniform_access_confirmed=True)`; `NestedInLinked` impede sub-pasta de pasta já ligada; perda do compartilhamento move o escopo para `status="access_lost"` (já escondido de `scoped_document`). | `integrations/google_drive_sa_service.py:296-345, 217-243, 461-475`; `api/evidence.py:21-37`; `integrations/google_sa_models.py` (`DriveFolderLink`) | A concessão a Espaço nasce **no ato de ligar a pasta** (§6); `access_lost` entra na fórmula do resolvedor (precedente já existente). |
| Na base original, `ACTIVE_DOCUMENT_LIMIT = 500` só aparecia em `usage_summary` (exibição). **Atualizado:** o teto é hoje **3.000 documentos ativos** (`Settings.active_document_limit`, unificado com os limites mensais em `[LIM-0][M8]`). | `audit_usage/service.py:15, 88-93` (grep `ACTIVE_DOCUMENT_LIMIT` em `backend/app`) | O teto (3.000 hoje) não restringe a escala do desenho; a escala "real" é o que o spike mede (§10). |
| `AuditLog(organization_id, actor_user_id, action, target_type, target_id)` — `target_id` UUID obrigatório; `_audit` em `api/access_admin.py:58`. | `audit_usage/models.py:21-33`; `api/access_admin.py:58-61` | Eventos `space.*` reutilizam `AuditLog` (sem tabela nova). |
| Testes de referência: `tests/access_helpers.py` (`seed_tenant`, `mint_key`, `bearer`), `tests/unit/test_scope_invariant.py`, `test_agent_revocation_*`, `tests/api/test_public_v1.py`, `tests/api/test_mcp_server.py`, `tests/unit/test_company_library.py` (fixture SQLite em memória + `Base.metadata.create_all`). | listagem de `backend/tests` | Os novos testes seguem esse padrão (SQLite unitário; Postgres opcional por `TEST_DATABASE_URL`). |

**O que [VIAB] disse e confirmei ou corrigi:**
- Confirmado: 62 ocorrências/24 arquivos como superfície de impacto; chaves sem `node_ids` alcançam a organização inteira (`access/models.py:27`); automações já reavaliam criador/destinatário; histórico/`last_answer`/notificações são snapshots.
- **Correção/precisão:** [VIAB] §3.2 trata `LibraryService.question_contexts` como ponto único; **não é** — a árvore e a busca por nome da biblioteca ignoram esse ponto (linha 3 da tabela). O plano trata a árvore como frente própria.
- **Colisão de nome "Espaço":** confirmada pela UI (`integrations-screen.tsx`, `new-space-options.ts`); a tarefa de renomeação (T-F1) vem **antes** das telas novas.

---

## 3. Modelo de dados e migrações

### 3.1 Tabelas (migração aditiva `20261019_0035_spaces.py`)

Convenção do repositório: toda tabela de domínio carrega `organization_id` (FK `organizations.id`, `ondelete=CASCADE`, `index=True`) e usa `UUIDPrimaryKeyMixin`/`CreatedAtMixin` de `app/core/models.py`; índices únicos parciais usam `postgresql_where`/`sqlite_where` (padrão de `access/models.py:94-100`).

**`spaces`** (`backend/app/spaces/models.py`)

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID FK | |
| `name` | String(120) not null | exibição |
| `name_key` | String(120) not null | `name.strip().casefold()` (unicidade independente de caixa) |
| `description` | String(500) null | |
| `is_default` | Boolean not null default false | **No máximo um por organização.** Define o Espaço que recebe novos membros automaticamente e é pré-selecionado ao ligar uma nova pasta. ("Geral" no backfill.) |
| `archived_at` | DateTime(tz) null | Arquivar = sai do resolvedor (concessões inertes), preserva auditoria. |
| `created_by_user_id` | UUID FK `users.id` ondelete SET NULL, null permitido | `null` = criado pela migração |
| `created_at` | (mixin) | |

Índices: único parcial `uq_spaces_org_name_active` em (`organization_id`,`name_key`) onde `archived_at IS NULL`; único parcial `uq_spaces_org_default` em (`organization_id`) onde `is_default` e `archived_at IS NULL`.

**`space_members`**

| Coluna | Tipo | Notas |
|---|---|---|
| `id`, `organization_id`, `space_id` (FK `spaces.id` CASCADE), `user_id` (FK `users.id` CASCADE) | | |
| `role` | String(16) not null | `member` \| `manager` (CheckConstraint `ck_space_member_role`) |
| `added_by_user_id` | UUID FK RESTRICT null | `null` = backfill/sistema |
| `removed_at` | DateTime(tz) null | remoção lógica (preserva histórico/auditoria) |
| `removed_by_user_id` | UUID null | |
| `created_at` | (mixin) | |

Índices: único parcial `uq_space_members_active` em (`space_id`,`user_id`) onde `removed_at IS NULL`; `ix_space_members_user_active` em (`organization_id`,`user_id`) onde `removed_at IS NULL` (consulta quente do resolvedor).
Invariante (testada, não só por FK): membro de Espaço **precisa** ter `Membership` ativa na mesma organização — o resolvedor re-checa a membership (I2), então remover a pessoa da organização corta tudo sem tocar em `space_members`.

**`space_folder_grants`** (concessão = "esta pasta conectada pertence a este Espaço")

| Coluna | Tipo | Notas |
|---|---|---|
| `id`, `organization_id`, `space_id` (FK CASCADE), `workspace_folder_id` (FK `workspace_folders.id` CASCADE) | | |
| `granted_by_user_id` | UUID FK `users.id` ondelete SET NULL, null permitido | `null` = concessão do backfill |
| `disclosure` | JSON not null default `{}` | `{"text_version": "v1", "member_count": 12, "acknowledged_at": "..."}` (I5 de [VIAB]) |
| `revoked_at`, `revoked_by_user_id` | null | revogação lógica |
| `created_at` | (mixin) | |

Índices: único parcial `uq_space_grants_active` em (`space_id`,`workspace_folder_id`) onde `revoked_at IS NULL`; `ix_space_grants_folder_active` em (`workspace_folder_id`) onde `revoked_at IS NULL` (usado pelo selo e pela ocultação de derivados).

> **Por que a concessão é por `WorkspaceFolder` e não por `LibraryNode`/documento:** o `WorkspaceFolder` é a unidade que `Document`/`DocumentChunk`/`ProcessingJob`/`SavedQuery` e toda recuperação já usam (`workspace_folder_id` indexado em ambas as tabelas grandes). Conceder por nó exigiria filtro por caminho em toda consulta de chunks. Com o robô do Drive, 1 pasta compartilhada = 1 `WorkspaceFolder` (§6), então a granularidade que o cliente controla (o que ele compartilha com o robô) coincide com a unidade de concessão. Concessão por sub-árvore fica como evolução (§14, R-7).

### 3.2 Tabelas **não** criadas (de propósito)

- Sem `space_id` em `documents`, `document_chunks`, `library_nodes` — sem cópia/duplicação, sem migração de dados pesados, sem risco de divergência.
- Sem `source_item_acl`/`chat_units` (P-2).
- Sem tabela de auditoria nova: `AuditLog` (`audit_usage/models.py`) com ações `space.created|renamed|archived|member_added|member_removed|member_role_changed|folder_granted|folder_revoked|admin_entered`; `target_type="space"`, `target_id=space.id` (o `target_id` é UUID obrigatório; para concessão/membro o alvo é o Espaço e o detalhe vai em `AuditLog` de segunda linha com `target_type="workspace_folder"`/`"user"`).

### 3.3 Mudanças em tabelas existentes

| Tabela | Mudança | Motivo |
|---|---|---|
| `membership_invitations` | `+ space_ids` JSON null | O convite pode já indicar os Espaços (default: Espaço padrão); ao aceitar, cria-se `space_members`. |
| `conversation_messages.context` (JSON) | passa a guardar `space_ids` pedido no filtro (opcional) | Exibição/replay; **não** é fonte de autorização (sempre recalculado ∩ membership atual). |
| `notifications.data` (JSON) | `+ provenance: {"document_ids": [...], "workspace_folder_ids": [...]}` | Ocultação na leitura do sino (§8). |
| `automation_runs.result` (JSON) | idem `provenance` | Ocultação de resultado/PDF (§8). |
| `saved_queries.last_answer` (JSON) | já guarda `document_ids` (`followed.py:79`) | Sem coluna nova; basta ler. |
| `organizations` | `+ spaces_resolver_mode` String(8) not null `server_default='off'` (`off`\|`shadow`\|`enforce`) — ver §11 | Chave de segurança do rollout. Fica em `organizations` (linha sempre existe) e **não** em `organization_access_settings` (linha criada sob demanda: ausência de linha não pode significar "sem Espaços"). |

Migração **aditiva e reversível** (`downgrade` remove as 3 tabelas e as colunas), sem tocar em dados existentes; o backfill é uma migração/etapa separada e idempotente (§11).

### 3.4 Evolução de escala (condicional, não no MVP)

`library_node_folders(node_id, workspace_folder_id)` — projeção "nó → pastas que o indexam", incluindo as pastas ancestrais — só entra se o spike (`spikes/library-scale/`) indicar que o filtro de árvore por junção com `Document` estoura o orçamento em 10k+ arquivos (critério em §10). Nenhuma outra tabela depende dela.


---

## 4. Resolvedor único e todos os pontos que precisam usá-lo

### 4.1 Contrato do resolvedor (`backend/app/spaces/access.py`)

```python
@dataclass(frozen=True)
class SpaceRef:
    id: UUID
    name: str

@dataclass(frozen=True)
class SpaceAccess:
    """O que UMA pessoa pode ler, numa organização, num instante. Imutável; calculado por request."""
    organization_id: UUID
    user_id: UUID
    spaces: Mapping[UUID, SpaceRef]                # Espaços ativos da pessoa (já filtrados por space_ids, se houve filtro)
    folder_spaces: Mapping[UUID, frozenset[UUID]]  # pasta conectada -> IDs dos Espaços DA PESSOA que a concedem

    @property
    def folder_ids(self) -> frozenset[UUID]: ...   # = folder_spaces.keys()
    def spaces_of(self, folder_id: UUID) -> tuple[SpaceRef, ...]: ...  # para os selos (ordem por nome)
    def allows(self, folder_id: UUID) -> bool: ...


class SpaceAccessResolver:
    def __init__(self, session: Session): ...
    def resolve(self, *, scope: OrganizationScope, user_id: UUID,
                space_ids: Collection[UUID] | None = None) -> SpaceAccess: ...
    def require_folder(self, *, scope, user_id, workspace_folder_id) -> WorkspaceFolder: ...   # substitui require_member_access
    def require_folders(self, *, scope, user_id, workspace_folder_ids) -> list[WorkspaceFolder]: ...  # UMA consulta (elimina o laço)
```

**Regras (testadas, §12 T-B2/T-B3):**

1. Não é membro ativo da organização ⇒ `SyncAccessDenied` (mesma exceção que `LibraryService.require_member` lança hoje, `library/service.py:171`), **antes** de olhar Espaços.
2. Uma única instrução SQL para os Espaços e pastas: `space_folder_grants g ⋈ space_members m (m.user_id=:u ∧ m.removed_at IS NULL) ⋈ spaces s (s.archived_at IS NULL ∧ s.organization_id=:o) ⋈ workspace_folders wf (wf.organization_id=:o)` com `g.revoked_at IS NULL`. Todo `JOIN` repete `organization_id` (padrão de defesa em profundidade do repositório).
3. `space_ids` (filtro) é **interseção**: `espaços_da_pessoa ∩ space_ids`. IDs desconhecidos/alheios são descartados em silêncio no resolvedor; nas rotas que recebem `space_ids` explicitamente, um ID que não pertence à pessoa devolve **404** (I7), nunca "sem permissão".
4. **Fail-closed:** qualquer exceção do banco propaga (o request falha); nunca existe caminho que devolva "todas as pastas" como fallback. Resultado vazio ⇒ `folder_spaces == {}` ⇒ zero conteúdo.
5. `status = access_lost` **não** é tratado aqui: a pasta continua concedida (para o selo "acesso perdido" do robô, `library/service.py:194-213`), e continua **não consultável** por `folder_is_queryable` (`knowledge/queryability.py`) e filtrada por `scoped_document` (`api/evidence.py:31`) — precedente existente, sem mudar.
6. **Modo de rollout** (`organizations.spaces_resolver_mode`, §11): `off` = resolvedor devolve "todas as pastas da organização" (legado, só para rollback); `shadow` = serve o legado e registra divergência; `enforce` = serve o resolvedor. O modo é lido **a cada `resolve`** (1 instrução barata por chave primária; sem cache, para que o rollback `enforce → shadow` valha no request seguinte). `off` só existe como degrau de rollback documentado — nunca é caminho de erro.

### 4.2 Integração central — duas portas, mesma função

| Porta | Mudança | Arquivo |
|---|---|---|
| `LibraryService.question_contexts(scope, user_id, space_ids=None)` | A consulta deixa de partir de "todo `WorkspaceFolder` da organização" e passa a restringir `WorkspaceFolder.id IN :access.folder_ids`; cada `LibraryContext` ganha `spaces: tuple[SpaceRef, ...]` (campo com default `()` para não quebrar construtores existentes). | `backend/app/library/service.py:42-52, 911-964` |
| `WorkspaceService.require_member_access/folders` | `require_member_access` delega a `SpaceAccessResolver.require_folder`; `folders` (usada pela tela de Fontes do admin) ganha irmã `folders_admin` (metadados operacionais, ver §5); `folders` para membro comum devolve só pastas em `U`. | `backend/app/workspaces/service.py:34-45` |

Como todas as superfícies de pergunta/recuperação já dependem dessas duas portas, **a maior parte do trabalho é teste, não código**: provar que nenhum caminho tem acesso lateral.

### 4.3 Inventário de call sites (62 ocorrências / 24 arquivos de [VIAB]) — o que cada um exige

Legenda de **efeito**: **H** = herda automaticamente ao mudar as duas portas (só teste); **M** = mudança de código; **N** = não toca conteúdo (checado, sem ação). Testes referenciados são os de §12.

| Grupo | Ponto (arquivo:linha de hoje) | Efeito | O que fazer / teste |
|---|---|---|---|
| **Chat/agente** | `knowledge/questions.py:1063` (`ask_scope`), `:1137-1143` (`ask` — laço `require_member_access` por pasta), `:1145` (cobertura) | **M** no laço, **H** no resto | Trocar o laço por **uma** chamada `require_folders` (também remove o N+1 medido no spike). T-B4. |
| | `knowledge/agent.py` (ferramentas via `LibraryToolExecutor` → `LibraryService`), `knowledge/overview.py:67` | **H** | `test_agent_revocation_*` ganha cenário "removido do Espaço no meio da conversa". T-G2. |
| **Recuperação** | `knowledge/retrieval.py:52-64, 90-100` (`_scoped`, `fetch`) | **H** (recebe `selection.folder_ids` já filtrado) | Teste de propriedade: nenhum `SearchHit.document_id` fora de `U`. T-G1. **Mudança de código** pequena: deduplicar hits por `(source_id, external_file_id)` e acumular `spaces` (arquivo presente em duas pastas de Espaços diferentes). T-E3. |
| | `knowledge/search.py:61` (busca por pasta única) | **M** | `require_member_access` → resolvedor; 404 se fora de `U`. T-B4. |
| **Biblioteca** | `library/service.py:173-184` `roots`, `:230-254` `children`, `:542-559` `search_page` | **M** (o grande) | Filtro de visibilidade de nós por `U` (§10). T-D1…T-D4. |
| | `:256-284` `indexed_documents_under`, `:318-361` `workspace_provenance`/`document_provenance`, `:363-424` `documents_for_nodes` | **M** | Restringir a documentos em pastas de `U` (hoje devolvem todas as pastas que indexam o arquivo — vazaria nome/ID de pasta de outro Espaço). T-D3. |
| | `:1002-1031` `authorized_catalog`, `:1073-1122` `mention_candidates`, `:1124-1183` `resolve_question_selection`/`authorize_mentions` | **H** | Mencionar nó fora de `U` ⇒ `ValueError("mention is unavailable")` (mesma resposta de "não existe"). T-G1. |
| | `:774-909` `sync_status`, `:1185-1217` `recent_syncs`, `library/manual_sync.py` (histórico) | **M** | Membro comum só vê sync de pastas em `U`; admin vê metadados operacionais de todas (nome do escopo e status, **sem** nomes de arquivos). T-D5. |
| **API REST (membro)** | `api/library.py:121` (question-contexts), `:152` (mention-candidates) | **H** + novo campo `spaces` | T-C3. |
| | `api/evidence.py:21-37` `scoped_document` (e os 4 usos em `api/document_view.py:85,104,132,143`) | **H** | Citação → documento de outro Espaço ⇒ 404 uniforme. T-G1. |
| | `api/ingestion.py:409-434` (histórico), `api/answer_export.py:40`, `api/clickup_tasks.py:67`, `api/answer_feedback.py:30`, `api/notifications.py:34` | **M** (derivados) | Ocultação pela proveniência (§8). T-H1…T-H5. |
| | `api/ingestion.py:120-290, 438` (`/workspace-folders/{id}/documents|search|questions|syncs|delete|reprocess`) | **M** | Operações de **administração** (sync, reprocess, excluir) seguem exigindo Owner/Admin e passam a exigir também **a pasta existir na organização**, sem exigir ser membro do Espaço; leitura de nomes de arquivo (`/documents`, `/documents/failures`) só se a pasta ∈ `U` **ou** via "Entrar no Espaço" (§5). `/search` e `/questions` por pasta: pasta ∈ `U` ou 404. T-B5. |
| | `api/integrations.py:866` (`GET /workspace-folders`, tela Fontes) | **M** | Admin: lista todas as pastas (metadados); membro: só `U`; cada item ganha `spaces` (os que o chamador enxerga) — base do atribuidor de Espaço. T-C2. |
| | `api/saved_queries.py` + `audit_usage/service.py:26,29,44` | **H** | Consulta salva só lista/roda se a pasta ∈ `U`; `last_answer` limpo na revogação (§8). T-H3. |
| | `api/insights.py`, `api/overview.py`, `api/usage.py` | **N** | Agregados (contagens, códigos de falha); sem texto de documento. Revisar `insights.py:74` (agrega por pasta — expor só totais ao admin). T-C2 nota. |
| **Credenciais** | `access/principal.py:76-86`, `access/scope.py`, `api/public_v1.py:181`, `mcp_server/auth.py:84-93`, `mcp_server/tools.py:71,60-90` | **H** + campo `spaces` | `U(usuário vinculado) ∩ node_ids`. Teste "admin que não é membro do Espaço não lê, mesmo com chave sem `node_ids`". T-I1/T-I2. |
| **Automação** | `automations/executor.py:53` (`accessible_folders`) e `:100-195`, `automations/scope.py`, `notifications/followed.py:55-90` | **H** + **M** (provenance) | O executor já reavalia criador e cada destinatário; vira correto automaticamente. Acrescentar `provenance` em `AutomationRun.result`/`Notification.data` e ocultação. T-H2/T-H4. |
| **Operador da plataforma** | `workspaces/service.py:74-76` `support_metadata`, `api/platform.py` | **N** | Já devolve só metadados operacionais por concessão da plataforma; não lê conteúdo. Apenas teste de regressão (não ganha `spaces`). |

**Lista de verificação viva:** T-A3 grava `specs/espacos/call-sites.md` (checklist com dono por arquivo, gerado por `graphify`/`rg` e conferido contra esta tabela) e um teste (`tests/unit/test_spaces_call_sites.py`) que **falha** se aparecer um novo uso de `question_contexts(`/`require_member_access(` fora da lista aprovada — o mecanismo que garante I3 ("divergência entre caminhos é o bug a prevenir") depois do deploy.

### 4.4 Árvore da biblioteca — a frente nova (regra de visibilidade)

Regra de [VIAB] §5.3, refinada com o código atual:

- **Arquivo visível** ⇔ existe `Document` (qualquer `index_status` ≠ `removed`/`deleted`) de `(source_id, external_file_id)` em pasta ∈ `U`.
- **Pasta (nó) visível** ⇔ tem descendente arquivo visível. **Raiz de fonte/ferramenta visível** ⇔ tem filho visível.
- Nós sem **nenhum** `Document` (catalogados mas fora de qualquer escopo) são visíveis **apenas** a Owner/Admin na visão operacional (precedente: `catalog_inventory` já os trata à parte, `library/service.py:604-609`); nunca a membros.
- `_same_tool_roots` (`library/service.py:215-228`: Drive OAuth + Drive-robô = uma raiz "Google Drive") continua valendo; o filtro roda **depois** dela.
- Paginação/contagem: o filtro vira `WHERE` (SQL), não pós-filtro em Python, para `total`/`offset` continuarem corretos (`BrowsePage.total`, `library/service.py:246`).

**v1 (MVP):** `visible_file_keys(access)` = `SELECT DISTINCT wf.source_id, d.external_file_id FROM documents d JOIN workspace_folders wf … WHERE d.workspace_folder_id IN :U` e, para pastas, subir a cadeia de `parent_id` em memória a partir dos arquivos visíveis (mesma técnica já usada em `mention_candidates`, `library/service.py:1085-1098`). **v2 (condicional):** tabela de projeção `library_node_folders` (§3.4/§10), trocada atrás da mesma interface `visible_node_clause(access)`.

---

## 5. Papéis

Três papéis de **gestão** sobre uma regra de **leitura** única (ser membro do Espaço). Os papéis da organização (`MembershipRole`: `owner|admin|member`, `organizations/models.py:11-14`) não mudam.

| Papel | Quem | Pode | **Não** pode |
|---|---|---|---|
| **Admin da organização** (`owner`/`admin`) | quem já administra a empresa | Criar/renomear/arquivar Espaços; definir o Espaço padrão; **adicionar/remover qualquer pessoa em qualquer Espaço**; **atribuir pastas conectadas a Espaços** (ao conectar e depois); designar *responsáveis*; ver, **para todas as pastas**, metadados operacionais (nome da pasta, status, contagens, códigos de falha, sync, uso, quais Espaços a concedem); criar chaves de API. | **Ler conteúdo** (nomes de arquivo, trechos, respostas) de Espaço de que não é membro (**D-2**). Para ler: botão **"Entrar neste Espaço"** → vira membro, com evento `space.admin_entered` visível aos membros do Espaço (UX §7). |
| **Responsável pelo Espaço** (`space_members.role='manager'`) | alguém designado (ex.: líder do RH) | Habilitar/desabilitar **pessoas da organização** no **próprio** Espaço; renomear o Espaço e editar descrição; ver a lista de membros e o impacto ("N documentos, M conversas") antes de remover. | Criar/arquivar Espaços; atribuir/revogar pastas (fonte de dados = decisão da empresa); convidar pessoas **novas** para a organização (convite continua sendo do Owner, `team-staff.tsx` hoje só para Owner); gerir outro Espaço. O responsável **é** membro (lê). |
| **Membro** (`space_members.role='member'`) | pessoa habilitada | Ler o conteúdo das pastas concedidas ao Espaço, **na visão unificada** com os demais Espaços dela; filtrar por Espaço; ver a lista de membros (nomes) do próprio Espaço. | Gerir qualquer coisa de Espaços. |

Regras auxiliares:

- **Um Espaço sempre tem ≥ 1 responsável OU o admin da organização como gestor de fato.** Remover o último responsável é permitido (Owner/Admin gerem de qualquer forma); a UI avisa.
- **Quem pode ser adicionado:** só pessoas com `Membership` ativa na organização. Desativar a pessoa na organização corta o acesso sem tocar em `space_members` (o resolvedor re-checa, I2).
- **Novo membro da organização** entra no Espaço marcado `is_default` (hoje "Geral"), a menos que o convite traga `space_ids`. Se o admin desmarcar o padrão, a pessoa entra **sem acesso** e vê o estado vazio "Peça acesso a um Espaço" (fail-closed, nunca "tudo").
- **Operação sobre pastas sem ser membro** (resolver o que o admin realmente faz): sync, reprocessar, ver falhas, excluir pasta, mudar atribuição → continuam por papel (Owner/Admin). O que muda: a resposta para admin **não-membro** troca `documents` (com nomes) por contagens e `failures` com o nome do arquivo substituído por `arquivo #<7 primeiros do id>`; "Entrar neste Espaço" devolve a visão completa. [INFERÊNCIA] Esta é a forma mais barata de preservar D-2 sem quebrar a operação; alternativa (admin nunca vê nome) quebra o reprocessamento.
- **Matriz de permissão** exercitada em `tests/api/test_space_roles_api.py` (T-C1): 3 papéis × 6 ações × (própria|outra organização|outro Espaço).

---

## 6. Drive: como as pastas compartilhadas com o robô viram fontes atribuíveis a Espaços

**Fatos [FATO].** No modo robô, o cliente compartilha uma pasta do Drive com o e-mail da conta de serviço da organização (`GoogleSaIdentity.sa_email`). O admin "liga" a pasta em `DriveSaConnectionService.link/_connect` (`integrations/google_drive_sa_service.py:296-345`), que (1) cria/reusa um `WorkspaceFolder` por `select_scope(mode="selected", folder_ids=(folder_id,), uniform_access_confirmed=True)` e (2) grava um `DriveFolderLink` ligado a ele (`workspace_folder_id`). Uma sub-pasta de pasta já ligada é **rejeitada** (`NestedInLinked`, `check_nested`, `:230-243`). A perda do compartilhamento move o link para `suspect`/`access_lost`, esconde o `WorkspaceFolder` (`hide`, `:461-475`) e agenda purga (`purge_due`, `:687`).

**Desenho.** *Pasta compartilhada com o robô ⇒ `WorkspaceFolder` (1:1) ⇒ concessão `space_folder_grants` a 1..N Espaços.* A atribuição nasce no mesmo ato de ligar:

1. **Ligar pasta (UI):** o fluxo de `link`/`link_batch` ganha o passo "**Quem poderá ver esta pasta?**" — seleção múltipla de Espaços, **pré-marcado o Espaço padrão** (para manter o comportamento de hoje), com a contagem de pessoas ("Geral · 60 pessoas") e o texto de ciência versionado (`disclosure.text_version="v1"`): *"As N pessoas dos Espaços escolhidos poderão pesquisar e ver trechos destes documentos. Quem já tem acesso pelo Drive não muda."* Sem ao menos um Espaço marcado, o botão "Ligar" fica desabilitado (fail-closed: pasta sem Espaço = invisível a todos).
2. **Backend:** `DriveSaConnectionService._connect(..., space_ids)` e `link_batch(..., space_ids)` recebem `space_ids` (obrigatório e não vazio quando `spaces_resolver_mode != off`); depois de `select_scope`, chamam `SpaceService.grant_folder(...)` **na mesma transação**. Falha na concessão desfaz a ligação (nada de pasta "órfã" visível a ninguém).
3. **Reatribuir depois:** tela da pasta → "Espaços" (só Owner/Admin) → `grant`/`revoke` (`POST/DELETE /organizations/{id}/spaces/{space_id}/folders/{workspace_folder_id}`). Revogar a última concessão deixa a pasta **sem Espaço**: some para todos os membros (continua visível ao admin como "sem Espaço — ninguém vê"), nada é apagado.
4. **O mesmo vale para OAuth** (Drive/OneDrive/SharePoint/Notion/ClickUp): `WorkspaceService.select_scope` (`workspaces/service.py:78-107`) ganha `space_ids`; nesses provedores o admin conecta *uma conta* e escolhe várias pastas — cada escopo vira um `WorkspaceFolder` e recebe concessão. O texto de `uniform_access_confirmed` muda de "todos os membros da organização" para "todos os membros dos Espaços escolhidos".
5. **Reconexão/recuperação (`restore`, `:530`):** a concessão pertence ao `WorkspaceFolder`, que é preservado quando o link volta de `access_lost` → `verified`; **não** se recria concessão. Purga definitiva (`purge`, `:623`) apaga o `WorkspaceFolder` e a FK `ON DELETE CASCADE` remove as concessões — a trilha fica em `AuditLog`.

**Limitação a dizer ao cliente (e na tela).** Como o robô **não aceita sub-pasta de pasta já ligada**, o recorte de Espaço é o recorte do que o cliente **compartilha**: para ter "RH" e "Diretoria" separados dentro de "/Empresa", o cliente compartilha `/Empresa/RH` e `/Empresa/Diretoria` com o robô (e não `/Empresa`). A tela de ligar já detecta `NestedInLinked` e explica; ganha uma dica "para separar por Espaço, compartilhe cada subpasta". Concessão **por sub-árvore** de uma pasta única (R-7) exigiria o filtro por caminho em chunks — fora do MVP.

**Conteúdo repetido em dois Espaços.** Conceder a mesma pasta a dois Espaços **não** duplica `Document`/chunks (teste de contagem, T-A4). Já "o mesmo arquivo em duas pastas ligadas" já gera dois `Document` hoje (`uq_documents_folder_external` é por pasta) — a recuperação deduplica por `(source_id, external_file_id)` e mostra os dois selos (T-E3).

---

## 7. UX: visão unificada, filtro e gestão de membros

Princípio: **a navegação principal nunca pergunta "em qual Espaço?"**. Espaço aparece como **atributo** (selo/filtro), não como destino.

### 7.1 Telas e mudanças (arquivos reais em `frontend/app/`)

| Tela | Arquivo | Mudança |
|---|---|---|
| **Biblioteca** | `product/library-screen.tsx`, `library-view-logic.ts`, `product/library-grid.tsx`, `product/use-library-items.ts` | Faixa de **chips de Espaço** acima da lista ("Todos os meus Espaços" ativo por padrão; chip por Espaço; multi-seleção) — estado na URL (`?spaces=a,b`) e `localStorage` só como conveniência (try/catch, como `LIBRARY_VIEW_KEY`). Selo(s) de Espaço em cada item e no detalhe. Botão "Agrupar por Espaço" (alterna a visão para raízes virtuais = Espaços, mesmo payload). Estado vazio: "Você ainda não está em nenhum Espaço — peça acesso a um administrador" (sem enumerar Espaços inexistentes). |
| **Busca** | `product/library-screen.tsx` (caixa de busca), novo uso de `POST /organizations/{id}/search` (T-E4) | Mesma caixa, **escopo = `U`**; os chips filtram; abas "Nomes | Conteúdo". Selo por resultado. |
| **Chat** | `product/chat-workspace.tsx`, `question-scope.tsx`, `mention-composer.tsx` | Faixa fixa sob o composer: **"Procurando em: todos os meus Espaços (3)"** (clique abre o seletor). O `QuestionScopePicker` ganha uma segunda dimensão **Espaço** (multi-seleção; vazio = todos), alimentada por `GET /library/question-contexts` (que passa a trazer `spaces` por contexto — zero chamada extra). `POST /organizations/{id}/questions` aceita `space_ids` (opcional). Citações mostram o selo; resposta que combina Espaços exibe "Fontes de: RH, Geral". Histórico restaurado reaplica filtro **recalculando** ∩ membership atual. |
| **Citações/visualizador** | `source-reading.tsx`, `answer-actions.tsx`, `file-viewer.tsx` | Selo + "Abrir" (já usa `scoped_document`); se 404, mensagem "Este conteúdo não está mais disponível para você" (mesma do placeholder de histórico). |
| **Fontes (admin)** | `product/integrations-screen.tsx`, `new-space-options.ts`, `product/drive-share-flow.tsx` (+ `drive-share-api.ts`, `drive-share-logic.ts`) | **Renomear** o "Espaço" legado para "Pasta conectada" (T-F1, antes de tudo). Passo "Quem poderá ver?" ao ligar pasta (§6). Coluna "Espaços" por pasta + editar. |
| **Espaços (nova)** | novo `product/spaces-screen.tsx` (+ `spaces-model.ts`, `spaces-api.ts` para a lógica testável em `.mjs`) | Lista de Espaços (nome, nº de pessoas, nº de pastas, responsável); detalhe com abas **Pessoas** e **Pastas**. Pessoas: busca na lista de membros da organização, toggle **Habilitar/Desabilitar**, papel (membro/responsável); ao desabilitar, **diálogo de impacto** (§8). Pastas (só admin): conceder/revogar. Acesso: admin da organização vê tudo; responsável vê o(s) seu(s) Espaço(s) na aba Pessoas; membro vê só leitura. |
| **Equipe** | `product/team-staff.tsx` | Convite pode escolher Espaços (default: o padrão). Coluna "Espaços" por pessoa com atalho para gerir. |
| **Automações** | `automation-recipients.tsx`, `automation-folder-picker.tsx` | O seletor de pastas/nós lista só `U` do criador; o destinatário já mostra `has_access` — passa a considerar Espaços (já vem do executor/`node_access`). |
| **Uso** | `usage-panel.tsx` | "Consumo por Espaço" só informativo (atribuído por pasta; pasta em 2 Espaços conta nos dois, rotulado). |
| **Chaves de API/MCP** | `access-settings.tsx`, `product/developer-screen.tsx`, `developer-mcp-config.ts` | Ao criar chave: "Esta chave alcançará N documentos em: RH, Geral" (prévia calculada para o **usuário criador**); aviso se criador é admin sem Espaços ("esta chave não lerá nada"). |

### 7.2 Exemplo concreto (a mesma "Acme" de [VIAB] §8, agora com visão unificada)

Carla (Diretoria) está em **Geral + RH + Diretoria**. Biblioteca: **uma** árvore, 3 chips; arquivos com selos `Geral`, `RH`, `Diretoria`. Ela pergunta "qual o reajuste de 2027?" no chat sem escolher Espaço: a faixa diz "Procurando em: 3 Espaços"; a resposta cita `reajuste-2027.pdf` (selo Diretoria) e `politica-salarial.pdf` (selo Geral). Se ela só quiser RH, clica no chip **RH** (filtro). Daniel (só Geral) faz a mesma pergunta e **não** recebe nem menção a documentos da Diretoria. Bruno removido do RH: abre uma conversa antiga e as respostas que citavam RH aparecem como "Conteúdo ocultado por mudança de acesso", a pergunta dele permanece.

### 7.3 Acessibilidade e responsividade (já exigidas pelo projeto)

Chips como grupo de botões `aria-pressed` com navegação por teclado; diálogo de impacto como `<dialog>` com foco preso e retorno (padrão `closeDialogAnimated`/`useDialogBackdropClose` de `library-screen.tsx`); selos com texto (nunca só cor); em telas estreitas o filtro vira um **seletor único** (padrão do `QuestionScopePicker`). Textos em PT-BR, sem jargão ("Pasta conectada", "Espaço", "Quem poderá ver").


---

## 8. Revogação e ocultação de derivados

Aplica a matriz de [VIAB] §6 ao desenho acima. Regra mestra: **o que é calculado a cada request herda o resolvedor; o que foi gravado é ocultado na leitura pela proveniência e purgado por job.**

### 8.1 Gatilhos

| Gatilho | Efeito imediato (próximo request) | Job |
|---|---|---|
| Pessoa **desabilitada** de um Espaço (`space_members.removed_at`) | `U` da pessoa encolhe; superfícies vivas deixam de devolver as pastas que só aquele Espaço concedia. | `purge_derived_for_user_space` (T-H6) |
| Pasta **revogada** de um Espaço (`space_folder_grants.revoked_at`) | Idem para **todos** os membros que dependiam só daquela concessão. | `purge_derived_for_folder` (T-H6) |
| Espaço **arquivado** | Concessões inertes (resolvedor ignora `archived_at`). | idem |
| Pessoa removida da **organização** | Já corta tudo (`Membership.is_active`, `library/service.py:162-171`); inalterado. | — |
| Robô perde o compartilhamento (`access_lost`) | Já oculto (`api/evidence.py:31`, `folder_is_queryable`); inalterado. | purga existente (`google_drive_sa_service.py:687`) |

### 8.2 Superfície por superfície

| Superfície | Tipo | Como fica |
|---|---|---|
| Chat, agente, recuperação, evidência, visualizador, mentions, árvore, busca | **Viva** | Herdam o resolvedor (§4). Teste de regressão no padrão `test_agent_revocation_*` (T-G2). |
| **Histórico de conversa** (`GET …/conversations/{id}`, `api/ingestion.py:409-434`) | Snapshot | **`ConversationService.history` passa a devolver cada mensagem `assistant` filtrada**: reconferir `document_id`s de `response.citations` (já gravados, `knowledge/agent.py:1455-1475`) e nós de `context.references` contra `U` atual. Se **qualquer** citação sai de `U`: `content` vira `"Conteúdo ocultado por mudança de acesso."`, `response` perde `answer`/`citations` e ganha `{"hidden": true, "reason": "access_changed"}`; a mensagem do **usuário** permanece. (Granularidade = mensagem inteira: uma resposta que misturou fontes não pode ser parcialmente reescrita sem inventar texto — decisão conservadora.) |
| **Exportar resposta** (`api/answer_export.py`) | Snapshot | Mesma função `visible_message(...)`; mensagem oculta ⇒ 404/"conteúdo ocultado" antes de gerar md/docx/pdf. |
| **ClickUp "criar tarefa"** (`api/clickup_tasks.py`, ADR-0020 D4/D12) | Externa depois de criada | Prévia e criação reconferem a proveniência da mensagem; oculta ⇒ 404. Após criada, é irrevogável (documentado). |
| **Feedback** (`api/answer_feedback.py`) | Metadado | Sem texto de conteúdo; só garante que a mensagem é do usuário. Sem mudança. |
| **Perguntas seguidas** (`SavedQuery.last_answer`, `notifications/followed.py:55-90`) | Snapshot | Leitura: se `last_answer.document_ids` ⊄ `U` ⇒ tratar como sem baseline e **ocultar**; `refresh_followed_queries` roda só se `workspace_folder_id ∈ U(user)` (hoje não verifica, usa só membership via `ask`); job limpa `last_answer`/`last_checked_at` e pausa `followed`. |
| **Notificações** (`Notification.body` até 600 chars, `data.citations`) | Snapshot | **Gravar `provenance`** (`document_ids`, `workspace_folder_ids`) em `data` ao criar (hoje há `citations[].document_id`, mas não pasta); leitura do sino oculta itens fora de `U` ("Conteúdo ocultado por mudança de acesso"); job apaga corpo/`data` do item oculto após 24 h. |
| **Resultado de automação / PDF** (`AutomationRun.result`, `automations/executor.py:194`, rota de PDF) | Snapshot | Mesmo `provenance` em `result`; ocultar na leitura do histórico/PDF. **Execuções futuras** já caem em `creator_access_lost` (criador) ou "destinatário pulado" (`skipped_recipients`) via `accessible_folders` (`executor.py:46-53`). |
| **E-mail e webhook de automação** (`automations/webhooks.py:27,107-120`, e-mail/PDF) | **Externa/irrevogável** | Mitigação no gatilho "pessoa desabilitada": (1) **pausar** automações **criadas** por ela cujo escopo toca pasta que ela perdeu (`Automation.enabled = False` — `automations/models.py` — e notificação ao dono com o motivo; **não** inventar status novo em `automation_runs`, cujo `CheckConstraint` só admite `queued|running|ok|empty|quota|error`); (2) remover a pessoa como **destinatária** de automações de terceiros se perder acesso (o executor já pula; o job apenas limpa a lista para não aparecer como "sem acesso" para sempre); (3) gravar `space_ids` na entrega (`AutomationRun.result.provenance`). A opção "este Espaço não pode sair da plataforma" de [VIAB] §6 **não** entra no MVP (decisão P-2: sem canais externos novos), mas a coluna `provenance` já viabiliza. |
| **Chave de API / MCP** | Viva | `U(usuário) ∩ node_ids` no próximo request. Desabilitar a pessoa **não revoga** a chave (que pertence ao admin criador); reduz o alcance. Se o **criador** da chave sai da organização, já deixa de autenticar (`access/principal.py:76-86`). |
| **`ExtractionCache`** (`ingestion/models.py`) | Interno | Só entra na purga **da pasta** quando a pasta é apagada; revogar concessão não apaga conteúdo (o conteúdo ainda pertence à organização e a outros Espaços). |
| Embeddings/chunks | Vivos | Não mudam por revogar concessão (sem cópia). Só a purga da pasta os remove. |

### 8.3 Diálogo de impacto (UX da remoção)

Antes de confirmar "Desabilitar Bruno no RH", `GET /organizations/{id}/spaces/{space_id}/members/{user_id}/impact` devolve: `documents_lost` (arquivos que **somem** do alcance dele considerando os **outros** Espaços dele — não conta o que ele continua vendo por outro Espaço), `conversations_hidden`, `automations_paused`, `followed_queries_cleared`. É um cálculo de leitura (`U` antes − `U` depois) + contagens por `provenance`; não altera nada. Texto: *"Bruno deixará de ver 214 documentos. 3 conversas dele terão trechos ocultados. 1 automação será pausada. Continuará vendo o que estiver em Geral."*

### 8.4 Prazos (premissa de [VIAB] §6, a confirmar com o dono)

Leitura viva = próximo request; ocultação de derivados = imediata (na leitura); **purga ≤ 24 h** (job diário no `beat_schedule` do Celery (`ingestion/tasks.py:62`)).

---

## 9. API pública, MCP e chaves de API

**Princípio:** *o alcance de uma credencial é a interseção de duas coisas — o que o **usuário vinculado** pode ler (`U`) e o que a credencial restringe (`node_ids`)* ([VIAB] §2/§5.4; já é a decisão D1 do plano 03, `specs/plans/integracoes/03-api-mcp-e-canais.md:51`).

| Ponto | Hoje | Depois |
|---|---|---|
| Chave de API (`api/public_v1.py`, `access/principal.py`) | Exige criador Owner/Admin (`principal.py:76-86`); sem `node_ids` ⇒ organização inteira (`access/models.py:27`). | Alcance = `U(criador) ∩ node_ids`. **Admin que não é membro de nenhum Espaço ⇒ a chave não lê nada** (e a UI avisa na criação). Nenhuma coluna nova em `api_keys`. |
| MCP (`mcp_server/auth.py:84-93`, `mcp_server/tools.py`) | Qualquer membro; `node_ids` do `McpConnection`. | `U(usuário)`. `list_sources` passa a devolver **só Espaços/pastas de `U`**, com `spaces`. |
| `GET /v1/sources`, MCP `list_sources` | Lista `question_contexts` (hoje = toda a organização). | Lista `U`; cada item ganha `spaces: [{"id","name"}]`. |
| `POST /v1/search`, `POST /v1/ask`, MCP `search`/`fetch` | `RetrievalService`/`ScopedAccess.selection` sobre `question_contexts`. | **Herdam** (§4). Hits e citações ganham `spaces`. `fetch` de um `id` fora de `U` ⇒ `ToolNotFound` (404 uniforme). |
| **Novo parâmetro opcional `space_ids`** (corpo de `/v1/search`, `/v1/ask`; argumento do MCP `search`) | — | Só **estreita**; ID que não é do usuário ⇒ 404 (I7). Útil para integrações que querem "só o RH". |
| `GET /v1/whoami` | org, escopos, `restricted_to_nodes`. | `+ spaces: [{"id","name"}]` (Espaços do usuário vinculado) — transparência sem expor Espaços alheios. |
| Prévia na criação da chave (`api/access_admin.py:73-98`) | — | Resposta de `POST /api-keys` e `GET /api-keys` traz `reach: {"spaces": [...], "documents": N}` calculado para o criador. |
| Auditoria (`ApiAuditEvent`, `access/audit.py`) | Nunca grava texto/trechos. | Sem mudança; opcional `space_count` (inteiro) — **sem** nomes de Espaço. |
| **Chaves já existentes** | `node_ids = NULL` ⇒ "tudo". | **Sem migração de dados.** O Espaço "Geral" contém todas as pastas e todos os membros ⇒ o alcance de cada chave existente **não muda no dia do deploy**; muda quando o admin começar a restringir Espaços (e aí a chave encolhe com ele, por construção). Esse efeito é dito no aviso de §11. |
| **`node_ids` apontando para nó fora de `U`** | `authorize_mentions` já falha fechado (`library/service.py:1170-1181`). | Idem: `SyncAccessDenied`/403 uniforme; o `node_ids` da credencial **nunca** amplia. |
| **Documentação pública** (`docs/api/`, `frontend/app/docs`) | — | Atualizar com `spaces`, `space_ids`, regra de interseção, e o aviso "admin sem Espaço ⇒ chave vazia" (T-I3). |
| **Threat model** (`docs/seguranca/threat-model-api-mcp-canais.md`) | Descreve `node_ids` como confinamento. | Acrescentar T-ESP (escalada por papel de admin, vazamento por histórico/derivados) com as mitigações acima (T-I3). |

---

## 10. Onde a escala da biblioteca afeta o desenho

Fonte: `spikes/library-scale/` (spike paralelo, **ainda em execução**: `results/api_1k.json` e `meta_1k.json`/`meta_10k.json` existem; `api_10k.json`/`api_50k.json` **não** existem ainda — `seed_50k.log` mostra o semeador do 50k em andamento, 52 002 nós / 50 827 documentos indexados). Medições em laptop, Postgres do docker sem ajuste (`PATHS_NOTE` de `bench_api.py:21`); **ordem de grandeza, não SLO.**

### 10.1 O que os números de 1k dizem (`results/api_1k.json`: 1 000 arquivos, 1 042 nós, 4 988 chunks, 10 escopos)

| Endpoint (hoje, sem Espaços) | mediana / p95 (ms) | instruções SQL | Leitura para o plano |
|---|---|---|---|
| `GET /library` (raízes) | 9,1 / 20,6 | 6 | barato; filtro por `U` deve manter < 30 ms |
| `GET …/children` (raiz de fonte, pág. 1/100) | 16,2 / 20,7 | 9 | pós-filtro **em SQL** (não Python) para `total` correto |
| `GET /library/search` ("ra", comum) | 10,5 / 26,7 | 7 | busca por nome é `ILIKE`; filtro `EXISTS` em `documents` indexado por `(workspace_folder_id, external_file_id)` |
| `GET /library/question-contexts` | 6,8 / 16,1 | 4 | **é a consulta que passa a depender do resolvedor**: +1 junção; meta p95 < 40 ms |
| `GET /library/mention-candidates` | 36,7–40,6 / 41,9–74,1 | 7 | **carrega todos os nós da organização em Python** (`_selection_nodes`, `library/service.py:985-991`); custo cresce ~linear com nós |
| `GET /library/sync-status` | 13,2 / 17,3 | 10 | filtrar por `U` reduz, não aumenta |
| `POST` pergunta, **1** escopo | 82,4 / 86,6 | 15 | — |
| `POST` pergunta, **todos os 10 escopos** (= a união) | **417,3 / 423,7** | **44** (206 ms em SQL) | **a consulta de `Membership` repete-se 13 vezes** (`repeated_shape_max = 13`): é o N+1 de `require_member_access` por pasta (`questions.py:1137-1143`) |

Tamanho: com 1k arquivos a tabela `document_chunks` pesa 108 MB; com 10k, **1,06 GB** (`meta_*.json`, `table_bytes`); `documents` e `library_nodes` ficam em ~4 MB cada. Ou seja: **a escala dói em `document_chunks`, não nas tabelas que Espaços tocam** — `space_*` terão dezenas/centenas de linhas por organização.

### 10.2 Decisões de desenho que a escala impõe

1. **Resolvedor em UMA consulta e por request (obrigatório).** A "união" é o caso comum para quem está em vários Espaços; no 1k, ela já custa 417 ms por causa do N+1 de membership. `require_folders` (batch) transforma `O(pastas)` consultas em `O(1)`: 4 instruções por `resolve`, independentes do nº de pastas. Como `authorized_catalog`/`resolve_question_selection`/`mention_candidates` chamam `question_contexts` mais de uma vez por request, o custo fica ≈ 4 × 2–3 instruções triviais (índices parciais, PK) contra as 13 consultas de membership de hoje; uma **memoização por request** do `SpaceAccess` (`session.info`, invalidada por `SpaceService` e desligada nos testes) é otimização **opcional**, só se `api_10k_spaces.json` (T-D0) mostrar necessidade. T-B2/T-B4 incluem um **teste de contagem de instruções** (`assert statements <= K`) para travar a regressão.
2. **Filtrar por `workspace_folder_id IN :U` — não por `space_id` — em chunks/documentos.** Ambas as tabelas grandes já indexam `workspace_folder_id` (`knowledge/models.py`: `index=True` em `Document.workspace_folder_id` e `DocumentChunk.workspace_folder_id`). Não adicionamos `space_id` a elas (evita reindexar 1 GB+ e uma segunda fonte de verdade). A lista `U` é pequena (nº de pastas conectadas ≈ dezenas); com milhares de pastas, trocar `IN (…)` por `JOIN` na CTE do resolvedor (anotado em T-B2).
3. **Árvore e busca por nome: filtro em SQL com `EXISTS` (v1), projeção `library_node_folders` (v2, condicional).** v1 usa o índice único `uq_documents_folder_external (workspace_folder_id, external_file_id)` (`knowledge/models.py:66`). **Gatilho para v2:** se o spike (`api_10k.json`) mostrar `children`/`search` com p95 > 150 ms ou > 15 instruções com `U` de ≥ 20 pastas. Quando existir, o plano T-D6 implementa v2 sem tocar nas telas (mesma `visible_node_clause`).
4. **`mention_candidates` e `_selection_nodes` (carregam todos os nós em memória):** já são o gargalo de escala **independente de Espaços** (36–74 ms a 1k ⇒ [INFERÊNCIA, a confirmar com `api_10k.json`] centenas de ms a 10k). O filtro por `U` **reduz** o conjunto carregado se aplicado **antes** (`WHERE source_id IN (fontes das pastas de U)`); T-D4 faz isso e **não** tenta reescrever a mentions inteira (fora do escopo). Se o spike confirmar degradação, abrir tarefa própria "paginar candidatos de menção em SQL" (R-5).
5. **Escrita (sync) não cresce com Espaços** na v1: concessão é por pasta, não por arquivo; `project_successful_sync` (`library/service.py:1219-1341`) não muda. O bench de ingestão do spike (`results/ingest.log`: 500 novos docs = 3 539 instruções, `SELECT documents` repetido 501×) indica N+1 **já existente** no caminho de reconciliação; **não** o agravamos — mas a v2 (projeção) acrescentaria escrita por nó ancestral, e por isso fica condicional.
6. **Teto de 3.000 documentos ativos** (`Settings.active_document_limit`; era 500) é por organização e não restringe o desenho. O consumo informativo "por Espaço" faz uma agregação por pasta (`count(*) GROUP BY workspace_folder_id`, mesma forma de `api/insights.py:74`) — barata.
7. **Selo por documento/citação em lote:** `SpaceAccess.spaces_of(folder_id)` é dicionário em memória; serializar N itens custa O(N), sem consulta por item (proibido: 1 consulta por item — teste de contagem em T-E1).
8. **Orçamento proposto (a validar com `api_10k.json`):** `question-contexts` p95 < 40 ms; `children`/`search` p95 < 100 ms (1k) e < 150 ms (10k); pergunta "união" ≤ 1,3× a de 1 escopo + 100 ms (hoje 5×) — o objetivo é **matar o N+1**, não otimizar a recuperação (que é custo de vetor, fora deste plano).

### 10.3 Como o spike entra no plano

- T-D0 (primeira tarefa da frente de árvore): **rerodar** `bench_api.py --label 10k` (e `50k` se o semeador terminar) **depois** de T-B/T-D1 mergeados, com `U` de 1, 5 e 20 pastas; salvar em `spikes/library-scale/results/api_10k_spaces.json` e anexar ao ADR-0021. Se estourar o orçamento ⇒ liberar T-D6.
- Se `results/api_10k.json` aparecer antes de começarmos, T-D0 passa a ser só "comparar".
- **Resultado do T-D0 (2026-10-19, banco de spike, `bench_spaces.py`; `results/api_10k_spaces.json` e `api_50k_spaces.json`):** com a visibilidade em CTE recursiva (v1) e os índices da migração 0037 (`pg_trgm` em `lower(name)`, `documents(organization_id, external_file_id)`), `children`/`search` com **1, 5 e 20 escopos legíveis** ficam em p95 ≤ 62 ms (10k: ≤ 40 ms) e 5 instruções SQL; no 50k a busca por nome com 20 escopos chega a p95 132 ms, ainda dentro do orçamento de 150 ms. `@`-menção (2 letras, o pior caso) 110–280 ms no 50k contra ~800 ms do caminho em Python. **Decisão: não liberar T-D6** (projeção `library_node_folders`); reavaliar se um cliente passar de 50k arquivos ou se a busca de 2 letras em `U` ≥ 20 escopos estourar 150 ms em produção.


---

## 11. Migração dos dados existentes (default: um Espaço inicial com todos, sem quebrar ninguém)

**Objetivo:** no dia do deploy, **nenhuma** pessoa ganha ou perde acesso, nenhuma chave de API muda de alcance, nenhuma conversa é ocultada. Só depois, por ação do admin, os Espaços passam a restringir.

### 11.1 Passos (três deploys lógicos, todos reversíveis)

| Passo | O que acontece | Reversão |
|---|---|---|
| **M1 — Esquema** (`20261019_0035_spaces.py`) | Cria `spaces`, `space_members`, `space_folder_grants`; `+ membership_invitations.space_ids`; `+ organizations.spaces_resolver_mode` com `server_default='off'`. Nenhuma linha lida/gravada pelo app ainda. | `alembic downgrade 20261014_0034` (drop tabelas/colunas; nada de dados antigos foi tocado). |
| **M2 — Backfill** (`20261019_0036_spaces_backfill.py`, idempotente, mesma função `backfill_default_spaces(connection)` de `app/spaces/backfill.py` usada por teste) | Para **cada organização sem Espaço**: cria **"Geral"** (`is_default=true`, descrição "Espaço inicial — todos os membros e todas as pastas"); `space_members` para **todo** membro com `Membership.is_active` (Owner/Admin → `manager`, Member → `member`; `added_by=NULL`); `space_folder_grants` para **todo** `WorkspaceFolder` da organização (`disclosure={"text_version":"backfill","member_count":N,"acknowledged_at":null,"origin":"migration"}`, `granted_by=NULL`); define `spaces_resolver_mode='shadow'`. Reexecutar não duplica (guarda por `NOT EXISTS`). | Reexecutável; `downgrade` apaga só as linhas com `origin="migration"`. |
| **M3 — Enforce** (por organização, **sem migração**: `python -m app.spaces.rollout enforce --organization <id>` ou `--all-clean`) | Depois da janela em `shadow` com **zero divergência** (§11.2), muda `spaces_resolver_mode='enforce'`. Daí em diante o resolvedor é a fonte de verdade. | `... rollout shadow --organization <id>` volta ao legado em segundos (o modo é lido por request). |

**Dual-write entre M2 e M3 (T-A4):** durante `shadow`, qualquer **novo membro** (`OrganizationService.create_organization:40`, `add_membership:67`, `accept_invitation:179`) é inserido no Espaço padrão da organização; qualquer **nova pasta conectada** (`WorkspaceService.select_scope:78`) recebe concessão ao Espaço padrão. Sem isso, em `enforce` haveria pessoas/pastas "sem Espaço". `deactivate_membership` (`:233`) também marca `space_members.removed_at` (higiene; o resolvedor já ignora membership inativa).

**Organizações novas** (criadas depois do deploy): `create_organization` já cria "Geral" (criador = `manager`) e define `spaces_resolver_mode` = `settings.spaces_new_org_mode` (**padrão `shadow`** até a tela de Espaços e o passo "Quem poderá ver?" estarem no ar — R2 de §13 —, quando o padrão passa a `enforce`).

### 11.2 Janela `shadow`: como se prova que é seguro

Em `shadow` o resolvedor calcula `U_espaços` **e** o conjunto legado, **serve o legado** e registra (nível `WARNING`, só contagens — nunca nomes) `spaces.shadow_divergence {organization_id, user_id, only_legacy, only_spaces}` quando diferem. Como o backfill dá a todos todas as pastas, a divergência esperada é **0**; qualquer ≠ 0 indica bug (ex.: pasta criada sem concessão). O relatório `python -m app.spaces.rollout report` agrega por organização. **Critério para M3:** 7 dias corridos (ou 1 000 requests de `question_contexts`) sem divergência na organização.

### 11.3 Efeitos colaterais que precisam ser ditos

- **Chaves de API/MCP existentes** mantêm alcance no dia do deploy (Geral = tudo). Quando o admin restringir "Geral" ou tirar uma pasta dele, as chaves **encolhem junto** — comunicar na tela de Espaços ("N chaves de API dependem deste Espaço").
- **Conversas e notificações antigas** não têm `provenance` de pasta, mas têm `document_id` nas citações (`context.references`/`response.citations`); a ocultação usa isso. Notificações **antigas** sem `data.citations[].document_id` (formato anterior) não são ocultáveis ⇒ tratam-se como **ocultas se sem proveniência e o usuário perdeu algum acesso** (conservador) — T-H4 decide e testa.
- **Consultas salvas** continuam presas a uma pasta; se a pessoa perder a pasta, a consulta some da lista (não é apagada).
- **Teste de equivalência pós-migração (T-G3):** monta uma organização com 3 pessoas, 2 pastas e dados reais de teste, grava as respostas de `question_contexts`, árvore (`roots/children/search`), `mention_candidates` e `/v1/sources` **antes** do backfill (modo `off`) e **depois** (modo `enforce` com "Geral") e exige igualdade — critério de aceite nº 1.


---

## 12. Plano de tarefas

**Convenções de execução (valem para todas as tarefas):**
- Backend: `cd backend && .venv/bin/python -m pytest <caminho> -q` · lint `.venv/bin/python -m ruff check <caminhos>` · frontend: `cd frontend && node --test tests/<arquivo>.test.mjs` (os testes importam `.ts` direto; Node ≥ 22.13, `package.json:engines`).
- **Teste primeiro, sempre:** o passo "ver falhar" é obrigatório; um teste novo que já passa invalida a tarefa.
- Commit por tarefa, mensagem `[ESP-<id>] <o que>` (padrão do repo: `[WA-POC-05] …`), `git add` **só dos caminhos da tarefa** (nunca `-A`; há arquivos alheios modificados — `graphify-out/`, `frontend/tests/lane2-chat-motion.test.mjs` — e cópias `* 2.*` espalhadas que **não** são tocadas). Depois de tarefas de código: `graphify update .` (AGENTS.md).
- Estimativas em **dev-dias de quem conhece a base** (faixa), cada tarefa cabe em 0,25–2 dias.
- Dependências em `← T-X`. Paralelizável = sem `←` comum e sem arquivo comum (arquivos grandes `library/service.py` e `knowledge/questions.py` são **seriais**: uma tarefa por vez).

### Bloco A — Modelo, migração, serviço, defaults

#### T-A1 — Modelos `Space`, `SpaceMember`, `SpaceFolderGrant`  (0,5 d)
**Files:** Create `backend/app/spaces/__init__.py`, `backend/app/spaces/models.py` · Modify `backend/alembic/env.py:25` (registrar import) · Test `backend/tests/unit/test_spaces_models.py`
**Interfaces — Produces:** `Space(id, organization_id, name, name_key, description, is_default, archived_at, created_by_user_id)`, `SpaceMember(id, organization_id, space_id, user_id, role, added_by_user_id, removed_at, removed_by_user_id)`, `SpaceFolderGrant(id, organization_id, space_id, workspace_folder_id, granted_by_user_id, disclosure, revoked_at, revoked_by_user_id)`; constantes `SPACE_ROLE_MEMBER="member"`, `SPACE_ROLE_MANAGER="manager"`, `SPACE_ROLES`.
- [ ] **1. Teste que falha** — `backend/tests/unit/test_spaces_models.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.organizations.models import Organization
from app.spaces.models import Space, SpaceMember, SpaceFolderGrant  # noqa: F401


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def _org(session):
    org, user = Organization(name="Acme"), User(email="a@example.test")
    session.add_all([org, user])
    session.flush()
    return org, user


def test_active_space_names_are_unique_case_insensitively(session):
    org, _ = _org(session)
    session.add(Space(organization_id=org.id, name="RH", name_key="rh"))
    session.flush()
    session.add(Space(organization_id=org.id, name="rh", name_key="rh"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_only_one_active_default_space_per_organization(session):
    org, _ = _org(session)
    session.add(Space(organization_id=org.id, name="Geral", name_key="geral", is_default=True))
    session.flush()
    session.add(Space(organization_id=org.id, name="Outro", name_key="outro", is_default=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_member_is_unique_while_active_and_role_is_checked(session):
    org, user = _org(session)
    space = Space(organization_id=org.id, name="RH", name_key="rh")
    session.add(space)
    session.flush()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="member"))
    session.flush()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="member"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(SpaceMember(organization_id=org.id, space_id=space.id, user_id=user.id, role="owner"))
    with pytest.raises(IntegrityError):
        session.flush()
```
- [ ] **2.** `cd backend && .venv/bin/python -m pytest tests/unit/test_spaces_models.py -q` → esperado: **FAIL** `ModuleNotFoundError: No module named 'app.spaces'`.
- [ ] **3. Implementação** — `backend/app/spaces/models.py`:
```python
"""Spaces: named groups of people, granted explicit sync scopes (ADR-0021). No content is copied."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

SPACE_ROLE_MEMBER = "member"
SPACE_ROLE_MANAGER = "manager"
SPACE_ROLES = (SPACE_ROLE_MEMBER, SPACE_ROLE_MANAGER)


def _org_fk() -> Mapped[UUID]:
    return mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Space(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "spaces"

    organization_id: Mapped[UUID] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_spaces_org_name_active", Space.organization_id, Space.name_key, unique=True,
    postgresql_where=Space.archived_at.is_(None), sqlite_where=Space.archived_at.is_(None),
)
Index(
    "uq_spaces_org_default", Space.organization_id, unique=True,
    postgresql_where=Space.is_default.is_(True) & Space.archived_at.is_(None),
    sqlite_where=Space.is_default.is_(True) & Space.archived_at.is_(None),
)


class SpaceMember(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "space_members"
    __table_args__ = (CheckConstraint("role IN ('member','manager')", name="ck_space_member_role"),)

    organization_id: Mapped[UUID] = _org_fk()
    space_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=SPACE_ROLE_MEMBER)
    added_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_space_members_active", SpaceMember.space_id, SpaceMember.user_id, unique=True,
    postgresql_where=SpaceMember.removed_at.is_(None), sqlite_where=SpaceMember.removed_at.is_(None),
)
Index(
    "ix_space_members_user_active", SpaceMember.organization_id, SpaceMember.user_id,
    postgresql_where=SpaceMember.removed_at.is_(None), sqlite_where=SpaceMember.removed_at.is_(None),
)


class SpaceFolderGrant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A synchronized scope (WorkspaceFolder) belongs to a Space. Revocation is logical."""

    __tablename__ = "space_folder_grants"

    organization_id: Mapped[UUID] = _org_fk()
    space_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_folder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_folders.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    disclosure: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


Index(
    "uq_space_grants_active", SpaceFolderGrant.space_id, SpaceFolderGrant.workspace_folder_id, unique=True,
    postgresql_where=SpaceFolderGrant.revoked_at.is_(None), sqlite_where=SpaceFolderGrant.revoked_at.is_(None),
)
Index(
    "ix_space_grants_folder_active", SpaceFolderGrant.workspace_folder_id,
    postgresql_where=SpaceFolderGrant.revoked_at.is_(None), sqlite_where=SpaceFolderGrant.revoked_at.is_(None),
)
```
  e `backend/app/spaces/__init__.py` vazio; em `backend/alembic/env.py` acrescentar `from app.spaces.models import Space, SpaceFolderGrant, SpaceMember  # noqa: F401` junto aos demais imports.
- [ ] **4.** mesmo comando → **PASS** (3 passed). `.venv/bin/python -m ruff check app/spaces tests/unit/test_spaces_models.py` → sem erros.
- [ ] **5.** `git add backend/app/spaces backend/alembic/env.py backend/tests/unit/test_spaces_models.py && git commit -m "[ESP-A1] Space, SpaceMember and SpaceFolderGrant models"`

#### T-A2 — Migrações 0035 (esquema) e 0036 (backfill idempotente)  (1 d)  ← T-A1
**Files:** Create `backend/alembic/versions/20261019_0035_spaces.py`, `backend/alembic/versions/20261019_0036_spaces_backfill.py`, `backend/app/spaces/backfill.py` · Modify `backend/app/organizations/models.py` (coluna `spaces_resolver_mode` em `Organization`) e `backend/app/organizations/models.py` (`MembershipInvitation.space_ids`) · Test `backend/tests/unit/test_spaces_backfill.py`, `backend/tests/unit/test_spaces_migration_sql.py`
**Interfaces — Produces:** `backfill_default_spaces(connection) -> int` (nº de organizações preenchidas); `Organization.spaces_resolver_mode: str` (`"off"|"shadow"|"enforce"`); `MembershipInvitation.space_ids: list[str] | None`.
- [ ] **1. Testes que falham** — `backend/tests/unit/test_spaces_backfill.py`:
```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.identity.models import User
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipRole, Organization
from app.spaces.backfill import backfill_default_spaces
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _legacy_org(engine):
    with sessionmaker(bind=engine).begin() as s:
        org = Organization(name="Acme")
        owner, member, gone = (User(email=f"{n}@example.test") for n in ("o", "m", "g"))
        s.add_all([org, owner, member, gone])
        s.flush()
        s.add_all([
            Membership(organization_id=org.id, user_id=owner.id, role=MembershipRole.OWNER, is_active=True),
            Membership(organization_id=org.id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True),
            Membership(organization_id=org.id, user_id=gone.id, role=MembershipRole.MEMBER, is_active=False),
        ])
        source = DataSource(organization_id=org.id, provider="google_drive", encrypted_credentials="x",
                            status="connected", connected_by_user_id=owner.id)
        s.add(source)
        s.flush()
        for name in ("a", "b"):
            s.add(WorkspaceFolder(organization_id=org.id, source_id=source.id, external_folder_id=name,
                                  name=name, uniform_access_confirmed=True, status="ready"))
        return org.id


def test_backfill_creates_geral_with_everyone_and_every_folder():
    engine = _engine()
    org_id = _legacy_org(engine)
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 1
    with sessionmaker(bind=engine)() as s:
        space = s.scalar(select(Space).where(Space.organization_id == org_id))
        assert (space.name, space.is_default) == ("Geral", True)
        members = s.execute(select(SpaceMember.role).where(SpaceMember.space_id == space.id)).scalars().all()
        assert sorted(members) == ["manager", "member"]  # owner -> manager; inactive membership skipped
        assert len(s.scalars(select(SpaceFolderGrant).where(SpaceFolderGrant.space_id == space.id)).all()) == 2
        assert s.get(Organization, org_id).spaces_resolver_mode == "shadow"


def test_backfill_is_idempotent():
    engine = _engine()
    _legacy_org(engine)
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 1
    with engine.begin() as connection:
        assert backfill_default_spaces(connection) == 0
    with sessionmaker(bind=engine)() as s:
        assert len(s.scalars(select(Space)).all()) == 1
        assert len(s.scalars(select(SpaceMember)).all()) == 2
```
  e `backend/tests/unit/test_spaces_migration_sql.py` (mesmo padrão de `test_authentication_migration_sql.py`):
```python
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
URL = "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"


def test_offline_sql_creates_space_tables_and_skips_backfill() -> None:
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], cwd=BACKEND_DIR,
                            env=os.environ | {"DATABASE_URL": URL}, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for table in ("spaces", "space_members", "space_folder_grants"):
        assert f"CREATE TABLE {table}" in result.stdout
    assert "spaces_resolver_mode" in result.stdout
```
- [ ] **2.** `.venv/bin/python -m pytest tests/unit/test_spaces_backfill.py tests/unit/test_spaces_migration_sql.py -q` → **FAIL** (`ModuleNotFoundError: app.spaces.backfill`; `spaces_resolver_mode` inexistente).
- [ ] **3. Implementação.**
  (a) `Organization` ganha `spaces_resolver_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="off", server_default="off")`; `MembershipInvitation` ganha `space_ids: Mapped[list[str] | None] = mapped_column(JSON)` (acrescentar `JSON` ao import de `sqlalchemy`).
  (b) `20261019_0035_spaces.py` — `revision="20261019_0035"`, `down_revision="20261014_0034"`: `op.create_table` das três tabelas (mesmas colunas/tipos de T-A1, `sa.Uuid()`, `created_at … server_default=sa.func.now()`, `sa.CheckConstraint("role IN ('member','manager')", name="ck_space_member_role")`), os cinco índices parciais com `op.create_index(..., unique=..., postgresql_where=sa.text("archived_at IS NULL"))` (e equivalentes `removed_at IS NULL`/`revoked_at IS NULL`/`is_default AND archived_at IS NULL`), `op.add_column("organizations", sa.Column("spaces_resolver_mode", sa.String(8), nullable=False, server_default="off"))`, `op.add_column("membership_invitations", sa.Column("space_ids", sa.JSON()))`. `downgrade()` apaga índices, tabelas e colunas na ordem inversa.
  (c) `backend/app/spaces/backfill.py`:
```python
"""Idempotent first-run data for Spaces: one default Space per organization with everyone and everything."""

from uuid import uuid4

import sqlalchemy as sa

MIGRATION_DISCLOSURE = {"text_version": "backfill", "acknowledged_at": None, "origin": "migration"}


def backfill_default_spaces(connection: sa.Connection) -> int:
    meta = sa.MetaData()
    for table in ("organizations", "memberships", "workspace_folders", "spaces", "space_members", "space_folder_grants"):
        sa.Table(table, meta, autoload_with=connection)
    org, mem, folder = meta.tables["organizations"], meta.tables["memberships"], meta.tables["workspace_folders"]
    spaces, members, grants = meta.tables["spaces"], meta.tables["space_members"], meta.tables["space_folder_grants"]
    has_space = sa.exists().where(spaces.c.organization_id == org.c.id)
    pending = connection.execute(sa.select(org.c.id).where(~has_space)).scalars().all()
    for organization_id in pending:
        space_id = uuid4()
        connection.execute(spaces.insert().values(
            id=space_id, organization_id=organization_id, name="Geral", name_key="geral", is_default=True,
            description="Espaço inicial — todos os membros e todas as pastas"))
        for user_id, role in connection.execute(sa.select(mem.c.user_id, mem.c.role).where(
                mem.c.organization_id == organization_id, mem.c.is_active.is_(True))):
            connection.execute(members.insert().values(
                id=uuid4(), organization_id=organization_id, space_id=space_id, user_id=user_id,
                role="manager" if str(role).lower().endswith(("owner", "admin")) else "member"))
        folder_ids = connection.execute(sa.select(folder.c.id).where(folder.c.organization_id == organization_id)).scalars().all()
        member_count = connection.execute(sa.select(sa.func.count()).select_from(members).where(members.c.space_id == space_id)).scalar_one()
        for folder_id in folder_ids:
            connection.execute(grants.insert().values(
                id=uuid4(), organization_id=organization_id, space_id=space_id, workspace_folder_id=folder_id,
                disclosure={**MIGRATION_DISCLOSURE, "member_count": member_count}))
        connection.execute(org.update().where(org.c.id == organization_id).values(spaces_resolver_mode="shadow"))
    return len(pending)
```
  (d) `20261019_0036_spaces_backfill.py` — `down_revision="20261019_0035"`; `upgrade()`: `if op.get_context().as_sql: return` (o `--sql` offline de `test_authentication_migration_sql.py` não tem conexão) senão `backfill_default_spaces(op.get_bind())`; `downgrade()`: apagar `space_folder_grants`/`space_members`/`spaces` cujo `disclosure->>'origin'='migration'` (grants) e Espaços "Geral" sem concessões residuais **somente se** nenhuma concessão manual existir (senão manter e logar) — comentar no código que o `downgrade` de dados é de melhor esforço e que o rollback seguro é `rollout shadow`/`off` (§11).
- [ ] **4.** mesmo comando → **PASS**; `.venv/bin/python -m pytest tests/unit/test_authentication_migration_sql.py -q` continua verde.
- [ ] **5.** `git add backend/alembic/versions/20261019_0035_spaces.py backend/alembic/versions/20261019_0036_spaces_backfill.py backend/app/spaces/backfill.py backend/app/organizations/models.py backend/tests/unit/test_spaces_backfill.py backend/tests/unit/test_spaces_migration_sql.py && git commit -m "[ESP-A2] spaces schema migration and idempotent default-space backfill"`
- **Verificação extra com Postgres (manual, uma vez):** `TEST_DATABASE_URL=… alembic upgrade head` num banco descartável e `alembic downgrade 20261014_0034` — o banco local de dev pode ser recriado (memória do projeto: fase de testes).

#### T-A3 — `SpaceService`: criar/renomear/arquivar, membros, concessões, auditoria  (1,5 d)  ← T-A1
**Files:** Create `backend/app/spaces/service.py` · Test `backend/tests/unit/test_space_service.py`
**Interfaces — Produces** (todas recebem `scope: OrganizationScope`, `actor_user_id: UUID`, lançam `SpaceDenied`/`SpaceConflict`/`SpaceNotFound` definidas no módulo):
`create_space(scope, actor_user_id, name, description=None, is_default=False) -> Space` · `rename_space(..., space_id, name, description)` · `archive_space(..., space_id)` · `set_default(..., space_id)` · `add_member(..., space_id, user_id, role="member") -> SpaceMember` · `remove_member(..., space_id, user_id) -> SpaceMember` · `set_member_role(..., space_id, user_id, role)` · `grant_folder(..., space_id, workspace_folder_id, disclosure) -> SpaceFolderGrant` · `revoke_folder(..., space_id, workspace_folder_id)` · `list_spaces_for_actor(scope, actor_user_id) -> list[SpaceView]` · `members(scope, actor_user_id, space_id)` · `default_space_id(session, organization_id) -> UUID | None`.
**Regras codificadas (cada uma com teste):** só `owner/admin` criam/arquivam/definem padrão/concedem pasta; `manager` (do próprio Espaço) e `owner/admin` adicionam/removem membros e mudam papéis; **só adiciona quem tem `Membership` ativa na organização**; adicionar quem já está ativo é idempotente (devolve a linha existente); `grant_folder` exige `WorkspaceFolder.organization_id == scope.organization_id` e `disclosure` com `text_version`; cada operação grava `AuditLog` (`space.created|renamed|archived|member_added|member_removed|member_role_changed|folder_granted|folder_revoked`, `target_type="space"`, `target_id=space.id`); operação sobre Espaço de **outra** organização ⇒ `SpaceNotFound` (indistinguível de inexistente).
- [ ] **1. Teste que falha** — `backend/tests/unit/test_space_service.py` (fixture e semeadura iguais às de T-A1; usar o helper de T-B2 `tests/spaces_helpers.py` quando existir, antes dele montar inline): casos nomeados e asserções —
  `test_only_admins_create_spaces` (`member` ⇒ `SpaceDenied`; `admin` ⇒ cria; `name_key` = nome em minúsculas),
  `test_duplicate_active_name_conflicts` (⇒ `SpaceConflict`; após arquivar o primeiro, o nome fica livre),
  `test_manager_manages_only_own_space` (manager do RH adiciona Bruno ao RH ✔; adiciona ao Diretoria ⇒ `SpaceDenied`),
  `test_cannot_add_user_without_active_membership` (usuário de outra org / membership inativa ⇒ `SpaceDenied`),
  `test_add_member_is_idempotent_and_remove_is_logical` (`removed_at` preenchido; readicionar cria **nova** linha ativa; histórico mantém a antiga),
  `test_grant_requires_disclosure_and_same_org_folder`,
  `test_every_mutation_writes_an_audit_log` (conta `AuditLog` por ação),
  `test_foreign_org_space_is_not_found`.
- [ ] **2.** `.venv/bin/python -m pytest tests/unit/test_space_service.py -q` → **FAIL** `ModuleNotFoundError: app.spaces.service`.
- [ ] **3. Implementação** em `backend/app/spaces/service.py` seguindo os padrões de `organizations/service.py` (`_require_owner`, `_record_membership_audit`) — um `_actor_role(scope, actor_user_id) -> MembershipRole | None` central consulta `Membership` ativa; `_require_admin` = `owner|admin`; `_require_manager_or_admin(space_id)` = admin ∨ `SpaceMember.role=='manager'` ativo naquele Espaço.
- [ ] **4.** mesmo comando → **PASS**; ruff limpo.
- [ ] **5.** `git add backend/app/spaces/service.py backend/tests/unit/test_space_service.py && git commit -m "[ESP-A3] SpaceService with roles, audit and logical removal"`

#### T-A4 — Defaults: novo membro → Espaço padrão; nova pasta → concessão padrão; criação de organização → "Geral"  (1 d)  ← T-A3
**Files:** Modify `backend/app/organizations/service.py:40-66,67-83,179-209,233-254` · `backend/app/workspaces/service.py:78-107` · `backend/app/core/config.py` (`spaces_new_org_mode`) · Test `backend/tests/unit/test_space_defaults.py`
**Regras:** `create_organization` cria "Geral" (criador = `manager`) e define `spaces_resolver_mode = settings.spaces_new_org_mode` (nova chave em `backend/app/core/config.py`, padrão `"shadow"`; vira `"enforce"` no R2 — §13.2); `add_membership`/`accept_invitation` inserem a pessoa em `invitation.space_ids` **se houver**, senão no Espaço padrão (se existir); `select_scope` ganha `space_ids: Sequence[UUID] | None = None` — `None` ⇒ concede ao Espaço padrão; lista ⇒ concede a cada um (validando que pertencem à organização); `deactivate_membership` marca `space_members.removed_at` das linhas ativas da pessoa.
- [ ] **1. Teste que falha** — `test_space_defaults.py`: `test_new_org_gets_geral_with_owner_manager_and_configured_mode`; `test_accept_invitation_joins_default_space`; `test_accept_invitation_with_space_ids_joins_only_those`; `test_select_scope_without_space_ids_grants_default_space`; `test_select_scope_with_space_ids_grants_each_and_records_disclosure`; `test_select_scope_second_call_does_not_duplicate_grant` (mesmo `scope_key` ⇒ mesma `WorkspaceFolder`; `count(SpaceFolderGrant)` inalterado); `test_deactivate_membership_marks_space_membership_removed`.
- [ ] **2.** `.venv/bin/python -m pytest tests/unit/test_space_defaults.py -q` → **FAIL** (`create_organization` não cria Espaço; `select_scope` não aceita `space_ids`).
- [ ] **3. Implementação** conforme as regras; `uniform_access_confirmed` **continua obrigatório** (mensagem de erro inalterada, `workspaces/service.py:81`); o texto de ciência muda só na UI (T-F6).
- [ ] **4.** PASS; rodar também `tests/unit/test_company_library.py tests/api/test_workspace_folder_management_api.py tests/unit/test_invitation_service.py -q` (regressão: continuam verdes — `select_scope` mantém o contrato antigo para quem não passa `space_ids`).
- [ ] **5.** `git add <4 caminhos> && git commit -m "[ESP-A4] default Space enrollment for members, scopes and new organizations"`

### Bloco B — Resolvedor único

#### T-B1 — Helpers de teste `tests/spaces_helpers.py`  (0,5 d)  ← T-A1
**Files:** Create `backend/tests/spaces_helpers.py` · Test (usado pelos demais; auto-teste em `backend/tests/unit/test_spaces_helpers.py`)
**Interfaces — Produces:** `seed_world(session) -> World` (organização "Acme"; usuários `eva` (owner, só Geral), `ana` (member: Geral+RH, manager do RH), `bruno` (member: Geral+RH), `carla` (member: Geral+RH+Diretoria), `daniel` (member: Geral+Diretoria); pastas `politicas`→Geral, `rh`→RH, `diretoria`→Diretoria (cada `WorkspaceFolder` `status="ready"`, 1 `Document` `indexed`, 1 `DocumentChunk` embedded, nós `LibraryNode` fonte+arquivo); `spaces_resolver_mode="enforce"`), `World(organization_id, users, spaces, folders, documents, nodes)` (dicionários `str → UUID`).
- [ ] **1.** `test_spaces_helpers.py`: `test_world_matches_the_acme_example` — afirma as pertenças acima via consultas diretas a `SpaceMember`/`SpaceFolderGrant`.
- [ ] **2.** pytest → FAIL (módulo inexistente). **3.** Implementar copiando o padrão de `tests/access_helpers.py:28-64` (`seed_tenant`) para várias pastas. **4.** PASS. **5.** commit `[ESP-B1] Acme multi-space seed helper for tests`.

#### T-B2 — `SpaceAccessResolver` (+ modo `off|shadow|enforce`)  (2 d)  ← T-B1
**Files:** Create `backend/app/spaces/access.py` · Test `backend/tests/unit/test_space_access_resolver.py`
**Interfaces — Consumes:** modelos de T-A1; `SyncAccessDenied` (`app.ingestion.service`); `OrganizationScope` (`app.core.scoping`). **Produces:** `SpaceRef`, `SpaceAccess`, `SpaceAccessResolver` (assinaturas de §4.1), `MODE_OFF/MODE_SHADOW/MODE_ENFORCE`.
- [ ] **1. Testes que falham** — `backend/tests/unit/test_space_access_resolver.py`:
```python
import pytest
from sqlalchemy import event

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.organizations.models import Membership
from app.spaces.access import SpaceAccessResolver
from app.spaces.models import SpaceFolderGrant, SpaceMember
from tests.spaces_helpers import seed_world  # fixture `session` igual à de test_spaces_models.py


def resolve(session, world, who, **kw):
    return SpaceAccessResolver(session).resolve(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who], **kw)


def test_access_is_the_union_of_the_users_spaces(session):
    world = seed_world(session)
    assert resolve(session, world, "carla").folder_ids == {
        world.folders["politicas"], world.folders["rh"], world.folders["diretoria"]}
    assert resolve(session, world, "daniel").folder_ids == {world.folders["politicas"], world.folders["diretoria"]}


def test_org_owner_is_not_a_reader_of_spaces_they_are_not_in(session):
    world = seed_world(session)
    assert resolve(session, world, "eva").folder_ids == {world.folders["politicas"]}


def test_space_filter_only_narrows_and_never_widens(session):
    world = seed_world(session)
    rh, diretoria = world.spaces["rh"], world.spaces["diretoria"]
    assert resolve(session, world, "ana", space_ids=[rh]).folder_ids == {world.folders["rh"]}
    assert resolve(session, world, "ana", space_ids=[diretoria]).folder_ids == frozenset()  # ana is not in Diretoria
    assert resolve(session, world, "ana", space_ids=[]).folder_ids == frozenset()  # explicit empty = nothing (fail-closed)


def test_removed_member_revoked_grant_and_archived_space_all_cut_access(session):
    world = seed_world(session)
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    session.query(SpaceMember).filter_by(space_id=world.spaces["rh"], user_id=world.users["bruno"]).update({"removed_at": now})
    session.query(SpaceFolderGrant).filter_by(workspace_folder_id=world.folders["diretoria"]).update({"revoked_at": now})
    session.flush()
    assert resolve(session, world, "bruno").folder_ids == {world.folders["politicas"]}
    assert resolve(session, world, "carla").folder_ids == {world.folders["politicas"], world.folders["rh"]}


def test_inactive_organization_membership_denies_before_looking_at_spaces(session):
    world = seed_world(session)
    session.query(Membership).filter_by(user_id=world.users["ana"]).update({"is_active": False})
    session.flush()
    with pytest.raises(SyncAccessDenied):
        resolve(session, world, "ana")


def test_badges_list_only_the_callers_own_spaces(session):
    world = seed_world(session)
    # the RH folder is also granted to Diretoria; Bruno is not in Diretoria
    session.add(SpaceFolderGrant(organization_id=world.organization_id, space_id=world.spaces["diretoria"],
                                 workspace_folder_id=world.folders["rh"], disclosure={"text_version": "v1"}))
    session.flush()
    names = [ref.name for ref in resolve(session, world, "bruno").spaces_of(world.folders["rh"])]
    assert names == ["RH"]
    assert [ref.name for ref in resolve(session, world, "carla").spaces_of(world.folders["rh"])] == ["Diretoria", "RH"]


def test_database_errors_propagate_instead_of_opening_access(session, monkeypatch):
    world = seed_world(session)
    resolver = SpaceAccessResolver(session)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "execute", boom)
    with pytest.raises(RuntimeError):
        resolver.resolve(scope=OrganizationScope(world.organization_id), user_id=world.users["ana"])


def test_constant_number_of_statements_regardless_of_folder_count(session):
    world = seed_world(session)
    seen: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda c, cur, st, p, ctx, m: seen.append(st))
    resolve(session, world, "carla")
    assert len(seen) <= 4, seen


def test_off_mode_returns_every_folder_and_shadow_serves_legacy(session):
    world = seed_world(session)
    from app.organizations.models import Organization
    for mode in ("off", "shadow"):
        session.get(Organization, world.organization_id).spaces_resolver_mode = mode
        session.flush()
        assert resolve(session, world, "daniel").folder_ids == set(world.folders.values())
    session.get(Organization, world.organization_id).spaces_resolver_mode = "enforce"
    session.flush()
    assert resolve(session, world, "daniel").folder_ids == {world.folders["politicas"], world.folders["diretoria"]}


def test_shadow_logs_divergence_counts_only(session, caplog):
    world = seed_world(session)
    from app.organizations.models import Organization
    session.get(Organization, world.organization_id).spaces_resolver_mode = "shadow"
    session.flush()
    with caplog.at_level("WARNING", logger="app.spaces.access"):
        resolve(session, world, "daniel")  # legacy = 3 folders, spaces = 2 -> only_legacy == 1
    record = next(r for r in caplog.records if r.getMessage() == "spaces.shadow_divergence")
    assert (record.only_legacy, record.only_spaces) == (1, 0)
    assert "Diretoria" not in caplog.text  # only counts are logged, never names
```
- [ ] **2.** `.venv/bin/python -m pytest tests/unit/test_space_access_resolver.py -q` → **FAIL** `ModuleNotFoundError: No module named 'app.spaces.access'`.
- [ ] **3. Implementação** — `backend/app/spaces/access.py`:
```python
"""The single answer to "which synchronized scopes may this person read?" (ADR-0021)."""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.organizations.models import Membership, Organization
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder

logger = logging.getLogger(__name__)
MODE_OFF, MODE_SHADOW, MODE_ENFORCE = "off", "shadow", "enforce"


@dataclass(frozen=True)
class SpaceRef:
    id: UUID
    name: str


@dataclass(frozen=True)
class SpaceAccess:
    organization_id: UUID
    user_id: UUID
    spaces: Mapping[UUID, SpaceRef]
    folder_spaces: Mapping[UUID, frozenset[UUID]]

    @property
    def folder_ids(self) -> frozenset[UUID]:
        return frozenset(self.folder_spaces)

    def allows(self, folder_id: UUID) -> bool:
        return folder_id in self.folder_spaces

    def spaces_of(self, folder_id: UUID) -> tuple[SpaceRef, ...]:
        refs = (self.spaces[space_id] for space_id in self.folder_spaces.get(folder_id, ()) if space_id in self.spaces)
        return tuple(sorted(refs, key=lambda ref: (ref.name.casefold(), str(ref.id))))


class SpaceAccessResolver:
    def __init__(self, session: Session):
        self.session = session

    def resolve(self, *, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None = None) -> SpaceAccess:
        self._require_active_member(scope, user_id)
        mode = self._mode(scope.organization_id)
        if mode == MODE_OFF:
            return self._legacy(scope, user_id)
        granted = self._granted(scope, user_id, space_ids)
        if mode == MODE_SHADOW:
            legacy = self._legacy(scope, user_id)
            only_legacy, only_spaces = legacy.folder_ids - granted.folder_ids, granted.folder_ids - legacy.folder_ids
            if only_legacy or only_spaces:
                logger.warning("spaces.shadow_divergence", extra={
                    "organization_id": str(scope.organization_id), "user_id": str(user_id),
                    "only_legacy": len(only_legacy), "only_spaces": len(only_spaces)})
            return legacy
        return granted

    def require_folders(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_ids: Collection[UUID]) -> list[WorkspaceFolder]:
        access = self.resolve(scope=scope, user_id=user_id)
        wanted = list(dict.fromkeys(workspace_folder_ids))
        if any(folder_id not in access.folder_ids for folder_id in wanted):
            raise SyncAccessDenied("workspace access denied")
        rows = list(self.session.scalars(select(WorkspaceFolder).where(
            WorkspaceFolder.id.in_(wanted), WorkspaceFolder.organization_id == scope.organization_id)))
        if len(rows) != len(wanted):
            raise SyncAccessDenied("workspace access denied")
        return rows

    def require_folder(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID) -> WorkspaceFolder:
        return self.require_folders(scope=scope, user_id=user_id, workspace_folder_ids=[workspace_folder_id])[0]

    # -- internals ---------------------------------------------------------------------------
    def _require_active_member(self, scope: OrganizationScope, user_id: UUID) -> None:
        member = self.session.scalar(select(Membership.id).where(
            Membership.organization_id == scope.organization_id, Membership.user_id == user_id,
            Membership.is_active.is_(True)))
        if member is None:
            raise SyncAccessDenied("company library access denied")

    def _mode(self, organization_id: UUID) -> str:
        return self.session.scalar(
            select(Organization.spaces_resolver_mode).where(Organization.id == organization_id)) or MODE_OFF

    def _legacy(self, scope: OrganizationScope, user_id: UUID) -> SpaceAccess:
        ids = self.session.scalars(select(WorkspaceFolder.id).where(WorkspaceFolder.organization_id == scope.organization_id))
        return SpaceAccess(scope.organization_id, user_id, {}, {folder_id: frozenset() for folder_id in ids})

    def _granted(self, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None) -> SpaceAccess:
        org = scope.organization_id
        spaces_query = (select(Space.id, Space.name)
                        .join(SpaceMember, SpaceMember.space_id == Space.id)
                        .where(Space.organization_id == org, Space.archived_at.is_(None),
                               SpaceMember.organization_id == org, SpaceMember.user_id == user_id,
                               SpaceMember.removed_at.is_(None)))
        if space_ids is not None:
            spaces_query = spaces_query.where(Space.id.in_(list(space_ids)))
        spaces = {space_id: SpaceRef(space_id, name) for space_id, name in self.session.execute(spaces_query)}
        folder_spaces: dict[UUID, set[UUID]] = {}
        if spaces:
            rows = self.session.execute(
                select(SpaceFolderGrant.workspace_folder_id, SpaceFolderGrant.space_id)
                .join(WorkspaceFolder, WorkspaceFolder.id == SpaceFolderGrant.workspace_folder_id)
                .where(SpaceFolderGrant.organization_id == org, SpaceFolderGrant.revoked_at.is_(None),
                       SpaceFolderGrant.space_id.in_(list(spaces)), WorkspaceFolder.organization_id == org))
            for folder_id, space_id in rows:
                folder_spaces.setdefault(folder_id, set()).add(space_id)
        return SpaceAccess(org, user_id, spaces, {k: frozenset(v) for k, v in folder_spaces.items()})
```
- [ ] **4.** PASS (9 testes) e `ruff check app/spaces/access.py`. Observação: 1 (membership) + 1 (modo) + 2 (`_granted`: Espaços e concessões) = **4 instruções**, valor travado por `test_constant_number_of_statements…`.
- [ ] **5.** `git add backend/app/spaces/access.py backend/tests/unit/test_space_access_resolver.py && git commit -m "[ESP-B2] SpaceAccessResolver with fail-closed union and rollout modes"`

#### T-B3 — Invariantes de propriedade ("nenhum caminho devolve fora de `U`")  (1 d)  ← T-B2, T-B4, T-D1, T-E3 (executar por último do bloco; escrever o esqueleto cedo)
**Files:** Create `backend/tests/unit/test_spaces_access_invariants.py` · Modify `backend/tests/unit/test_scope_invariant.py` (acrescentar `space_ids`/`spaces` à lista de parâmetros que as ferramentas do agente **não** podem receber do modelo: `FORBIDDEN` linha 7)
- [ ] **1.** Teste parametrizado por (`pessoa` × `superfície`) sobre `seed_world`: superfícies = `question_contexts`, `roots/children/search_page`, `mention_candidates`, `resolve_question_selection`, `RetrievalService.search/fetch`, `scoped_document`, `ScopedAccess.selection` (chave) e MCP `run_search/run_fetch/run_list_sources`. Asserção única: **todo `document_id`/`folder_id`/`node_id` devolvido ∈ conjunto esperado para a pessoa** (tabela do exemplo Acme); para ids de fora ⇒ exceção "indisponível"/`ToolNotFound`/404. Falha enquanto qualquer superfície ainda não usa o resolvedor.
- [ ] **2.** pytest → **FAIL** para as superfícies ainda não migradas (lista no erro). **3.** Nada a implementar aqui: cada tarefa de superfície faz seu caso passar. **4.** Ao fim do plano: **PASS** total. **5.** commit `[ESP-B3] access invariant matrix: person x surface`.

#### T-B4 — Integrar `question_contexts`, `WorkspaceService`, `QuestionService.ask` (batch, sem N+1)  (2 d)  ← T-B2
**Files:** Modify `backend/app/library/service.py:42-52,911-964` · `backend/app/workspaces/service.py:34-45` · `backend/app/knowledge/questions.py:1137-1143` · `backend/app/knowledge/search.py:61` · Test `backend/tests/unit/test_space_integration_core.py`
**Interfaces — Consumes:** `SpaceAccessResolver` (T-B2). **Produces:** `LibraryContext.spaces: tuple[SpaceRef, ...] = ()`; `question_contexts(self, *, scope, user_id, space_ids: Collection[UUID] | None = None)`.
- [ ] **1. Testes que falham** — `test_space_integration_core.py`: `test_question_contexts_return_only_accessible_folders_with_badges` (Daniel: 2 contextos; `contexts[i].spaces` só Geral/Diretoria); `test_question_contexts_space_filter_narrows` (Carla, `space_ids=[rh]` ⇒ só RH); `test_require_member_access_denies_folder_outside_spaces` (Bruno + pasta Diretoria ⇒ `GoogleAccessDenied("workspace access denied")`, **mesma exceção de hoje**); `test_ask_with_many_folders_runs_one_membership_query` (conta instruções contendo `FROM memberships` durante `QuestionService.ask` com 3 pastas **== 1**; hoje, uma por pasta); `test_org_scope_question_for_daniel_never_cites_rh` (usando `FakeProvider` de `tests/unit/test_semantic_questions.py:39`); `test_off_mode_matches_legacy_behaviour` (mesmas respostas de antes da mudança).
- [ ] **2.** pytest do arquivo → **FAIL** (`question_contexts() got an unexpected keyword argument 'space_ids'`; N consultas de membership).
- [ ] **3. Implementação:**
  `library/service.py` — em `question_contexts`, depois de `self.require_member(...)`: `access = SpaceAccessResolver(self.session).resolve(scope=scope, user_id=user_id, space_ids=space_ids)`; acrescentar ao `.where(...)` da consulta `WorkspaceFolder.id.in_(list(access.folder_ids))`; no `LibraryContext(...)` passar `spaces=access.spaces_of(folder.id)`; o dataclass ganha `spaces: tuple[SpaceRef, ...] = ()` (import de `SpaceRef` de `app.spaces.access`; sem ciclo: `spaces.access` não importa `library`).
  `workspaces/service.py` — `require_member_access` vira: `try: return SpaceAccessResolver(self.session).require_folder(...) except SyncAccessDenied as error: raise GoogleAccessDenied("workspace access denied") from error`; `folders` filtra por `access.folder_ids` (membro) — a variante de administração é T-C2.
  `knowledge/questions.py:1137-1143` — substituir o laço por `folders = {f.id: f for f in SpaceAccessResolver(self.session).require_folders(scope=scope, user_id=user_id, workspace_folder_ids=folder_ids)}` (traduzir `SyncAccessDenied → GoogleAccessDenied` como no `ask_selection`), mantendo a checagem `folder_is_queryable` por pasta, em memória.
  `knowledge/search.py:61` — mesma troca de `require_member_access`.
- [ ] **4.** PASS; regressão: `.venv/bin/python -m pytest tests/unit/test_company_library.py tests/unit/test_library_authorized_catalog.py tests/unit/test_semantic_questions.py tests/unit/test_agent_flow.py tests/api/test_multiscope_questions_api.py tests/api/test_public_v1.py tests/api/test_mcp_server.py -q` verdes (organizações semeadas pelos helpers antigos têm `spaces_resolver_mode="off"` — o `server_default` — então o comportamento é o legado).
- [ ] **5.** `git add backend/app/library/service.py backend/app/workspaces/service.py backend/app/knowledge/questions.py backend/app/knowledge/search.py backend/tests/unit/test_space_integration_core.py && git commit -m "[ESP-B4] route question_contexts and folder access through the SpaceAccessResolver"`

#### T-B5 — Rotas por pasta em `api/ingestion.py` (leitura vs. operação de admin)  (1 d)  ← T-B4, T-C2
**Files:** Modify `backend/app/api/ingestion.py:94-290,438-` · Test `backend/tests/api/test_workspace_folder_space_access_api.py`
- [ ] **1.** Testes: `GET/POST /workspace-folders/{id}/search|questions|documents` — membro fora do Espaço ⇒ 404 (não 403: I7); admin não-membro em `/documents` ⇒ 200 **sem nomes** (`items[].name` ausente, `counts` presentes); admin após "entrar" ⇒ nomes; `POST …/sync`, `…/reprocess`, `DELETE …` por admin não-membro ⇒ continuam permitidos; por membro comum ⇒ 403 como hoje.
- [ ] **2.** FAIL (hoje: 200 para qualquer membro). **3.** Implementar com `SpaceAccessResolver`; operações administrativas passam por `_require_org_admin` e `WorkspaceFolder.organization_id`. **4.** PASS + `tests/api/test_workspace_folder_management_api.py -q` verde. **5.** commit `[ESP-B5] folder routes: read by Space, operate by role`.


### Bloco C — API de administração, papéis, contexto da pergunta

#### T-C1 — Router `/organizations/{id}/spaces…` + matriz de papéis  (2 d)  ← T-A3, T-B2
**Files:** Create `backend/app/api/spaces.py` · Modify `backend/app/main.py:~193` (`app.include_router(spaces_router, dependencies=authenticated)`; o teste `tests/api/test_route_authorization.py` falha se um roteador privado ficar sem `authenticated`) · Test `backend/tests/api/test_spaces_api.py`, `backend/tests/api/test_space_roles_api.py`
**Rotas (todas sob `/organizations/{organization_id}`):** `GET /spaces` · `POST /spaces` (admin) · `PATCH /spaces/{space_id}` · `DELETE /spaces/{space_id}` (arquiva; admin) · `GET /spaces/{space_id}/members` · `POST /spaces/{space_id}/members` `{user_id, role}` · `PATCH /spaces/{space_id}/members/{user_id}` `{role}` · `DELETE /spaces/{space_id}/members/{user_id}` · `GET /spaces/{space_id}/members/{user_id}/impact` · `POST /spaces/{space_id}/folders/{workspace_folder_id}` `{disclosure:{text_version}}` (admin) · `DELETE /spaces/{space_id}/folders/{workspace_folder_id}` (admin) · `POST /spaces/{space_id}/enter` (admin: auto-inclusão + `space.admin_entered`).
**Erros:** Espaço de outra organização ou em que o chamador não pode nem *ver* ⇒ **404 `{"detail":"space not found"}`**; papel insuficiente num Espaço visível ⇒ 403 `{"detail":"not allowed"}`; nome duplicado ⇒ 409.
- [ ] **1. Testes que falham** (`test_space_roles_api.py`, `TestClient` + `seed_world`; sessão de cada usuário como em `tests/api/test_company_library_api.py`): matriz parametrizada **papel × ação** — `eva` (owner): cria/arquiva/concede ✔, adiciona qualquer pessoa ✔; `ana` (manager do RH): adiciona Bruno ao RH ✔, adiciona ao Diretoria ⇒ 404, `POST /spaces` ⇒ 403, concede pasta ⇒ 403; `bruno` (member): `GET /spaces` lista **só** Geral e RH, `POST members` ⇒ 403; `daniel` (member) `GET /spaces/{rh}/members` ⇒ **404** (não existe para ele); usuário de outra organização ⇒ 404 em tudo; `POST /spaces/{diretoria}/enter` por `eva` ⇒ 200, depois `eva` lê a pasta Diretoria e existe `AuditLog(action="space.admin_entered")`; `impact` para Bruno/RH devolve `documents_lost==1` (o doc do RH; Geral continua), `conversations_hidden`, `automations_paused`, `followed_queries_cleared` inteiros ≥ 0.
- [ ] **2.** `.venv/bin/python -m pytest tests/api/test_space_roles_api.py tests/api/test_spaces_api.py -q` → **FAIL** (404 em todas as rotas: roteador inexistente).
- [ ] **3. Implementação** reutilizando `SpaceService` (T-A3) e o helper de sessão/usuário de `api/access_admin.py:49-61` (`_require_admin`, `_audit`); respostas só com `id,name,description,is_default,member_count,folder_count,my_role` (nunca listar Espaços alheios). `impact` fica em stub que devolve `documents_lost` real (diferença de `U`) e zeros para os demais — T-H6 completa os contadores.
- [ ] **4.** PASS + `tests/api/test_route_authorization.py -q` verde. **5.** `git add backend/app/api/spaces.py backend/app/main.py backend/tests/api/test_spaces_api.py backend/tests/api/test_space_roles_api.py && git commit -m "[ESP-C1] Spaces admin API with owner/manager/member matrix"`

#### T-C2 — `GET /workspace-folders` com Espaços; visão operacional do admin sem nomes de arquivo  (1 d)  ← T-B4
**Files:** Modify `backend/app/workspaces/service.py` (novo `folders_admin`), `backend/app/api/integrations.py:855-900`, `backend/app/api/insights.py:~74` (apenas totais) · Test `backend/tests/api/test_workspace_folders_spaces_api.py`
- [ ] **1.** Testes: membro comum (`bruno`) lista só pastas de `U`, cada item com `spaces:[{id,name}]` **somente dos Espaços dele**; admin (`eva`) lista **todas** as pastas com `spaces` **de todos os Espaços** (é config) e `readable: false` para as que ele não lê; resposta do admin **não** contém nomes de arquivo; pasta sem concessão aparece só ao admin com `spaces: []`.
- [ ] **2.** FAIL (hoje lista tudo para todos, sem `spaces`). **3.** `folders_admin` = metadados operacionais (usado só quando o papel da organização é `owner|admin`); `folders` (membro) filtra por `access.folder_ids`. **4.** PASS + `tests/api/test_google_integrations.py -q` verde. **5.** commit `[ESP-C2] workspace-folders list is Space-aware; admins see operational metadata`.

#### T-C3 — `spaces` no `question-contexts` e `space_ids` na pergunta (do payload ao `question_contexts`)  (2 d)  ← T-B4  (**serial** com T-B4: mesmos arquivos grandes)
**Files:** Modify `backend/app/api/library.py:108-136` · `backend/app/api/ingestion.py:60-66,320-405` (`QuestionInput.space_ids: list[UUID] | None`, validação `max_length=50`; lista vazia ⇒ `None`) · `backend/app/knowledge/questions.py:982-1034` (`ask_selection(..., space_ids=None)`) · `backend/app/knowledge/agent.py` (`AgentRequest.space_ids: tuple[UUID, ...] | None = None`, repassar em `AgentService.ask` e nos `LibraryToolExecutor.*` que chamam `resolve_question_selection`/`authorized_catalog`) · `backend/app/library/service.py:1002-1031,1124-1157` (`space_ids` opcional em `authorized_catalog`/`resolve_question_selection`, repassado a `question_contexts`) · `backend/tests/unit/test_scope_invariant.py:7` (`FORBIDDEN` ganha `"space_ids"` — o **modelo** nunca fornece escopo) · Test `backend/tests/api/test_space_filter_questions_api.py`
- [ ] **1. Testes que falham:** `question-contexts` traz `spaces` por item e é idêntico ao anterior em organização `off`; `POST …/questions` com `scope="selection"` e `space_ids=[rh]` para Carla ⇒ `resolved_context.folder_count == 1` e `citations` só do RH; `space_ids=[diretoria]` para Bruno ⇒ **404** `{"detail":"space not found"}` (não 403); `space_ids` omitido ⇒ união (`folder_count==3` para Carla); histórico grava `context.space_ids` (só o pedido; **não** autoriza); o agente não aceita `space_ids` vindo de argumentos de ferramenta (`test_scope_invariant` verde com `FORBIDDEN` ampliado).
- [ ] **2.** FAIL (`space_ids` ignorado/422). **3.** Implementação conforme lista de arquivos; erro de `space_ids` alheio vira `SpaceNotFound` no resolvedor quando `strict=True` (parâmetro novo de `resolve`, usado só pelas rotas; os demais chamadores seguem descartando silenciosamente). **4.** PASS + `tests/unit/test_agent_flow.py tests/unit/test_scope_invariant.py tests/api/test_multiscope_questions_api.py -q` verdes. **5.** commit `[ESP-C3] Space filter flows from the question payload to the resolver`.

### Bloco D — Biblioteca (árvore, busca por nome, derivados de catálogo)

> Serial: todas tocam `backend/app/library/service.py` (1 579 linhas). Uma tarefa por vez; commits pequenos.

#### T-D0 — Linha de base de escala  (0,5 d)  ← T-B4
**Files:** Create `spikes/library-scale/results/api_10k_spaces.json` (saída) · Modify nada.
- [ ] **1.** Ler `spikes/library-scale/results/` (se `api_10k.json`/`api_50k.json` já existirem, copiar números para `specs/espacos/plano-implementacao.md` §10.1). **2.** `spikes/library-scale/run.sh bench_api.py --label 10k --runs 7` (Postgres do docker do spike; **banco de spike, nunca o de dev**), com 1, 5 e 20 pastas em `U` (variar concessões por script). **3.** Comparar com o orçamento de §10.2-8; gravar resultado e decisão ("liberar T-D6: sim/não"). **4.** `git add spikes/library-scale/results/api_10k_spaces.json specs/espacos/plano-implementacao.md && git commit -m "[ESP-D0] library scale baseline with Spaces"`.

#### T-D1 — Visibilidade de nós: `roots` e `children`  (2 d)  ← T-B4
**Files:** Create `backend/app/library/visibility.py` · Modify `backend/app/library/service.py:173-184,230-254` · Test `backend/tests/unit/test_library_space_visibility.py`
**Interfaces — Produces:** `visible_file_keys(session, access: SpaceAccess, organization_id) -> set[tuple[UUID, str]]` (`(source_id, external_file_id)`); `visible_node_ids(nodes, file_keys) -> set[UUID]` (arquivos visíveis + ancestrais); `LibraryService.roots(..., visible_only=True)` e `children(...)` passam a filtrar em SQL por `LibraryNode.id IN :visible` (v1).
- [ ] **1. Testes que falham:** Daniel vê raiz "Google Drive" com filhos `politicas` e `diretoria`, **não** `rh`; Bruno não vê `diretoria`; `children().total` reflete o filtrado (paginação com `page_size=1`); admin não-membro (`eva`) vê apenas `politicas` (D-2); arquivo presente em duas pastas de Espaços diferentes aparece **uma vez** com os dois Espaços ao qual a pessoa pertence; nó sem nenhum `Document` fica oculto a membros; organização `off` ⇒ árvore idêntica à atual (teste de caracterização escrito **antes**).
- [ ] **2.** FAIL (hoje todos veem tudo). **3.** Implementar `visible_file_keys` com uma instrução (`select(WorkspaceFolder.source_id, Document.external_file_id).join(...).where(Document.workspace_folder_id.in_(list(access.folder_ids)), Document.index_status.not_in(("removed","deleted")))`) e ancestrais pela cadeia `parent_id` (técnica de `library/service.py:1085-1098`); `_same_tool_roots` roda antes (sem mudança). **4.** PASS + `tests/unit/test_company_library.py tests/api/test_company_library_api.py -q`. **5.** commit `[ESP-D1] library tree visibility by accessible scopes`.

#### T-D2 — `search_page` (busca por nome)  (1 d)  ← T-D1
**Files:** Modify `backend/app/library/service.py:542-559` · Test `backend/tests/unit/test_library_space_search.py`
- [ ] **1.** Testes: Bruno busca "contrato" ⇒ só nós visíveis (nenhum do Diretoria), `total` correto; busca com `space_ids=[rh]` estreita; busca por nome de pasta restrita não revela existência (`total` não conta ocultos). **2.** FAIL. **3.** Reusar `visible_node_ids` como `WHERE LibraryNode.id IN` (v1). **4.** PASS. **5.** commit `[ESP-D2] library name search respects Spaces`.

#### T-D3 — Proveniência e listagens de documentos de um nó  (1 d)  ← T-D1
**Files:** Modify `backend/app/library/service.py:256-284,318-424` · `backend/app/api/library.py:30-75,215-320` · Test `backend/tests/unit/test_library_space_provenance.py`
- [ ] **1.** Testes: `workspace_provenance`/`document_provenance`/`documents_for_nodes` devolvem **só** pastas ∈ `U` (o arquivo em RH e Diretoria mostra uma só pasta a Bruno); `indexed_documents_under` idem; `workspace_folder_ids` do payload de `_node` não vaza UUID de pasta alheia. **2.** FAIL. **3.** Acrescentar parâmetro `access: SpaceAccess` e filtrar `Document.workspace_folder_id.in_`. **4.** PASS. **5.** commit `[ESP-D3] node provenance limited to accessible scopes`.

#### T-D4 — `mention_candidates` / `_selection_nodes` com pré-filtro  (1 d)  ← T-D1
**Files:** Modify `backend/app/library/service.py:985-991,1073-1122` · Test `backend/tests/unit/test_library_space_mentions.py`
- [ ] **1.** Testes: candidatos de Bruno não contêm nó do Diretoria nem pelo nome; `resolve_question_selection` com mention de nó do Diretoria por Bruno ⇒ `ValueError("mention is unavailable")` (mesma mensagem de "não existe"); contagem de nós carregados em memória **≤** nós das fontes de `U`. **2.** FAIL. **3.** `_selection_nodes(scope, source_ids=...)` com `WHERE LibraryNode.source_id IN :fontes_de_U`. **4.** PASS + `tests/api/test_chat_composer_context_api.py -q`. **5.** commit `[ESP-D4] mentions and node map limited to accessible sources`.

#### T-D5 — Status de sync e histórico  (1 d)  ← T-D1
**Files:** Modify `backend/app/library/service.py:774-909,1185-1217` · `backend/app/library/manual_sync.py` · `backend/app/api/library.py:166-200,330-380` · Test `backend/tests/api/test_library_space_sync_status_api.py`
- [ ] **1.** Testes: membro comum só vê sync/histórico de pastas em `U` (nome do escopo de pasta restrita **não** aparece); admin vê todos (nome do escopo + status, **sem** nomes de arquivo; `progress` com contagens e `skipped_reason`, sem `name`). **2.** FAIL. **3.** Filtrar por `access.folder_ids` (membro) / metadados reduzidos (admin). **4.** PASS + `tests/unit/test_sync_manual_resync.py tests/api/test_library_sync_permissions.py -q` verdes. **5.** commit `[ESP-D5] sync status and history respect Spaces`.

#### T-D6 — (condicional a T-D0) projeção `library_node_folders`  (3 d)  ← T-D0
Só se T-D0 indicar estouro de orçamento. **Files:** Create `backend/alembic/versions/2026MMDD_00NN_library_node_folders.py`, `backend/app/library/node_folders.py` · Modify `backend/app/library/service.py:1219-1341` (`project_successful_sync` mantém a projeção), `backend/app/library/visibility.py` (troca a implementação atrás da mesma interface) · Test `backend/tests/unit/test_library_node_folders.py`
- [ ] **1.** Testes: após `project_successful_sync` com 2 pastas, a projeção contém `(arquivo, pasta)` e `(ancestrais, pasta)`; remover arquivo/pasta limpa linhas; **invariante** "todo `Document` indexado tem linhas na projeção" (função `verify_node_folders(session)` usada também num job de reparo); resultado de `children/search` idêntico ao v1 em `seed_world` + conjunto aleatório (propriedade). **2.** FAIL. **3.** Implementar + `python -m app.library.node_folders rebuild --source <id>` idempotente. **4.** PASS. **5.** commit `[ESP-D6] node-to-folder projection for large libraries`.

### Bloco E — Selo de Espaço, filtro e busca unificada

#### T-E1 — Selos e `space_ids` nos endpoints da biblioteca  (1 d)  ← T-D1, T-D2
**Files:** Modify `backend/app/api/library.py:30-135` (`_node(..., spaces)`, parâmetro `space_ids` em `/library`, `/library/nodes/{id}/children`, `/library/search`, `/library/mention-candidates`) · Test `backend/tests/api/test_library_space_badges_api.py`
- [ ] **1.** Testes: cada item traz `spaces:[{id,name}]` (só os do chamador); `?space_ids=<rh>` estreita; `?space_ids=<alheio>` ⇒ 404; número de instruções SQL de `children` com 100 itens é **independente** de N (`assert statements <= K` — selo vem do `SpaceAccess` em memória). **2.** FAIL. **3.** `_node` recebe `access` e usa `spaces_of`. **4.** PASS. **5.** commit `[ESP-E1] Space badges and filter on library endpoints`.

#### T-E2 — Selo nas citações (resposta, histórico, API pública, MCP)  (1,5 d)  ← T-C3
**Files:** Modify `backend/app/knowledge/presentation.py:38-66` (`serialize_question_result(..., spaces_by_document: Mapping[UUID, tuple[SpaceRef, ...]] | None = None)` acrescenta `citation["spaces"]`) · `backend/app/api/ingestion.py:376-405` (monta o mapa `document_id → spaces` com **uma** consulta `Document.id, Document.workspace_folder_id` + `SpaceAccess.spaces_of`) · `backend/app/api/ingestion.py:409-434` (histórico recalcula `spaces` na leitura; nunca confia no gravado) · Test `backend/tests/api/test_citation_spaces_api.py`
- [ ] **1.** Testes: resposta de Carla cita `reajuste` com `spaces:[Diretoria]` e `politica` com `[Geral]`; uma citação de arquivo em RH+Geral mostra **os dois** para Carla e **só Geral** para Daniel (que, aliás, nem vê o RH); relido o histórico depois de Carla sair do RH, o selo RH **some** (e a mensagem é ocultada se for a única fonte — T-H1). **2.** FAIL. **3.** Implementar; `include_provider=False` (rota por pasta) também recebe `spaces`. **4.** PASS + `tests/unit/test_answer_blocks.py tests/api/test_conversations_api.py -q`. **5.** commit `[ESP-E2] citations carry the caller's Spaces`.

#### T-E3 — Recuperação: deduplicar arquivo em duas pastas e acumular selos  (1 d)  ← T-B4
**Files:** Modify `backend/app/knowledge/retrieval.py:62-100` (`SearchHit.spaces`, dedupe por `(source_id, external_file_id)`) · `backend/app/knowledge/questions.py` (ponto onde evidências são agrupadas por documento — localizar por `_document_citations` em `knowledge/agent.py:1443`) · Test `backend/tests/unit/test_retrieval_space_dedupe.py`
- [ ] **1.** Testes: arquivo "A" indexado em duas pastas (RH e Geral) ⇒ **um** `SearchHit` com `spaces=[Geral, RH]` para Carla; para Bruno idem; para Daniel (só Geral) ⇒ um hit com `[Geral]`; nenhum hit repete título/trecho idêntico. **2.** FAIL. **3.** Implementar. **4.** PASS + `tests/unit/test_mcp_tools.py tests/api/test_text_search_api.py -q`. **5.** commit `[ESP-E3] retrieval merges a file indexed in several scopes`.

#### T-E4 — Busca unificada de conteúdo `POST /organizations/{id}/search`  (1,5 d)  ← T-E3, T-C3
**Files:** Modify `backend/app/api/ingestion.py` (novo endpoint ao lado de `/workspace-folders/{id}/search:249`) · Test `backend/tests/api/test_org_search_api.py`
- [ ] **1.** Testes: Carla busca "reajuste" ⇒ hits de Geral e Diretoria com `spaces`; Daniel ⇒ não vê RH; `space_ids=[rh]` estreita; resposta limitada a `limit<=20` (`MAX_SEARCH_LIMIT`, `retrieval.py:21`); `snippet` passa por `strip_invisible`; texto de documento marcado como não confiável (`content_trust`) como no MCP. **2.** FAIL (404). **3.** Usa `RetrievalService.search(selection=…)` com `QuestionSelection` vindo de `resolve_question_selection(providers=todos, mentions=[], space_ids=…)`. **4.** PASS. **5.** commit `[ESP-E4] organization-wide content search over the caller's Spaces`.

### Bloco F — Frontend

> Testes de lógica pura em `frontend/tests/*.test.mjs` (importam `.ts` direto, como `library-view-logic.test.mjs`); telas validadas por `npm run lint` e roteiro manual de QA (§12.1). Nenhum arquivo `* 2.*` é tocado.

#### T-F1 — Renomear o "espaço" legado → "Pasta conectada"  (0,5 d)  — **primeira tarefa de frontend**
**Files:** Modify `frontend/app/product/integrations-screen.tsx`, `frontend/app/new-space-options.ts`, `frontend/app/product/library-screen.tsx` (`spacesPanelOpen`, textos), `frontend/app/organization-onboarding.tsx` · Test `frontend/tests/new-space-options.test.mjs` (existente, ajustar) + `frontend/tests/space-vocabulary.test.mjs`
- [ ] **1.** `space-vocabulary.test.mjs`: lê os `.tsx/.ts` listados e afirma que **nenhum texto visível ao usuário** usa "espaço(s)" para designar escopo de sincronização (regex sobre strings de UI: `Espaço: “`, `espaços já indexados`, …) e que "Pasta conectada" aparece; identificadores de código (`newSpaceOptions`, `ExistingSpace`) **podem** permanecer (renomear símbolos só se trivial). **2.** `node --test frontend/tests/space-vocabulary.test.mjs` → **FAIL**. **3.** Trocar os textos. **4.** PASS + `node --test frontend/tests/new-space-options.test.mjs`. **5.** commit `[ESP-F1] rename legacy "espaço" to "Pasta conectada" in the UI`.

#### T-F2 — Lógica de Espaços (pura) `spaces-model.ts`  (1 d)  ← T-C1 (contrato)
**Files:** Create `frontend/app/spaces-model.ts` · Test `frontend/tests/spaces-model.test.mjs`
**Interfaces — Produces:** `type SpaceRef = {id: string; name: string}`; `parseSpaceFilter(search: string, allowed: SpaceRef[]): string[]` (lê `?spaces=a,b`, descarta ids que o usuário não tem); `serializeSpaceFilter(ids: string[]): string`; `spaceBadges(spaces: SpaceRef[], max = 2): {visible: string[]; hiddenCount: number}`; `scopeSummary(selected: string[], all: SpaceRef[]): string` ("Todos os meus Espaços (3)" / "RH, Geral" / "RH +2"); `canManageMembers(role: "owner"|"admin"|"member", myRole: "member"|"manager"|null): boolean`; `impactSentence(name: string, impact: {documents_lost: number; conversations_hidden: number; automations_paused: number}): string`.
- [ ] **1. Teste que falha** — `frontend/tests/spaces-model.test.mjs`:
```js
import assert from "node:assert/strict";
import test from "node:test";
import { canManageMembers, impactSentence, parseSpaceFilter, scopeSummary, serializeSpaceFilter, spaceBadges } from "../app/spaces-model.ts";

const all = [{ id: "g", name: "Geral" }, { id: "r", name: "RH" }, { id: "d", name: "Diretoria" }];

test("filter parsing drops ids the user does not belong to", () => {
  assert.deepEqual(parseSpaceFilter("?spaces=r,zzz,d", all), ["r", "d"]);
  assert.deepEqual(parseSpaceFilter("", all), []);
  assert.equal(serializeSpaceFilter(["r", "d"]), "r,d");
});

test("badges collapse after the limit", () => {
  assert.deepEqual(spaceBadges(all, 2), { visible: ["Geral", "RH"], hiddenCount: 1 });
  assert.deepEqual(spaceBadges([], 2), { visible: [], hiddenCount: 0 });
});

test("scope summary never asks the user to pick a Space", () => {
  assert.equal(scopeSummary([], all), "Todos os meus Espaços (3)");
  assert.equal(scopeSummary(["r"], all), "RH");
  assert.equal(scopeSummary(["r", "d", "g"], all), "Todos os meus Espaços (3)");
});

test("who can manage members", () => {
  assert.equal(canManageMembers("admin", null), true);
  assert.equal(canManageMembers("member", "manager"), true);
  assert.equal(canManageMembers("member", "member"), false);
  assert.equal(canManageMembers("member", null), false);
});

test("impact sentence is plain Portuguese", () => {
  assert.equal(
    impactSentence("Bruno", { documents_lost: 214, conversations_hidden: 3, automations_paused: 1 }),
    "Bruno deixará de ver 214 documentos. 3 conversas terão trechos ocultados. 1 automação será pausada.");
  assert.equal(
    impactSentence("Ana", { documents_lost: 1, conversations_hidden: 0, automations_paused: 0 }),
    "Ana deixará de ver 1 documento.");
});
```
- [ ] **2.** `cd frontend && node --test tests/spaces-model.test.mjs` → **FAIL** (`Cannot find module …/spaces-model.ts`).
- [ ] **3. Implementação** `frontend/app/spaces-model.ts`:
```ts
export type SpaceRef = { id: string; name: string };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function parseSpaceFilter(search: string, allowed: SpaceRef[]): string[] {
  const raw = new URLSearchParams(search.startsWith("?") ? search : `?${search}`).get("spaces") ?? "";
  const known = new Set(allowed.map((space) => space.id));
  return [...new Set(raw.split(",").filter((id) => known.has(id)))];
}
export const serializeSpaceFilter = (ids: string[]) => ids.join(",");

export function spaceBadges(spaces: SpaceRef[], max = 2) {
  return { visible: spaces.slice(0, max).map((space) => space.name), hiddenCount: Math.max(0, spaces.length - max) };
}
export function scopeSummary(selected: string[], all: SpaceRef[]): string {
  if (selected.length === 0 || selected.length >= all.length) return `Todos os meus Espaços (${all.length})`;
  const names = selected.map((id) => all.find((space) => space.id === id)?.name).filter(Boolean) as string[];
  return names.length <= 2 ? names.join(", ") : `${names[0]} +${names.length - 1}`;
}
export function canManageMembers(orgRole: "owner" | "admin" | "member", myRole: "member" | "manager" | null) {
  return orgRole !== "member" || myRole === "manager";
}
export function impactSentence(name: string, impact: { documents_lost: number; conversations_hidden: number; automations_paused: number }) {
  const parts = [`${name} deixará de ver ${plural(impact.documents_lost, "documento", "documentos")}.`];
  if (impact.conversations_hidden) parts.push(`${plural(impact.conversations_hidden, "conversa terá", "conversas terão")} trechos ocultados.`);
  if (impact.automations_paused) parts.push(`${plural(impact.automations_paused, "automação será", "automações serão")} pausada${impact.automations_paused === 1 ? "" : "s"}.`);
  return parts.join(" ");
}
```
- [ ] **4.** mesmo comando → **PASS**. **5.** `git add frontend/app/spaces-model.ts frontend/tests/spaces-model.test.mjs && git commit -m "[ESP-F2] pure Space filter, badge and impact logic"`

#### T-F3 — Tela **Espaços** (lista, pessoas, pastas, diálogo de impacto)  (3 d)  ← T-F2, T-C1
**Files:** Create `frontend/app/product/spaces-screen.tsx`, `frontend/app/product/spaces-api.ts` (chamadas tipadas: `listSpaces`, `members`, `addMember`, `removeMember`, `impact`, `grant`, `revoke`, `enter`) · Modify `frontend/app/product-app.tsx` e `frontend/app/product/shell.tsx` (item de navegação "Espaços", visível a todos; conteúdo muda por papel) · Test `frontend/tests/spaces-api.test.mjs` (caminhos/corpos dos requests com `fetch` simulado: `DELETE /organizations/{id}/spaces/{sid}/members/{uid}` etc.) + roteiro §12.1
- [ ] **1.** `spaces-api.test.mjs` (fetch fake registra `method/url/body`): cada função monta a URL/corpo exatos; erro 404 vira `SpacesError("not_found")`; 403 vira `SpacesError("forbidden")`. **2.** FAIL (módulo inexistente). **3.** Implementar `spaces-api.ts` e a tela (diálogo `<dialog>` + `closeDialogAnimated`, padrão de `library-screen.tsx`; botão "Desabilitar" abre impacto → confirmar; botão "Entrar neste Espaço" só para admin não-membro). **4.** `node --test tests/spaces-api.test.mjs` PASS; `npm run lint` sem erros novos. **5.** commit `[ESP-F3] Spaces screen with members, folders and impact dialog`.

#### T-F4 — Biblioteca: chips, selos, "Agrupar por Espaço"  (2 d)  ← T-F2, T-E1
**Files:** Modify `frontend/app/product/library-screen.tsx`, `library-grid.tsx`, `use-library-items.ts`, `frontend/app/library-view-logic.ts` (estado `groupBySpace`), `frontend/app/product/types-and-api.tsx` (`LibraryNode.spaces`) · Test `frontend/tests/library-view-logic.test.mjs` (estender) + `frontend/tests/library-space-filter.test.mjs`
- [ ] **1.** Testes: `serializeLibraryView/parseLibraryView` preservam `groupBySpace` e rejeitam valor inválido; `buildLibraryQuery({spaces:["r"]})` acrescenta `&space_ids=r` e **omite** o parâmetro quando vazio (visão unificada = ausência de filtro). **2.** FAIL. **3.** Implementar. **4.** PASS + lint. **5.** commit `[ESP-F4] library Space chips, badges and grouping`.

#### T-F5 — Chat: faixa "Procurando em…", seletor de Espaço, selos nas citações  (2 d)  ← T-F2, T-C3, T-E2
**Files:** Modify `frontend/app/question-scope.tsx` (`QuestionContext.spaces`, segunda dimensão), `frontend/app/product/chat-workspace.tsx:256-270` (enviar `space_ids` só se filtrado), `frontend/app/source-reading.tsx`, `frontend/app/answer-actions.tsx` · Test `frontend/tests/question-scope-spaces.test.mjs`
- [ ] **1.** Testes: `contextsInSpaces(contexts, [])` devolve todos (união); com `["r"]` só os que têm o Espaço; `scopeSummary` alimenta a faixa; `payloadSpaceIds([])` ⇒ `undefined` (não envia). **2.** FAIL. **3.** Implementar. **4.** PASS + lint. **5.** commit `[ESP-F5] chat searches all my Spaces by default, with an optional filter`.

#### T-F6 — "Quem poderá ver esta pasta?" ao ligar pasta + texto de ciência  (1,5 d)  ← T-F2, T-A4, T-C1
**Files:** Modify `frontend/app/product/drive-share-flow.tsx`, `drive-share-api.ts`, `drive-share-logic.ts`, `frontend/app/product/integrations-screen.tsx` · Test `frontend/tests/drive-share-logic.test.mjs` (estender) 
- [ ] **1.** Testes: `canLink({spaceIds: []})` ⇒ `false` (não liga sem Espaço); `defaultSpaceSelection(spaces)` pré-marca o `is_default`; corpo de `link`/`link-batch` inclui `space_ids`; dica `NestedInLinked` ganha o texto "para separar por Espaço, compartilhe cada subpasta". **2.** FAIL. **3.** Implementar. **4.** PASS. **5.** commit `[ESP-F6] choose Spaces when linking a Drive folder`.
**Backend correspondente** (`drive_sa.py` `LinkInput.space_ids`, `DriveSaConnectionService._connect/link_batch`, `api/integrations.py:835` `select_scope`) é a tarefa **T-F6b** (1 d, antes de F6): `backend/tests/api/test_google_drive_sa_api.py` ganha "ligar com `space_ids` cria concessões na mesma transação; falha de concessão desfaz a ligação; sem `space_ids` em organização `enforce` ⇒ 422 `space_required`".

#### T-F7 — Equipe: convite com Espaços e coluna "Espaços"  (1 d)  ← T-C1, T-A4
**Files:** Modify `frontend/app/product/team-staff.tsx`, `backend/app/organizations/service.py:130-178` (`create_invitation(..., space_ids)`), `backend/app/api/onboarding.py` ou rota de convites existente · Test `backend/tests/unit/test_invitation_service.py` (estender) + `frontend/tests/team-spaces.test.mjs`
- [ ] **1.** Testes: convite guarda `space_ids` validados na organização; `accept_invitation` insere nos Espaços do convite (já em T-A4). **2–5.** padrão. Commit `[ESP-F7] invitations choose Spaces`.

#### T-F8 — Chaves de API: prévia de alcance e aviso "admin sem Espaços"  (1 d)  ← T-I1
**Files:** Modify `frontend/app/access-settings.tsx`, `frontend/app/product/developer-screen.tsx` · Test `frontend/tests/access-reach.test.mjs`
- [ ] **1.** Testes: `reachSentence({spaces:["RH","Geral"], documents:214})` ⇒ "Esta chave alcançará 214 documentos em: RH, Geral."; sem Espaços ⇒ "Esta chave não lerá nenhum documento: quem a criou não participa de nenhum Espaço." **2–5.** padrão. Commit `[ESP-F8] API key reach preview`.

### Bloco H — Derivados: ocultação na leitura, pausa de automações, purga

#### T-H1 — Histórico de conversa oculta respostas fora de `U`  (1,5 d)  ← T-B4
**Files:** Create `backend/app/spaces/visibility_of_messages.py` · Modify `backend/app/knowledge/agent.py:176-` (`ConversationService.history` recebe `access`), `backend/app/api/ingestion.py:409-434` · Test `backend/tests/api/test_conversation_hiding_api.py`
**Interfaces — Produces:** `message_visibility(session, access, messages) -> dict[UUID, bool]` (uma consulta para todos os `document_id` citados: `select(Document.id, Document.workspace_folder_id).where(Document.id.in_(ids))`); `HIDDEN_NOTICE = "Conteúdo ocultado por mudança de acesso."`.
- [ ] **1. Teste que falha** — `test_conversation_hiding_api.py` (`seed_world`; Bruno pergunta "contrato" em Geral+RH e a resposta cita o doc do RH; salvar a conversa com `ConversationService.append`):
```python
def test_history_hides_answers_citing_a_scope_the_user_lost(client, world, as_user):
    conversation_id = ask_as(client, world, "bruno", "qual o contrato?")   # cita documents["rh"]
    before = as_user("bruno").get(f"/organizations/{world.organization_id}/conversations/{conversation_id}").json()
    assert before["messages"][1]["content"] != HIDDEN_NOTICE
    remove_from_space(world, "bruno", "rh")                                # SpaceService.remove_member
    after = as_user("bruno").get(f"/organizations/{world.organization_id}/conversations/{conversation_id}").json()
    assert after["messages"][0]["content"] == "qual o contrato?"          # the user's own question stays
    assert after["messages"][1]["content"] == HIDDEN_NOTICE
    assert after["messages"][1]["response"] == {"hidden": True, "reason": "access_changed"}
    assert "contrato" not in str(after["messages"][1]).lower().replace("qual o contrato?", "")
```
  (+ `test_history_keeps_answers_whose_sources_are_all_still_accessible`, `test_answer_export_of_hidden_message_is_404`, `test_message_without_citations_is_never_hidden`, `test_history_costs_one_extra_query_not_one_per_message`.)
- [ ] **2.** FAIL (histórico devolve tudo). **3.** Implementar: para cada mensagem `assistant`, `documents,_ = _answer_provenance(message)` (`knowledge/agent.py:1455`, tornar público) e **também** `context.references` (nós ⇒ pasta via `Document`); oculta se **algum** `document_id` citado tiver `workspace_folder_id ∉ access.folder_ids` **ou** não existir mais. **4.** PASS + `tests/api/test_conversations_api.py tests/api/test_answer_export_api.py -q`. **5.** commit `[ESP-H1] hide stored answers after access changes`.

#### T-H2 — Automações: `provenance`, pausa por perda de acesso, ocultação do resultado/PDF  (1,5 d)  ← T-B4
**Files:** Modify `backend/app/automations/executor.py:188-196` (gravar `result.provenance = {"document_ids": [...], "workspace_folder_ids": [...]}`) · `backend/app/api/automations.py` (histórico/PDF ocultam) · Create `backend/app/spaces/derived.py` (`pause_automations_for_lost_access(session, organization_id, user_id, lost_folder_ids)`) · Test `backend/tests/unit/test_automation_space_access.py`
- [ ] **1.** Testes: execução grava `provenance`; criador que perdeu a pasta ⇒ `error_code="creator_access_lost"` (já existe) e, após `pause_automations_for_lost_access`, `Automation.enabled is False` + 1 `Notification` ao dono; destinatário sem acesso a uma pasta do escopo ⇒ em `skipped_recipients` (comportamento atual preservado); resultado de execução antiga cujo `provenance` sai de `U` ⇒ API devolve `{"hidden": true}` no lugar de `answer`/`citations`. **2.** FAIL. **3.** Implementar. **4.** PASS + `tests/api/test_automations_api.py tests/unit/test_automation_report_pdf.py -q`. **5.** commit `[ESP-H2] automation results carry provenance and hide on access loss`.

#### T-H3 — Perguntas seguidas e consultas salvas  (1 d)  ← T-B4
**Files:** Modify `backend/app/notifications/followed.py:55-90`, `backend/app/audit_usage/service.py:23-47` · Test `backend/tests/unit/test_followed_space_access.py`
- [ ] **1.** Testes: `refresh_followed_queries` **pula** consulta cujo dono perdeu a pasta (sem chamar o modelo; `counts["rerun"]` não incrementa); `purge` de `last_answer`/`last_checked_at` ao perder acesso; leitura de `SavedQuery` com pasta fora de `U` ⇒ `GoogleAccessDenied`. **2.** FAIL. **3.** Implementar. **4.** PASS + `tests/unit/test_notification_tasks.py` verde (cobre `refresh_followed_queries`; confirmar com `grep -rl refresh_followed_queries backend/tests`). **5.** commit `[ESP-H3] followed queries respect Spaces and clear stale answers`.

#### T-H4 — Notificações com `provenance` e leitura filtrada  (1 d)  ← T-H2
**Files:** Modify `backend/app/notifications/service.py` (`notify(..., provenance=None)`), `backend/app/notifications/followed.py:84-90`, `backend/app/api/notifications.py:34-` · Test `backend/tests/api/test_notifications_space_api.py`
- [ ] **1.** Testes: notificação de automação/seguida guarda `data.provenance`; após perder a pasta, `GET /notifications` devolve o item com `body="Conteúdo ocultado por mudança de acesso."` e sem `data.citations`; item **antigo** sem `provenance` mas com `citations[].document_id` usa os ids; item antigo sem nada ⇒ oculto **se** `kind` ∈ {`followed_query_changed`,`automation_result`} e o usuário perdeu algum acesso (decisão conservadora de §11.3). **2.** FAIL. **3.** Implementar. **4.** PASS + `tests/api/test_notifications_api.py -q`. **5.** commit `[ESP-H4] notifications hide content after access changes`.

#### T-H5 — Exportação e ClickUp reconferem a proveniência  (0,5 d)  ← T-H1
**Files:** Modify `backend/app/api/answer_export.py:40-`, `backend/app/api/clickup_tasks.py:67-` · Test `backend/tests/api/test_answer_export_api.py` e `backend/tests/api/test_clickup_tasks_api.py` (estender)
- [ ] **1.** Testes: mensagem oculta ⇒ 404 em `…/export` e `…/clickup-task/preview|POST`; mensagem visível ⇒ comportamento atual. **2.** FAIL. **3.** Reusar `message_visibility`. **4.** PASS. **5.** commit `[ESP-H5] export and ClickUp re-check message provenance`.

#### T-H6 — Impacto real + job de purga ≤ 24 h  (1,5 d)  ← T-H1…T-H4
**Files:** Modify `backend/app/spaces/derived.py` (`impact(...)`, `purge_derived_for_user(...)`, `purge_derived_for_folder(...)`), `backend/app/api/spaces.py` (impacto completo), `backend/app/ingestion/tasks.py:62-` (entrada no `beat_schedule`: `purge-hidden-derived`, diária) · Test `backend/tests/unit/test_space_purge.py`
- [ ] **1.** Testes: `impact` conta **só** o que some considerando os outros Espaços; `purge_*` zera `last_answer`, apaga `Notification.body/data` ocultos **após 24 h** de `removed_at`/`revoked_at` (não antes) e **não** apaga mensagens de conversa (mantém a pergunta; o conteúdo da resposta é substituído por tombstone `{"hidden":true}`); idempotente. **2.** FAIL. **3.** Implementar + agendar. **4.** PASS + `tests/unit/test_ingestion_scheduler.py -q` verde (o `beat_schedule` tem teste). **5.** commit `[ESP-H6] derived-content impact and 24h purge job`.

### Bloco I — Credenciais, API pública, MCP

#### T-I1 — Chave de API e MCP: `U(usuário) ∩ node_ids`; admin ≠ leitor  (1 d)  ← T-B4
**Files:** Test `backend/tests/api/test_public_v1_spaces.py`, `backend/tests/api/test_mcp_server_spaces.py` · Modify (se algum caminho vazar) `backend/app/access/scope.py`, `backend/app/api/public_v1.py:170-200`, `backend/app/mcp_server/tools.py:60-90`
- [ ] **1. Testes (devem falhar primeiro onde houver vazamento; esperam-se majoritariamente verdes por herança — o ponto é **provar**):** `eva` (admin que não está no Diretoria) com chave **sem** `node_ids`: `POST /v1/search` por termo só do Diretoria ⇒ `results == []`; `GET /v1/sources` não lista a pasta; `POST /v1/ask` não cita; chave com `node_ids=[nó do Diretoria]` ⇒ **403/404 uniforme** (`authorize_mentions`); MCP `fetch` do `document_id` do Diretoria por usuário sem o Espaço ⇒ `ToolNotFound`; depois de `eva` **entrar** no Diretoria, os mesmos pedidos passam; remover Ana do RH reduz o alcance da chave de Ana **no próximo request** (sem novo token). **2.** rodar; **FAIL** onde houver caminho sem resolvedor. **3.** Corrigir o que falhar (esperado: nada além de T-B4). **4.** PASS + `tests/api/test_public_v1.py tests/api/test_public_v1_review.py tests/api/test_mcp_server.py tests/unit/test_principal.py -q`. **5.** commit `[ESP-I1] prove credentials are bounded by the linked user's Spaces`.

#### T-I2 — `spaces` e `space_ids` na API pública e no MCP  (1,5 d)  ← T-I1, T-C3
**Files:** Modify `backend/app/api/public_v1.py` (`whoami`, `/sources`, `/search`, `/ask`, modelos de payload), `backend/app/mcp_server/tools.py` (`run_search/run_list_sources`) e `backend/app/access/scope.py` (aceitar `space_ids` no `selection`), `backend/app/api/access_admin.py:73-100` (`reach`) · Test `backend/tests/api/test_public_v1_spaces.py` (estender)
- [ ] **1.** Testes: `whoami.spaces` lista os Espaços do usuário vinculado; `/sources[].spaces`; `/search` com `space_ids` alheio ⇒ 404; `POST /api-keys` devolve `reach.spaces/documents` para o criador; `ApiAuditEvent` **não** grava nomes de Espaço. **2–5.** padrão. Commit `[ESP-I2] Spaces in public API, MCP and key reach preview`.

#### T-I3 — Documentação pública e threat model  (0,5 d)  ← T-I2
**Files:** Modify `docs/seguranca/threat-model-api-mcp-canais.md`, `docs/api/referencia-v1.md`, `docs/api/openapi-v1.json`, `docs/api/CHANGELOG.md`, `frontend/app/docs/**` · Test `frontend/tests/api-docs-logic.test.mjs` (estender, já existe)
- [ ] **1.** Teste: a referência pública cita `space_ids`, `spaces` e a regra de interseção; o threat model contém T-ESP-1…3. **2–5.** padrão. Commit `[ESP-I3] document Space-bounded credentials`.

### Bloco G — Testes transversais (rodam no fim de cada fase; escreve-se o esqueleto cedo)

- **T-G1 (1 d) ← T-B3, T-C1:** `backend/tests/api/test_spaces_end_to_end.py` — fluxo completo: admin cria "RH", liga pasta com `space_ids`, adiciona Bruno, Bruno vê a pasta na biblioteca/chat/busca/evidência/`/v1`; admin remove Bruno ⇒ **todas** as superfícies vivas somem no próximo request, histórico oculta, `last_answer` limpo, automação do Bruno pausada, chave/MCP reduzidos (critério 3 da §13.2).
- **T-G2 (0,5 d) ← T-B4:** estender `backend/tests/unit/test_agent_revocation_moved_file.py`, `…_review.py`, `…_sibling_folder.py` com "removido do Espaço no meio da conversa" (o agente reavalia o escopo a cada ferramenta: `LibraryToolExecutor` → `authorized_catalog`).
- **T-G3 (1 d) ← T-A2, T-B4, T-D1, T-E1:** `backend/tests/integration/test_spaces_equivalence.py` — grava, em modo `off`, as respostas de `question_contexts`, `roots/children/search`, `mention_candidates`, `/v1/sources` e uma pergunta com `FakeProvider`; roda `backfill_default_spaces` + modo `enforce`; **exige igualdade** (critério de aceite 1). Marca `@pytest.mark.postgres` além da versão SQLite.

### Bloco J — Rollout, guarda de regressão, ADR

#### T-J1 — CLI de rollout `python -m app.spaces.rollout`  (1 d)  ← T-A2, T-B2
**Files:** Create `backend/app/spaces/rollout.py` · Test `backend/tests/unit/test_space_rollout.py`
- [ ] **1.** Testes: `enforce --organization <id>` falha se houver `space_folder_grants` ausente para alguma pasta **ou** membro ativo sem nenhum `space_members` (recusa: "organização tem pasta/pessoa sem Espaço") a menos que `--force`; `shadow`/`off` sempre permitidos (rollback); `report` agrega divergências e imprime só contagens; `--all-clean` só promove organizações sem divergência no período. **2–5.** padrão. Commit `[ESP-J1] rollout CLI with safety checks`.

#### T-J2 — Guarda contra novos pontos de acesso sem resolvedor  (0,5 d)  ← T-B4, T-D1
**Files:** Create `backend/tests/unit/test_spaces_call_sites.py`, `specs/espacos/call-sites.md`
- [ ] **1.** Teste: varre `backend/app/**/*.py` (`ast`) e falha se `question_contexts(`, `require_member_access(`, `WorkspaceFolder` em `select(...)` (fora de `app/spaces`, `app/workspaces`, `app/library/service.py`, `app/ingestion`, `app/integrations`) aparecer em arquivo **não listado** em `specs/espacos/call-sites.md`. **2.** FAIL (arquivo da lista inexistente). **3.** Gerar a lista da tabela §4.3. **4.** PASS. **5.** commit `[ESP-J2] guard: no new content-access call site without review`.

#### T-J3 — ADR-0021 final + `graphify update .`  (0,5 d)  ← todas
Mover o rascunho do Anexo A para `specs/adr/ADR-0021-espacos-acesso-por-pessoa.md` (já criado como rascunho nesta sessão), atualizar status para "Aprovado e implementado", anexar `api_10k_spaces.json`, rodar `graphify update .`. Commit `[ESP-J3] ADR-0021 accepted`.

### 12.1 Roteiro manual de QA (após Bloco F; o que testes automatizados não cobrem)

1. Organização migrada: abrir biblioteca, chat e busca — idêntico ao dia anterior (uma árvore, nenhum chip além de "Geral" se só existir Geral). 2. Criar "RH"; mover pasta; ver Bruno **perder** o RH na biblioteca (recarregando) e o chat não citar mais. 3. Pessoa em 3 Espaços: **uma** pergunta, citações com selos de Espaços diferentes; filtro "RH" restringe. 4. Admin sem Espaço: tela mostra "sem Espaço — ninguém vê" e botão "Entrar neste Espaço". 5. Celular (≤ 390 px): chips viram seletor único, diálogo de impacto utilizável. 6. Navegação por teclado e leitor de tela nos chips e no diálogo. 7. Chave de API de admin sem Espaços: aviso "não lerá nada".


---

## 13. Ordem, dependências, releases e estimativa

### 13.1 Grafo de dependências (resumo)

```
A1 ─► A2 ─┬─► A3 ─► A4 ─────────────────────────────────────────────┐
          └─► B1 ─► B2 ─► B4 ─┬─► C3 ─┬─► E2 ─► F5                   │
                              ├─► D1 ─┬─► D2 ─► E1 ─► F4              │
                              │       ├─► D3 / D4 / D5               │
                              │       └─► (D0 ─► D6 condicional)     │
                              ├─► E3 ─► E4                           │
                              ├─► H1 ─► H5                           │
                              ├─► H2 ─► H4 ─► H6   (H3 paralela)     │
                              ├─► I1 ─► I2 ─► I3 / F8                │
                              └─► B5 (← C2)                          ├─► J1 ─► (enforce por organização)
C1 (← A3,B2) ─► C2 ─► B5 ;  C1 ─► F2 ─► F3 ;  A4+C1 ─► F6b ─► F6 ─► F7 │
B3 (esqueleto cedo; fecha por último) · G1/G2/G3 no fim de cada release · J2 após B4+D1 ◄┘
F1 não depende de nada (pode abrir no dia 1)
```

**Arquivos que impõem ordem serial** (uma tarefa por vez em cada um): `backend/app/library/service.py` (B4 → D1 → D2 → D3 → D4 → D5 → D6) e `backend/app/knowledge/questions.py` + `knowledge/agent.py` (B4 → C3 → H1). Tudo o mais pode correr em paralelo depois de B2.

### 13.2 Releases (cada um entrega algo executável e reversível)

| Release | Conteúdo | Quem sente | Reversão |
|---|---|---|---|
| **R0 — Fundação invisível** | A1–A4, B1, B2, J1 (CLI), F1 (renomear) | Ninguém, exceto o texto "Pasta conectada". Esquema + backfill em `shadow` (resolvedor calcula e **só registra divergência**). | `alembic downgrade` ou nenhum efeito (modo `off`/`shadow` serve o legado). |
| **R1 — Núcleo seguro (backend)** | B3, B4, B5, C1–C3, D0–D5 (+D6 se preciso), E1–E4, H1–H6, I1–I2, G1–G3, J2 | Admin via API; usuários: nada muda enquanto `shadow`. Critérios de aceite medidos aqui. | `rollout shadow` por organização (segundos). |
| **R2 — UX e ligação** | F2–F8, I3, J3 | Telas de Espaços, chips/selos, chat com faixa e filtro, ligar pasta com Espaços. **Só depois do R2** (F3 + F6 no ar) promovemos organizações a `enforce` e criamos organizações novas já em `enforce` (`settings.spaces_new_org_mode`, padrão `shadow` até lá). | `rollout shadow`. |

**Critérios de aceite (todos automatizados; cada um aponta para a tarefa que o prova):**

1. **Equivalência:** organização migrada com "Geral" ⇒ respostas idênticas às de antes (contextos, árvore, busca, menções, `/v1/sources`, pergunta) — **T-G3**.
2. **Isolamento por superfície:** membro só do Geral não encontra documento de outro Espaço por chat, busca, menção, árvore, evidência, visualizador, exportação, `/v1`, MCP — todos ausência/404 uniforme — **T-B3 + T-G1**.
3. **Remoção:** remover Bruno do RH ⇒ no **próximo request** todas as superfícies vivas deixam de devolver RH; histórico mostra o aviso; `last_answer` limpo; automação pausada; chave/MCP encolhem — **T-G1, T-H1…H6, T-I1**.
4. **Admin ≠ leitor:** chave de API de admin que não é membro do Diretoria não alcança Diretoria mesmo sem `node_ids` — **T-I1**.
5. **Fora da organização continua fora** (`Membership.is_active`) — **T-B2**.
6. **Fail-closed:** falha do resolvedor ou resultado vazio ⇒ zero conteúdo — **T-B2**.
7. **Auditoria** de criar/alterar Espaço, conceder/revogar pasta, "admin entrou no Espaço" — **T-A3, T-C1**.
8. **Escala:** instruções SQL do resolvedor constantes (≤ 4) e orçamentos de §10.2-8 — **T-B2, T-D0, T-E1**.
9. **Sem duplicação:** conceder a mesma pasta a dois Espaços não cria `Document`/chunk — **T-A4**.
10. **Visão unificada (requisito do dono):** pessoa em 3 Espaços faz **uma** pergunta, **uma** busca e navega **uma** árvore sem escolher Espaço; recebe documentos dos 3; o filtro só estreita; `space_ids` alheio ⇒ 404 — **T-C3, T-D1, T-E4, T-F4/F5**.
11. **Selo só dos Espaços da pessoa** (nunca revela Espaço alheio) — **T-B2, T-E1, T-E2**.
12. **Arquivo em duas pastas** aparece **uma** vez com os selos combinados — **T-D1, T-E3**.
13. **Derivados ocultos na leitura** (histórico, exportação, ClickUp, seguidas, notificações, automações) — **T-H1…H5**.

### 13.3 Estimativa (dev-dias de quem conhece a base; **[ESTIMATIVA]**, confiança baixa-média)

| Bloco | Tarefas | Dev-dias |
|---|---|---|
| A — Modelo/migração/serviço/defaults | A1 0,5 · A2 1 · A3 1,5 · A4 1 | 4 |
| B — Resolvedor | B1 0,5 · B2 2 · B3 1 · B4 2 · B5 1 | 6,5 |
| C — API admin/contexto | C1 2 · C2 1 · C3 2 | 5 |
| D — Biblioteca | D0 0,5 · D1 2 · D2 1 · D3 1 · D4 1 · D5 1 (· D6 3 **condicional**) | 6,5 (+3) |
| E — Selo/filtro/busca | E1 1 · E2 1,5 · E3 1 · E4 1,5 | 5 |
| F — Frontend | F1 0,5 · F2 1 · F3 3 · F4 2 · F5 2 · F6b 1 · F6 1,5 · F7 1 · F8 1 | 13 |
| H — Derivados | H1 1,5 · H2 1,5 · H3 1 · H4 1 · H5 0,5 · H6 1,5 | 7 |
| I — Credenciais/API | I1 1 · I2 1,5 · I3 0,5 | 3 |
| G — Transversais | G1 1 · G2 0,5 · G3 1 | 2,5 |
| J — Rollout/guarda/ADR | J1 1 · J2 0,5 · J3 0,5 | 2 |
| **Total** | | **≈ 54,5 (faixa 44–68)** (+3 se D6) |

**Calendário ilustrativo [INFERÊNCIA]:** 1 dev ≈ 11–14 semanas; 2 devs ≈ 7–10 semanas (não cai pela metade: o núcleo B→D em `library/service.py` e `questions.py` é serial, e o frontend só avança de verdade depois do contrato de C1 — o F1 e o F2 podem começar antes). Caminho crítico: **A1 → A2 → B1 → B2 → B4 → C3 → D1 → D2 → E1 → F4**, ≈ 15 dev-dias; o resto (H, I, E3/E4, F3/F6) corre ao lado.

**Diferença para [VIAB] Fase 1 (18–32 dev-dias):** este plano é maior porque (a) inclui a **tela e o frontend completos** (13 d), (b) cobre **todos** os derivados (7 d) e a **API/MCP** (3 d) com testes, (c) trata a **árvore** (6,5 d) — que [VIAB] subestimou por tratar `question_contexts` como ponto único —, e (d) tem rollout reversível em `shadow`. Sem F, o backend "enforce-ready" fica em ≈ 40 dev-dias.

**Spike de escala e estimativa:** se `api_10k_spaces.json` (T-D0) não exigir a projeção, a faixa não muda; se exigir, +3 d (T-D6). Os números de 50k (semeador em andamento) só reabrem o desenho se `children/search` passarem de ~300 ms mesmo com a projeção.

---

## 14. Riscos e autorrevisão

### 14.1 Riscos principais

| # | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R-1 | Um caminho de leitura ficar fora do resolvedor (I3). | Média | **Alto** | T-B3 (matriz pessoa × superfície), T-J2 (guarda AST em `question_contexts(`/`require_member_access(`), `shadow` com zero divergência antes de `enforce`. |
| R-2 | N+1 de membership/selo reaparecer e matar a pergunta "união". | Média | Médio | Testes de contagem de instruções (T-B2, T-B4, T-E1); orçamento medido em T-D0. |
| R-3 | Conflito de merge em `library/service.py` (1 579 linhas) e `questions.py` (2 285). | Alta | Médio | Ordem serial §13.1; commits pequenos; uma pessoa por arquivo por vez. |
| R-4 | D-2 ("admin não lê") quebrar a operação (reprocessar, diagnosticar falha). | Média | Médio | Nomes de arquivo redigidos + "Entrar neste Espaço" auditado (T-B5, T-C2); alternativa: relaxar para "admin vê nomes" **se o dono preferir** (decisão aberta Q-2). |
| R-5 | `mention_candidates`/`_selection_nodes` (tudo em memória) degradar a 10k+ nós independentemente de Espaços. | Média | Médio | T-D4 pré-filtra; se o spike confirmar, tarefa própria de paginação em SQL (fora deste plano). |
| R-6 | Janela `shadow` nunca fecha limpa (divergência recorrente). | Baixa | Médio | Relatório por organização (T-J1); causa típica = pasta nova sem concessão ⇒ T-A4. |
| R-7 | Cliente quer Espaços **dentro** de uma única pasta compartilhada com o robô. | Média | Médio | Limitação dita na tela (§6); evolução = concessão por sub-árvore (filtro por caminho em chunks) — decisão posterior com dados reais. |
| R-8 | Resposta que mistura Espaços e depois a pessoa perde um deles ⇒ a resposta inteira some do histórico (granularidade conservadora). | Média | Baixo | Documentado (§8.2); alternativa (reescrever parcialmente) inventaria texto — rejeitada. |
| R-9 | E-mail/webhook/ClickUp já enviados são irrevogáveis. | Certa | Médio | Pausa de automações (T-H2), `provenance` gravada, ClickUp reconfere antes de criar; dito na UI. |
| R-10 | Testes em SQLite não exercitam índices parciais/planos do Postgres. | Média | Médio | Versões `@pytest.mark.postgres` em T-A2/T-G3 (`TEST_DATABASE_URL`); `tests/integration/test_performance_paths_postgres.py` como molde. |
| R-11 | Árvore de trabalho suja (arquivos alheios modificados, cópias `* 2.*`). | Alta | Baixo | `git add` só de caminhos da tarefa; nenhuma tarefa mexe em `* 2.*`. |
| R-12 | Vocabulário "Espaço" confundir clientes que já usam o termo legado. | Alta | Baixo-médio | T-F1 vem antes de qualquer tela nova; nota de versão. |

### 14.2 Perguntas ao dono (não bloqueiam as releases R0–R1)

| # | Pergunta | Padrão adotado |
|---|---|---|
| Q-1 | O responsável pelo Espaço pode adicionar pessoas só **da organização** (padrão) ou também convidar novas? | Só da organização; convidar é do Owner (hoje `team-staff.tsx`). |
| Q-2 | Admin da organização **não** lê conteúdo de Espaço de que não é membro (D-2) — aceita que ele só veja nomes de arquivo ao "Entrar" (auditado)? | Sim (R-4 descreve o custo). |
| Q-3 | Prazo de purga dos derivados: 24 h (padrão de [VIAB]). | 24 h. |
| Q-4 | Quando a organização promover o Espaço padrão a "sem membros automáticos", novos membros entram **sem acesso** — OK? | Sim (fail-closed). |

### 14.3 Autorrevisão (oc-route §8)

**1. Cobertura do pedido** — cada requisito aponta para seção/tarefas:

| Requisito do pedido | Onde |
|---|---|
| Modelo de dados e migrações | §3; T-A1, T-A2; §11 |
| Resolvedor único + todos os pontos que o usam | §4 (inventário §4.3); T-B2, T-B4, T-B5, T-D*, T-E3, T-J2 |
| Papéis (admin da org, responsável, membro) | §5; T-A3, T-C1 |
| UX da visão unificada + filtro + gestão de membros | §1, §7; T-F1…F8, T-C3, T-E1, T-E4 |
| Revogação e ocultação de derivados | §8; T-H1…H6, T-G1 |
| API pública/MCP/chaves | §9; T-I1…I3, T-F8 |
| Migração (Espaço inicial com todos) | §11; T-A2, T-A4, T-G3, T-J1 |
| Tarefas pequenas com paths exatos, testes primeiro, ordem, estimativa | §12–13 |
| Onde a escala afeta o desenho (spike) | §10; T-D0, T-D6 |
| Drive: pastas do robô → fontes atribuíveis | §6; T-F6b, T-F6, T-A4 |
| ADR-0021 | Anexo A + `specs/adr/ADR-0021-espacos-acesso-por-pessoa.md`; T-J3 |
| Ponto de partida [VIAB] (D-0…D-3, riscos de vazamento, chaves sem `node_ids`, colisão do nome) | §0, §2 (confirmações/correções), §8, §9, T-F1 |

**2. Varredura de placeholders (limitações honestas).** Não há "TBD/TODO". **Nível de detalhe desigual, por escolha de escopo:** T-A1, T-A2, T-B2 e T-F2 trazem **código completo** (teste + implementação); T-H1 e T-C1 trazem teste-chave completo ou matriz explícita; as demais trazem arquivo/linha exatos, **testes nomeados com as asserções** e o ponto de edição, mas **não** o código de cada teste — o executor (builder) expande a partir daí seguindo o padrão do arquivo de teste vizinho citado. Pontos marcados "(condicional)": T-D6 (depende do spike).

**3. Consistência de nomes.** Verificados: `SpaceAccessResolver.resolve/require_folder/require_folders`, `SpaceAccess.folder_ids/spaces_of/allows`, `SpaceRef`, `LibraryContext.spaces`, `QuestionInput.space_ids`, `Organization.spaces_resolver_mode ∈ {off, shadow, enforce}`, `HIDDEN_NOTICE`, `backfill_default_spaces`, tabelas `spaces/space_members/space_folder_grants`, revisões `20261019_0035`/`0036`. Corrigidos durante a escrita: modo do rollout moveu de `organization_access_settings` para `organizations` (linha sempre existe); `automation_runs.status` **não** ganha valor novo (pausa = `Automation.enabled=False`); `ACTIVE_DOCUMENT_LIMIT` é só exibição.

**4. O que este documento NÃO verificou.** Nenhum teste foi executado (plano apenas). `api_10k.json`/`api_50k.json` não existiam no momento da escrita: tudo que depende de 10k+ é **[INFERÊNCIA]**. Não li em profundidade `automations/triggers.py`, `report_pdf.py`, `notifications/digest.py` (mesma lacuna de [VIAB] §3.2/§14): entram como "revisar" em T-H2/T-H4/T-J2. Números de linha são da working tree de 2026-10-19 (`62062cc`) e envelhecem a cada merge em `library/service.py`.

---

## 15. Handoff de execução

Duas formas de executar (escolher uma):

**(a) Recomendada — um builder por tarefa, com revisão entre tarefas.** No Overclock: um `oc-pilot` abre um pane `oc-builder` (modelo Sonnet, conforme preferência registrada) **por tarefa**, na ordem de §13.1, e revisa o diff antes da seguinte. Cada tarefa já é um cartão independente (arquivos, testes, comando, commit). Paralelizar apenas lanes sem arquivo comum: **Lane 1** núcleo (A→B→C3→D→E), **Lane 2** derivados/credenciais (H, I, depois de B4), **Lane 3** frontend (F1 já; F2+ depois de C1).

**(b) Inline com checkpoints**, parando ao fim de **R0**, **R1** (critérios de aceite 1–13 verdes) e **R2** (roteiro §12.1).

**Primeiro passo sugerido:** T-A1 (0,5 d) + T-F1 (0,5 d) em paralelo — entregam código executável e reversível sem nenhum efeito para o usuário. Antes de promover a `enforce`, **confirmar Q-2** (D-2 com o dono).

> Este plano **não** iniciou execução, **não** alterou código de produção e **não** fez commit.


---

## Anexo A. ADR-0021

A versão canônica e final ("Aprovado e implementado") está em `specs/adr/ADR-0021-espacos-acesso-por-pessoa.md`; o rascunho que ficava aqui foi removido para não divergir.
