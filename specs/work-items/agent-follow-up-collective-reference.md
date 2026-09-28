# Seguimento coletivo do agente após inventário de pasta

**Status:** validating — implementação concluída; validação independente reservada ao piloto da Missão 19.

## Fonte, escopo e aprovação

- Fonte: `specs/001-mvp-document-intelligence.md` F4, §§7 e 11; contrato aprovado de contexto em `specs/work-items/chat-composer-context.md`; relato real da Missão 19 e diagnóstico `h-6j`.
- Aprovação: a missão já autoriza corrigir a regressão de referência coletiva no seguimento sem ampliar autorização, contrato público ou comportamento de outras funcionalidades.
- Resultado: depois de um inventário autorizado de pasta, a frase real “me de um resumo bem sucinto do conteudo de cada arquivo” reutiliza todas as referências de arquivo persistidas daquele inventário e produz a síntese extrativa existente por arquivo.
- Não inclui: diagnosticar/corrigir o HTTP 503, mudar provedor/timeout, UI, API, modelo de dados, produção ou o contrato de síntese extrativa.

## Diagnóstico e decisão

- Causa raiz: `AgentService` já reautoriza referências persistidas por organização, provider e pasta, mas `_plural_file_reference` reconhecia somente pronomes (`eles/elas/deles/delas/ambos/ambas`). A expressão coletiva nominal “cada arquivo” não ativava esse caminho e caía no retrieval comum.
- Decisão técnica: ampliar somente o detector existente para as formas coletivas de arquivo `cada arquivo`, `cada um dos arquivos` e `todos os arquivos`. É uma escolha de implementação coberta pelo comportamento aprovado; não altera ownership de dados, autorização, retenção, custo material ou API pública.
- Ownership: implementação em `backend/app/knowledge/agent.py`; regressão em `backend/tests/unit/test_document_agent.py`; este dossier. O piloto executará a revisão independente sem editar durante o gate.

## Critérios de aceite e matriz de testes

| Critério | Evidência |
| --- | --- |
| A frase real ativa o seguimento coletivo após inventário. | `test_follow_up_plural_reuses_only_the_persisted_folder_inventory` |
| “Cada arquivo” e “todos os arquivos” positivos retornam todos os arquivos previamente referenciados; arquivo fora da pasta não aparece. | Asserções de conteúdo e conjunto de referências no teste de agente. |
| Uma negação explícita coletiva seguida de ordinal (“Não resuma todos os arquivos; apenas o segundo.”) seleciona só o ordinal. | Asserções da resposta e das evidências do provider no teste de agente. |
| Ordinal qualificando um coletivo positivo (“todos os arquivos, começando pelo segundo”) mantém o pedido coletivo. | Asserções de ambos os arquivos no teste de agente. |
| O seguimento usa referências persistidas, sem menções novas. | Inventário é salvo em `ConversationMessage.context.references`; o segundo `ask` usa `mentions=[]`. |
| Provider, pasta e organização continuam sendo reautorizados. | Provider incompatível, arquivo movido para fora da pasta e organização aleatória resultam em `SyncAccessDenied`; suíte de isolamento pertinente permanece verde. |
| Formulações coletivas anteriores continuam funcionando. | Testes existentes com “eles” e suíte integral de `test_document_agent.py`. |

## Evidência reproduzível

- Fail-before do h-6k: `cd backend && ./.venv/bin/pytest -q tests/unit/test_document_agent.py::test_follow_up_plural_reuses_only_the_persisted_folder_inventory` → exit 1, pois o provider comum era chamado para a frase real.
- Fail-before de h-6m: com as novas asserções, o teste focal sobre o detector de `651d5d2` → exit 1; a resposta incluía `A Gravidade.pdf` apesar de “apenas o segundo”.
- Pass-after focado: `cd backend && ./.venv/bin/pytest -q tests/unit/test_document_agent.py::test_follow_up_plural_reuses_only_the_persisted_folder_inventory` → exit 0, `1 passed`.
- Pass-after do arquivo: `cd backend && ./.venv/bin/pytest -q tests/unit/test_document_agent.py` → exit 0, `9 passed`.
- Pós-correção o teste focal valida os pedidos “cada arquivo”, “todos os arquivos”, negação com ordinal e coletivo positivo com ordinal, além de isolamento/reautorização.
- Suíte backend: `cd backend && ./.venv/bin/pytest -q` → exit 0, `348 passed, 8 skipped`; quatro warnings de depreciação já existentes.
- Lint: `cd backend && ./.venv/bin/ruff check app/knowledge/agent.py tests/unit/test_document_agent.py` → exit 0.
- Integridade do diff: `git diff --check` → exit 0.
- Grafo: `.tools/graphify/bin/graphify update .` → exit 0; 3.525 nós e 9.385 arestas.

## Riscos, rollback e gate

- Risco residual: o detector é lexical e intencionalmente estreito; negações com verbos fora da lista (`resuma/resumir`, `liste/listar`, `analise/analisar`, `descreva/descrever`) ainda podem ser interpretadas como coletivas. Novas paráfrases precisam de testes antes de ampliar a lista.
- Rollback: reverter a alternativa nominal adicionada à regex; nenhuma migração ou limpeza de dados é necessária.
- Revisão independente h-6m: bloqueou `651d5d2` porque a frase negada selecionava ambos os arquivos e `todos os arquivos` não tinha teste automatizado de ponta a ponta. Correção e cobertura atualizadas; aguardar nova revisão do piloto.
- Gate: manter `validating` até a nova revisão independente do piloto. O 503 permanece fora deste diagnóstico e desta correção.
