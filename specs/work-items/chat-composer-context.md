# chat-composer-context — Contexto por mensagem no chat

**Status:** done — decisões protegidas aprovadas explicitamente pelo usuário com “perfeito, pode seguir”; implementação autorizada em 2026-09-27.

## Fonte e resultado

- Pedido da missão: contexto no compositor, controle compacto com seleção de várias ferramentas e menções pesquisáveis de arquivos/pastas por `@` ou `/`.
- Fonte: `specs/001-mvp-document-intelligence.md` §3, F4 e §10; `specs/adr/ADR-0007-indexed-question-scopes.md`; `specs/work-items/F-042.md`.
- Resultado: a pergunta usa somente arquivos indexados autorizados das ferramentas escolhidas, opcionalmente delimitados por menções, com citações de ferramenta e arquivo.
- Não inclui busca ao vivo nos provedores, ACL granular, mudança de retenção, novo conector/serviço ou salvar consulta ampla num registro de pasta.

## Evidência do estado atual

| Achado | Local |
| --- | --- |
| A API pública da organização aceita `organization` ou `provider` singular; a rota legada cobre uma pasta. | `backend/app/api/ingestion.py:56-70,270-322` |
| O serviço aceita internamente uma lista de pastas, revalida membro/pasta e filtra documento/chunk por organização e pasta antes do ranking. | `backend/app/knowledge/questions.py:277-405` |
| O catálogo expõe pasta, fonte, provider e estado; a busca da biblioteca procura nomes de arquivos/pastas. | `backend/app/library/service.py:271-336`; `backend/app/api/library.py:58-101` |
| Um arquivo da árvore mapeia para documentos por `(source_id, external_file_id)`, inclusive em escopos sobrepostos. | `backend/app/library/service.py:177-208` |
| A UI tem `<select>` único acima da conversa e envia apenas o escopo escolhido; não envia menções estruturadas. | `frontend/app/question-scope.tsx:21-55`; `frontend/app/product-app.tsx:417-430,520-560` |
| Todos os membros ativos da organização compartilham o conteúdo conectado; platform staff não herda acesso. Fontes desconectadas retêm índice conforme ADR. | `specs/001-mvp-document-intelligence.md:75-83`; `specs/adr/ADR-0007-indexed-question-scopes.md:11` |

## Decisões protegidas para aprovação

| Decisão | Proposta recomendada | Por que é protegida |
| --- | --- | --- |
| Combinação de ferramentas e menções | Ferramentas escolhidas são o limite da consulta. Sem menções: união de suas pastas elegíveis. Com menções: somente arquivos citados e descendentes das pastas citadas dentro dessas ferramentas; múltiplas menções fazem união. Uma menção de outra ferramenta exige marcá-la antes do envio. | Define quais dados chegam ao modelo. |
| Identidade da ferramenta | Uma opção por `provider` com conteúdo indexado da organização, agrupando conexões do mesmo provider. Índice de fonte desconectada continua consultável conforme ADR-0007; rotular como “conteúdo indexado”. | Define propriedade/visibilidade dos dados; “conectada” no pedido pode significar outra política. |
| API pública | Adicionar modo `scope=selection` à rota da organização com `providers[]` e `mentions[]`; manter todos os modos e rota legados. | Altera contrato público. |

As três decisões acima foram aprovadas explicitamente pelo usuário. ADR-0007 e F4 da spec registram o comportamento durável. Ownership: backend e testes backend no executor pane-104; frontend e dossiê no pane-103; validação independente após integração.

## Contrato proposto: descoberta

- `GET /library/question-contexts?organization_id=...` continua a fornecer `id`, `source_id`, `source_provider`, `status` e `query_status`. A UI agrupa por provider normalizado. “Todas as ferramentas” é opção exclusiva, equivalente aos providers indexados elegíveis atuais da organização, não a um provider especial. Indicar cobertura parcial, pendência e ausência de embeddings. Fonte desconectada com índice segue a retenção vigente.
- Novo `GET /library/mention-candidates?organization_id=...&q=...&limit=20`, retornando `{items:[{node_id,kind,name,source_id,source_provider,path,query_status}]}`. `kind` é `file|folder`; `path` diferencia nomes iguais. Buscar somente metadados de `LibraryNode` da organização, após associação ativa e junção com fonte da mesma organização. Mostrar apenas nós que levam a documento indexado em WorkspaceFolder elegível. Pasta inclui descendentes indexados. Ordenação estável, limite fixo, sem conteúdo extraído, credenciais ou URL externa. A busca existente da Biblioteca permanece intacta.
- O cliente pode filtrar sugestões pelas ferramentas escolhidas; o backend sempre revalida seleção e nós no envio.

## Contrato proposto: pergunta

```json
{
  "question": "Resuma os prazos",
  "scope": "selection",
  "providers": ["google_drive", "notion"],
  "mentions": [{"kind": "file", "node_id": "00000000-0000-0000-0000-000000000001"}]
}
```

- `providers`: lista não vazia, sem duplicatas após normalizar aliases (`google`/`google_drive`), limitada ao catálogo conhecido. `mentions`: opcional, máximo de 20 nós distintos com tipo e UUID válidos. `provider` singular é inválido junto de `selection`; combinações inválidas são 422. Pergunta continua entre 1 e 1000 caracteres. `@` e `/` são atalhos da UI; só IDs escolhidos e enviados separadamente contam como menções. Texto que parece menção não altera o escopo.
- Resolver providers e menções em `LibraryService` após validar membro ativo. Revalidar `LibraryNode`, fonte, descendência, documento, estado de WorkspaceFolder e organização. Intersectar com providers marcados. Nó estrangeiro/removido, tipo falso, provider fora da seleção ou arquivo sem índice válido falha de forma segura antes de embedding/modelo; não ampliar silenciosamente a busca.
- `QuestionService` recebe IDs de pastas **e** filtro de `document_id` autorizado. Aplicar ambos em contagem, inventário, busca semântica, busca lexical e evidências, antes do ranking e da geração. Arquivo indexado em várias pastas usa só cópias elegíveis e deduplicação `(source_id, external_file_id)`; IDs externos iguais em fontes diferentes permanecem separados.
- Preservar `answer`, `confidence`, `citations`, `retrieval_status`, `coverage` e erros HTTP atuais. No novo modo, citações incluem `source_provider`; `resolved_context` opcional retorna providers/contagens e IDs locais aceitos, sem conteúdo. Sem evidência: `answer:null`, citações vazias e status seguro. Falha da IA/cota permanece HTTP explícito. Logs só com contagens, status e duração, sem pergunta, texto, nome ou segredo. Sem contexto elegível, não chamar modelo. Compatibilidade integral dos endpoints antigos; perguntas salvas continuam restritas à pasta legada.

## Contrato proposto: compositor

- Retirar seletor superior; colocar controle compacto junto ao textarea. Popover multisseleção: “Todas as ferramentas” e um item por provider com índice. Marcar “Todas” limpa individuais; marcar provider desmarca “Todas”; seleção vazia impede envio. Resumo e cobertura acessíveis sem ocupar altura permanente. O foco visual da tela permanece na pergunta; reutilizar tokens, CSS e ícones Lucide atuais.
- `@` abre busca de arquivo/pasta no cursor; `/` abre comandos “Arquivo” e “Pasta” para a mesma busca. Digitação filtra por nome/caminho; setas/Enter escolhem; Escape fecha; toque/click funcionam. Resultados homônimos mostram ferramenta e caminho. Itens escolhidos viram chips removíveis com IDs estruturados; editar/remover atualiza esses IDs. Respeitar IME, debounce/cancelamento e respostas obsoletas. Texto comum com `/` não deve abrir comando fora do gatilho.
- Ao enviar, congelar `{question,providers,mentions,labels}` na mensagem e no request. Bloquear mudanças de escopo durante request; limpar só rascunho enviado; preservar rascunho/menções em falha para reenviar. Mudança posterior de seleção não altera histórico. Exibir loading, vazio, erro e retry. Teclado, rótulos, foco visível, alvos ≥44 px e 375/768/1024/1440 px sem rolagem horizontal.

## Ownership e matriz de aceite

| Papel | Arquivos previstos | Entrega |
| --- | --- | --- |
| Analista | Este dossiê e spec/ADR após decisão | Contrato e aceite |
| Implementação backend | `backend/app/api/ingestion.py`, `backend/app/api/library.py`, `backend/app/library/service.py`, `backend/app/knowledge/questions.py` | Resolução/autorização/filtro |
| Implementação frontend | `frontend/app/product-app.tsx`, `frontend/app/question-scope.tsx`, CSS de chat/controle | Compositor e histórico |
| Testes | `backend/tests/api/`, `backend/tests/unit/` e testes frontend adequados | Positivos, erros e isolamento |
| Validador independente | Diff final, sem editar | Gate |

| Dado / quando / então | Evidência requerida |
| --- | --- |
| Duas ferramentas prontas / marcar ambas e perguntar sem menção / somente união autorizada, com citação de ferramenta e arquivo. | API e fixture de recuperação; corpo HTTP UI |
| “Todas” selecionada / marcar uma ferramenta / “Todas” sai; marcar “Todas” limpa individuais; mensagem antiga retém snapshot. | Componente/e2e |
| Arquivo e pasta mencionados / perguntar / somente arquivo e descendentes elegíveis entram em contagem, ranking, prompt e citações. | Unit/API com provedor fake capturando evidências |
| Mesmo arquivo em escopos sobrepostos / consultar / sem cópia duplicada; IDs externos iguais em fontes distintas permanecem distintos. | Unit |
| Nó de outro tenant, membro inativo/staff, tipo falso, nó removido ou provider não marcado / listar ou perguntar / recusar antes do modelo e sem metadados estrangeiros. | API negativa e isolamento |
| Conteúdo vazio, pendente ou sem embedding / consultar / sem resposta factual e com estado/erro explícito. | API/UI |
| Teclado, toque e 375/768/1024/1440 px / abrir, buscar, escolher e remover / controles acessíveis e sem sobreposição. | UI DOM e inspeção visual |
| Cliente legado / perguntar por pasta/provider/organização ou salvar por pasta / contrato atual continua. | Regressão API/UI |

## Validação e gate

- Após aprovação: testes focados de API/perguntas semânticas, suíte backend, Ruff, lint/build frontend, interação e responsividade, revisão independente, `git diff --check` e `.tools/graphify/bin/graphify update .` após editar código.
- Performance: fixture local com várias pastas, cópias duplicadas e 20 menções; medir duração, queries e volume antes do ranking. Não alegar p95 sem benchmark. Sem migração prevista; histórico/menções continuam em memória como hoje. Rollback: retirar modo novo no compositor, preservando endpoints legados.
- Evidência de implementação: backend `.venv/bin/pytest -q` (309 passed, 8 skipped, informado pelo executor), suíte focada `.venv/bin/pytest -q tests/api/test_chat_composer_context_api.py tests/api/test_multiscope_questions_api.py` (33 passed), Ruff limpo (executor), `frontend/npm run lint` (exit 0, um aviso existente em `product-app.tsx:643`), `frontend/npm run build` (exit 0), `frontend/node_modules/.bin/tsc --noEmit` (exit 0 após anotar tipos do proxy API), `git diff --check` (exit 0), `.tools/graphify/bin/graphify update .` (exit 0). Não houve migração nem mudança de retenção; rollback do compositor preserva endpoints anteriores.
- Validação independente: pane-105 executou suíte backend (309 passed, 8 skipped), lint, Ruff e build; não encontrou bloqueante de isolamento. Apontou dois findings médios de UX/estado: Escape reabria menções na tecla seguinte; falha podia reaplicar menções antigas a novo rascunho. Corrigidos com supressão do gatilho até o token terminar e snapshot preservado na mensagem falha com ação explícita de repetir. O mesmo validador reexaminou ambos por inspeção, não encontrou novo bloqueante e repetiu 33 testes focados, Ruff, lint, TypeScript e `git diff --check` com sucesso. A interação visual autenticada e a checagem manual nos quatro viewports não foram executadas; essa evidência permanece uma limitação. O typecheck inicialmente falhou por dois parâmetros sem tipo no proxy API fora do diff; a anotação foi incluída e `tsc --noEmit` passou. Gate final: sem finding bloqueante, implementação e verificações concluídas.
