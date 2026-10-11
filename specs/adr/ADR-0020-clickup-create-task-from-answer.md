# ADR-0020: Escrita pontual no ClickUp — criar tarefa a partir de uma resposta

- **Status:** Aprovado e implementado; piloto em workspace real pendente
- **Data:** 2026-10-11
- **Decisor:** produto (usuário), com os demais defaults desta ADR
- **Supera parcialmente:** ADR-0019 D3 ("somente leitura"). A leitura continua sendo o modo padrão do conector; esta ADR abre **uma única exceção de escrita**.
- **Relaciona-se com:** ADR-0019 (conector), ADR-0015 (cerca anti-prompt-injection), `backend/tests/unit/test_agent_read_only_invariant.py`.

## Contexto

Respostas do Arquivio muitas vezes terminam em "alguém precisa fazer algo" (revisar a cláusula, cobrar o prazo). Hoje o usuário copia a resposta e abre o ClickUp à mão. O token OAuth do ClickUp não tem escopos granulares (ADR-0019 D2/D3): o mesmo token já permite escrita, então **não há re-consentimento** — a barreira precisa ser nossa.

O risco é conteúdo indexado (não confiável) levar o modelo a escrever em sistemas externos. O agente e o servidor MCP são, por contrato, somente leitura.

## Decisões

| # | Decisão |
|---|---|
| D1 | **Só ação humana aprovada.** A escrita é um endpoint REST (`POST …/messages/{id}/clickup-task`) chamado pelo clique do usuário depois de revisar um rascunho editável. Nenhum modelo decide criar tarefa. |
| D2 | **Fora do agente e do MCP.** Não existe ferramenta `create_task` no agente (`INTENT_TOOLS`/`ALLOWED_TOOLS`) nem no MCP (3 ferramentas de leitura). A invariante `test_agent_read_only_invariant` segue verde e um teste novo garante que `app/knowledge` e `app/mcp_server` não referenciam a escrita. |
| D3 | **Única operação:** `POST /api/v2/list/{list_id}/task` (`ClickUpOAuthClient.create_task`). Sem editar/excluir tarefas, sem comentários, sem webhooks. O cliente de escrita **não faz retry automático** (um segundo POST após resultado desconhecido duplicaria a tarefa); 429 é devolvido ao usuário com a espera. |
| D4 | **Origem restrita:** só a resposta (mensagem `assistant`) do **próprio** usuário, em conversa dele e organização em que é membro ativo; qualquer outra combinação é 404. |
| D5 | **Validação de lista:** `list_id` precisa ser uma das listas que o administrador selecionou para a fonte ClickUp (seleção direta ou por Workspace/Space/Folder pai, resolvida pela biblioteca local — sem chamada ao ClickUp). Fora disso: 422. O menu de listas do rascunho usa o mesmo conjunto. Lista sugerida: a da fonte ClickUp mais citada na resposta; senão a primeira. |
| D6 | **Idempotência:** header `Idempotency-Key` obrigatório (16–128 caracteres `[A-Za-z0-9_-]`; o frontend gera `crypto.randomUUID()` uma vez por abertura do modal). Tabela `clickup_task_creations` (única por organização+chave) é gravada como `pending` **antes** da chamada. Mesma chave devolve a tarefa existente sem nova chamada; chave de outro usuário/mensagem → 409; `pending` → 409; falha conhecida (`failed`) permite repetir a mesma chave; **resultado desconhecido** (timeout/5xx, `error_code=outcome_unknown`) bloqueia a mesma chave (409) para forçar o usuário a conferir o ClickUp antes de abrir uma nova tentativa. |
| D7 | **Autoria no rodapé:** a tarefa nasce com o token de quem conectou o ClickUp; por isso o servidor **sempre** acrescenta "Criada pelo Arquivio a pedido de `<e-mail do usuário>`" à descrição (o cliente não controla nem remove o rodapé; o modal o mostra de forma somente leitura). |
| D8 | **Auditoria e abuso:** `AuditLog` `clickup.task.created` (ator, organização, id do registro); a tabela guarda só ids/estado/erro, nunca o conteúdo. Limite simples de **5 criações por minuto por usuário** (contado na própria tabela, vale entre workers; repetição de chave não conta). Campos saneados e limitados (título 200, descrição 20.000, 10 etiquetas de 50, 10 responsáveis, prioridade 1–4, prazo entre 2000 e 2100, caracteres de controle/invisíveis removidos). |
| D9 | **Erros mapeados:** 401 → fonte vira `reauth_required` + mensagem de reconexão (o botão some até reconectar); 403/404 → "sem permissão nesta lista"; 429 → espera informada (`Retry-After`); 400/422 do ClickUp → "recusou os dados"; timeout/5xx → "não foi possível confirmar". O token nunca é logado. |
| D10 | **Quem pode:** qualquer membro ativo da organização (a mesma audiência que já lê o conteúdo do ClickUp pelo chat, ADR-0019 D3). Alternativa mais restrita (só admin) fica como ajuste de política se o piloto pedir. |
| D11 | **Visibilidade do botão sem custo:** `GET /library/question-contexts`, que o chat já carrega, passa a trazer `source_status` por contexto. O botão aparece só quando existe contexto `clickup` com `source_status == "connected"` e a mensagem está persistida. Nenhuma chamada extra ao ClickUp decide a visibilidade; membros e statuses só são lidos (por lista, sob demanda) quando o modal abre. |
| D12 | **Rascunho sem efeito colateral:** `GET …/clickup-task/preview` lê apenas dados locais (título = pergunta, descrição = resposta + seção "Fontes" com links das citações, listas, sugestão). `GET …/lists/{list_id}/options` lê membros e statuses de **uma** lista selecionada (a lista de membros do ClickUp pode vir incompleta; responsável é opcional). |

## Consequências

- O conteúdo da resposta passa a existir também no ClickUp e fica visível para quem acessa a lista; o modal avisa isso. Excluir a tarefa no ClickUp não é coberto pelo Arquivio.
- Tarefas aparecem como criadas pela pessoa que conectou o ClickUp (limitação do token único); o rodapé é a atribuição.
- O 5xx/timeout com resultado desconhecido pode deixar uma tarefa criada sem registro `created`; o fluxo prefere pedir conferência humana a arriscar duplicidade.
- Seleção de listas é a projeção local da última sincronização: uma lista removida da seleção some do menu na próxima sincronização; até lá o ClickUp ainda valida a permissão no POST.
- A migração `20261011_0029` é aditiva (tabela nova); rollback = `alembic downgrade 20261010_0028`.
