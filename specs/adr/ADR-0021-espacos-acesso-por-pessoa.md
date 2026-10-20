# ADR-0021: Espaços — acesso a conteúdo por pessoa, com visão unificada

- **Status:** Aprovado e implementado (branch `feat/espacos`; rollout por organização com `python -m app.spaces.rollout`)
- **Data:** 2026-10-19
- **Decisor:** produto (usuário). Decisões do dono já dadas em 2026-10-19: (P-1) o Drive em produção segue **por enquanto** com o robô (conta de serviço com quem o cliente compartilha pastas) — CASA/OAuth `drive.readonly` fora deste plano; (P-2) integrações de comunicação (WhatsApp, Slack, Teams) ficam para depois; (P-3) quem tem acesso a vários Espaços **não pode ficar trocando de Espaço** para achar as coisas.
- **Relaciona-se com:** `specs/research/comunicacao-espacos-viabilidade-2026-10-15.md` (D-0…D-7; este ADR assume D-2, D-3, D-4, D-7 e deixa D-0/D-1/D-5/D-6 — chat — fora de escopo), `specs/plans/integracoes/03-api-mcp-e-canais.md` (D1: credencial ⊆ usuário), ADR-0006 (projeção da biblioteca), ADR-0007 (escopos de pergunta indexados), ADR-0013 (chave por provider), ADR-0015 (cerca anti-injeção), ADR-0020 (ação humana aprovada), `specs/espacos/plano-implementacao.md` (plano de execução).
- **Não substitui** nenhum ADR anterior. Estende ADR-0007: o conjunto de pastas consultáveis deixa de ser "toda a organização" e passa a ser "o que os Espaços da pessoa concedem".

## Contexto

Hoje o conteúdo é plano por organização: quem é membro ativo lê tudo (`LibraryService.require_member`, `library/service.py:162-171`; `WorkspaceService.require_member_access`, `workspaces/service.py:34-39`). O administrador "atesta acesso uniforme" ao selecionar uma pasta (`uniform_access_confirmed`, `workspaces/service.py:80-81`) e **não existe ACL por pessoa**. Empresas reais precisam de recortes (Geral, RH, Diretoria) sem abrir mão de uma experiência única: a pessoa que participa de vários recortes quer **uma biblioteca, uma busca e um chat** sobre a soma do que pode ver.

Fatos que moldam a decisão (todos verificados em código em 2026-10-19):
- A recuperação já é "uma consulta sobre um conjunto de `workspace_folder_id`" (`knowledge/retrieval.py:52-64`, `knowledge/questions.py:1138-1198`); o chat com "todas as ferramentas" já consulta a união.
- O ponto de estrangulamento de **perguntas** é `LibraryService.question_contexts` (`library/service.py:911-964`); a **árvore** e a **busca por nome** da biblioteca **não** passam por ele (`library/service.py:173-184, 230-254, 542-559`).
- O robô do Drive cria **um `WorkspaceFolder` por pasta compartilhada** e rejeita sub-pasta de pasta já ligada (`integrations/google_drive_sa_service.py:296-345, 217-243`).
- Chaves de API exigem criador Owner/Admin e, sem `node_ids`, alcançam a organização inteira (`access/principal.py:76-86`, `access/models.py:27`); MCP aceita qualquer membro.
- Conteúdo derivado é persistido e devolvido sem reavaliar: histórico de conversa (`api/ingestion.py:409-434`), `SavedQuery.last_answer`, `Notification` (corpo/`data`), `AutomationRun.result`, e-mails e webhooks.
- A UI já usa "Espaço" para o escopo de sincronização (`WorkspaceFolder`).
- O caminho "união" paga uma consulta de `Membership` **por pasta** (`knowledge/questions.py:1137-1143`; spike `spikes/library-scale/results/api_1k.json`: pergunta sobre 10 escopos = 417 ms, 44 instruções SQL, a consulta de membership repetida 13 vezes).

## Decisões

| # | Decisão |
|---|---|
| D1 | **Modelo:** três tabelas — `spaces`, `space_members`, `space_folder_grants`. Um Espaço **referencia** `WorkspaceFolder` (N:M); nenhuma tabela de conteúdo ganha `space_id`; nada é copiado. Remoção/revogação são **lógicas** (`removed_at`/`revoked_at`), arquivar um Espaço o torna inerte. |
| D2 | **Regra de leitura (única):** `membership ativa na organização ∧ membership ativa no Espaço ∧ concessão da pasta ao Espaço não revogada ∧ pasta consultável` (`folder_is_queryable` e o filtro de `access_lost` seguem como hoje). **Papel de admin não concede leitura.** O admin pode **entrar** no Espaço por ação auditada e visível aos membros (`space.admin_entered`). |
| D3 | **Resolvedor único** `SpaceAccessResolver` (`app/spaces/access.py`): devolve, em **quatro instruções constantes**, o conjunto de pastas acessíveis e, por pasta, **quais Espaços da própria pessoa** a concedem. `LibraryService.question_contexts` e `WorkspaceService.require_member_access` delegam a ele; o laço de `require_member_access` por pasta em `QuestionService.ask` vira uma chamada em lote. **Fail-closed:** erro propaga; resultado vazio ⇒ zero conteúdo; não existe fallback "todas as pastas" fora do modo de rollout `off`. |
| D4 | **Visão unificada por padrão (decisão central):** **não existe "Espaço ativo".** Biblioteca, busca e chat operam sobre `U(pessoa)` = união das pastas dos Espaços dela. Espaço é **filtro opcional** (`space_ids`, sempre **intersectado** com os Espaços da pessoa — só estreita) e **selo** em cada documento/citação, calculado **na leitura** e contendo **apenas Espaços da própria pessoa** (existência de Espaço alheio não vaza). `space_ids` alheio ⇒ 404. |
| D5 | **Papéis:** admin da organização (cria/arquiva Espaços, atribui pastas, gere qualquer membership de Espaço; vê metadados operacionais de todas as pastas, **não** conteúdo); **responsável** (`space_members.role='manager'`, habilita/desabilita pessoas **da organização** no próprio Espaço); **membro** (lê). Operações de pasta (sync, reprocessar, excluir) seguem por papel da organização; admin não-membro recebe contagens e códigos de falha **sem nomes de arquivo** até "Entrar". |
| D6 | **Atribuição de fonte:** a concessão nasce no ato de conectar/ligar a pasta ("Quem poderá ver?", Espaço padrão pré-marcado; sem Espaço não liga). No robô do Drive, pasta compartilhada ⇒ `WorkspaceFolder` (1:1) ⇒ concessão a 1..N Espaços. A granularidade é a do **compartilhamento** (o robô não aceita sub-pasta de pasta ligada); concessão por sub-árvore fica como evolução. `uniform_access_confirmed` permanece; seu texto passa a "todos os membros dos Espaços escolhidos". |
| D7 | **Revogação em duas velocidades:** superfícies vivas (chat, agente, busca, árvore, evidência, visualizador, API/MCP) herdam o resolvedor — efeito no **próximo request**; derivados persistidos são **ocultados na leitura pela proveniência já gravada** (`document_id` das citações; `provenance` nova em notificações/automações) e **purgados em ≤ 24 h** por job. Resposta que cita fonte perdida é ocultada **inteira** (a pergunta do usuário permanece). Automações do usuário que tocam pasta perdida são **pausadas**; e-mail/webhook/ClickUp já enviados são irrevogáveis (documentado). |
| D8 | **Credenciais:** alcance = `U(usuário vinculado) ∩ node_ids da credencial`. Sem coluna nova em `api_keys`. Admin que não é membro de Espaço ⇒ chave que não lê nada (aviso na criação). `/v1` e MCP ganham `spaces` (e `space_ids` opcional, só estreita). |
| D9 | **Migração sem mudança de comportamento:** Espaço **"Geral"** (`is_default`) por organização com **todos os membros ativos** (Owner/Admin como `manager`) e **todas as pastas**; modo por organização `off → shadow → enforce` (`organizations.spaces_resolver_mode`): em `shadow` serve o legado e registra divergência (só contagens); promove-se a `enforce` com zero divergência; rollback imediato para `shadow`. Novos membros/pastas entram no Espaço padrão enquanto o admin não decidir o contrário. |
| D10 | **Vocabulário:** "Espaço" = o novo agrupamento com pessoas. O conceito legado (`WorkspaceFolder`) passa a "Pasta conectada" na UI antes de qualquer tela nova; no código permanece `WorkspaceFolder`. |
| D11 | **Escala:** filtro por `workspace_folder_id IN :U` (já indexado nas tabelas grandes), **não** por `space_id`. Árvore/busca por nome: filtro em SQL por junção com `Document` (v1); projeção `library_node_folders` **somente se** o spike de escala (`spikes/library-scale/`) mostrar estouro do orçamento em 10k+ arquivos. Memoização do `SpaceAccess` por request é opcional. |
| D12 | **Limites:** continuam **por organização** (3.000 documentos ativos em `Settings.active_document_limit`, `MONTHLY_LIMITS`); consumo por Espaço é informativo (pasta em dois Espaços conta nos dois, rotulado). Hierarquia entre Espaços e limite por Espaço **fora** do escopo (adicionar a pessoa aos dois Espaços). |
| D13 | **Fora de escopo (decisões do dono):** CASA/OAuth `drive.readonly`; WhatsApp/Slack/Teams. O modelo **não os bloqueia**: concessão por pasta/escopo e `disclosure` JSON comportam `public_in_source`/ciência quando voltarem. |

## Consequências

**Positivas**
- A pessoa em vários Espaços nunca escolhe onde procurar; "não achei" significa "não existe para mim".
- Um ponto de verdade para acesso (D3) reduz a chance de um caminho esquecer o filtro; guarda em CI contra novos pontos de acesso sem revisão.
- Sem cópia de conteúdo: concessão e revogação custam O(linhas de `space_*`), sem reindexar.
- Migração reversível e sem efeito visível no dia do deploy.
- O N+1 de membership, hoje dominante na pergunta "união", é eliminado como pré-requisito.

**Negativas / custos**
- Superfície grande (≈ 62 ocorrências em 24 arquivos) e **árvore da biblioteca** exige filtro próprio — o maior trabalho novo; arquivos centrais (`library/service.py`, `questions.py`) forçam execução serial.
- Granularidade de Espaço no Drive = pasta compartilhada com o robô; cliente que quer dividir uma pasta única precisa compartilhar subpastas separadamente.
- Ocultar a resposta **inteira** que citou fonte perdida é conservador (pode esconder trecho ainda legítimo).
- Saídas externas (e-mail, webhook, ClickUp) são irrevogáveis; mitigadas por pausa de automação e `provenance`.
- Admin não-membro perde nomes de arquivo em operações de pasta até "Entrar" (D-2).
- Conceito novo "Espaço" colide com o uso legado do termo até T-F1.

## Alternativas rejeitadas

1. **"Espaço ativo" com troca de contexto** — rejeitada pelo dono (P-3) e porque induz "não achei" por procurar no lugar errado.
2. **Uma organização por Espaço** — isolamento perfeito sem código, mas duplica fontes e cota, não combina Espaços ([VIAB] §5.6). Serve de ponte, não de solução.
3. **N consultas (uma por Espaço) mescladas** — multiplica latência (a união de 10 escopos já custa 417 ms por N+1); o conjunto de pastas resolve a união numa só consulta.
4. **Copiar documentos/chunks por Espaço** — duplica 1 GB+ de chunks a 10k arquivos e o teto de documentos.
5. **`space_id` em `documents`/`document_chunks`/`library_nodes`** — reindexa as maiores tabelas e cria segunda fonte de verdade.
6. **Admin lê tudo** — transformaria "criar chave de API" em atalho para ler o Espaço da Diretoria (D-2 de [VIAB]).
7. **Concessão por documento/nó** — filtro por caminho em todas as consultas de chunks; adiado como evolução (R-7 do plano).
8. **Reescrever parcialmente respostas antigas** ao perder uma fonte — inventaria texto; ocultar inteiro é seguro e previsível.

## Critérios de aceite

(automatizados; detalhe em `specs/espacos/plano-implementacao.md` §13.2)
1. Organização migrada com "Geral" responde **identicamente** ao antes (contextos, árvore, busca, menções, `/v1/sources`, pergunta).
2. Membro só do Geral não encontra conteúdo de outro Espaço por nenhuma superfície (ausência/404 uniforme).
3. Remover alguém de um Espaço: próximo request sem as pastas; histórico oculta; `last_answer` limpo; automação pausada; chave/MCP encolhem.
4. Chave de admin que não é membro do Espaço não o alcança, mesmo sem `node_ids`.
5. Pessoa em 3 Espaços: **uma** pergunta, **uma** busca, **uma** árvore; filtro só estreita; `space_ids` alheio ⇒ 404; selos só de Espaços dela.
6. Falha do resolvedor ⇒ zero conteúdo.
7. Resolvedor em ≤ 4 instruções SQL constantes; orçamentos de escala do spike respeitados.
8. Conceder a mesma pasta a dois Espaços não duplica `Document`/chunks; arquivo em duas pastas aparece uma vez com selos combinados.
9. Eventos de auditoria de Espaço, membro, concessão e "admin entrou".

## Implementação (o que mudou em relação à proposta)

- Teto de documentos ativos: **3.000** por organização (era 500).
- Modos: em `shadow` o legado nunca quebra e a divergência vai para o log; `space_ids` estreita também em `off`/`shadow`; modo vazio/desconhecido ⇒ `enforce`. `403`→`404` em pasta inalcançável só em `shadow`/`enforce`.
- `access` é obrigatório nas funções de proveniência da biblioteca; `None` = visão de sistema, restrita a administração depois da checagem de admin, e proibida em código de aplicação por teste de CI (`test_spaces_call_sites.py`, lista em `specs/espacos/call-sites.md`).
- Alcance de chave (`reach`) em `POST` e `GET /api-keys`, por criador; `/people` devolve só `user_id` e e-mail.
- Escala (T-D0, `spikes/library-scale/results/api_10k_spaces.json`, `api_50k_spaces.json`): CTE recursiva dentro do orçamento até 50k arquivos; `library_node_folders` (T-D6) **não** foi liberada.
- Rollout: `python -m app.spaces.rollout` (`status`, `report`, `off|shadow|enforce`, `enforce --all-clean`); `enforce` recusa organização com pasta/pessoa sem Espaço.
- Fora do entregue: coluna "Espaços" por pasta em Integrações.

## Pontos em aberto

- Q-2 (D-2 na operação): admin vê nomes de arquivo só após "Entrar" — confirmar com o dono.
- Prazo de purga (24 h) e política de pausa de automações — confirmar.
- Reavaliar `library_node_folders` se um cliente passar de 50k arquivos ou a busca de 2 letras em ≥ 20 escopos estourar 150 ms em produção.
