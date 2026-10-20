# Pontos de acesso a conteúdo revisados (T-J2, ADR-0021)

Cada arquivo abaixo chama `question_contexts(`, `require_member_access(` ou monta `select(...)` sobre `WorkspaceFolder`
fora dos pacotes donos do acesso (`app/spaces`, `app/workspaces`, `app/library/service.py`, `app/ingestion`,
`app/integrations`). `backend/tests/unit/test_spaces_call_sites.py` falha se aparecer um arquivo que não esteja aqui.
**Para acrescentar um arquivo:** confirme que ele obtém o conjunto de pastas por `SpaceAccessResolver` (direta ou
indiretamente via `LibraryService`/`WorkspaceService`) e registre a revisão na linha. Nunca passe `access=None`
(visão de sistema) em código voltado a membros: o teste também proíbe isso.

- `app/api/access_admin.py` — prévia de alcance da chave (`reach`) usa o resolvedor do criador — T-I2
- `app/api/automations.py` — destinatários e escopo; visibilidade por proveniência — T-H2
- `app/api/evidence.py` — `scoped_document`: citação em outro Espaço ⇒ 404 uniforme — T-B3/T-G1
- `app/api/insights.py` — agregados operacionais (sem texto de documento) — T-C2
- `app/api/library.py` — rotas da biblioteca recebem o `access` do chamador — T-D1..D5
- `app/api/public_v1.py` — `/v1` limita a chave aos Espaços do usuário vinculado — T-I1/T-I2
- `app/audit_usage/service.py` — consultas salvas e `last_answer` limpo na revogação — T-H3
- `app/automations/executor.py` — reavalia criador e cada destinatário a cada execução — T-H2
- `app/automations/triggers.py` — gatilhos por pasta; só enfileira, não lê conteúdo — T-H2
- `app/knowledge/agent.py` — ferramentas reavaliam `authorized_catalog` a cada chamada — T-G2
- `app/knowledge/derived_visibility.py` — oculta derivados pela proveniência — T-H1
- `app/knowledge/overview.py` — visão geral pela seleção autorizada — T-B4
- `app/knowledge/queryability.py` — pastas consultáveis dentro do acesso — T-B4
- `app/knowledge/questions.py` — `ask`/`ask_scope` por `require_folders` do resolvedor — T-B4
- `app/knowledge/retrieval.py` — recebe `selection.folder_ids` já filtrado; selos por Espaço — T-E3
- `app/knowledge/search.py` — busca por pasta única: 404 se fora do acesso — T-B4
- `app/knowledge/space_seals.py` — selos só dos Espaços da pessoa — T-E2
- `app/library/manual_sync.py` — histórico de sincronização limitado ao acesso — T-D5
- `app/mcp_server/tools.py` — MCP limita ao usuário vinculado e a `space_ids` estreitando — T-I2
- `app/notifications/digest.py` — resumo de notificações oculta o que a pessoa perdeu — T-H4
