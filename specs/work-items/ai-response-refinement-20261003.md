# Refinamento de respostas: inventário, contagem e seleção temática

Data: 2026-10-03. Base inspecionada: `d5cfad7f173acdea4749ac38c05dad4190ead421`.
Investigação consultada: handoff `h-gs`, pane-418. Implementação: pane-419, missão uP2WVPUrvYxO.

## Correções da revisão h-gw — responsável pane-422

Claim em 2026-10-03, branch compartilhada `design/arquivio-identity-20261003`.
Contrato: corrigir somente os quatro warnings de h-gw/pane-421 sobre h-gu/pane-419,
preservar alterações preexistentes, executar regressões/checks e atualizar o grafo; sem deploy.
Skills: inline [oc-builder, oc-blackbox, oc-stamp].

Investigação antes do fix: a query de `catalog_file_snapshots` retorna todos os chunks e
somente o loop Python aplica o teto; `_topic_assessments` aceita qualquer substring não
vazia; `catalog_inventory` usa `parent_id == root.id` para pastas, sem aviso na contagem;
`_inventory_stats` cai em `list(listing.citations)` quando não há temas. Hipótese:
esses quatro comportamentos decorrem respectivamente da ausência de limite SQL por
documento, de validação de quote apenas por substring, de escopo não exposto e de fallback
de citações sem relação com afirmações temáticas. Testes foram escritos e executados
antes dos fixes; a reexecução final em cópia isolada do estado h-gu confirmou **18 failed /
3 passed**, exit 1 esperado. Log: `ai-response-refinement-20261003.review-red.txt`.
Status: quatro achados corrigidos e regressões verificadas.

| Achado h-gw | Correção e evidência |
|---|---|
| Leitura ilimitada de chunks | Subquery de documentos admitidos + `row_number()` por documento, ordenado por posição; no máximo seis chunks retornados por documento. `substr` limita cada texto a 6.000 caracteres no SQL e o orçamento agregado permanece no Python. Teste observa 7 linhas (6 + 1) em vez de 41, mantendo o outro arquivo e o estado não indexado; primeiro chunk de 18.000 caracteres também fica limitado. Execução SQLite e compilação do SQL PostgreSQL. |
| Quote trivial ou variação de caixa rejeitada | Exigir 20–600 caracteres e três palavras com pelo menos duas letras, além de procedência em um único chunk do próprio arquivo. NFKC, remoção dos controles invisíveis já tratados pelo provider, espaços e casefold também aplicados à comparação e ao filtro de título isolado. Prompt alinhado. Evidência fraca, inclusive `matches=False`, permanece desconhecida. Isto não prova entailment. |
| Escopo de pasta não divulgado | A contagem diz que considera arquivos diretamente nas pastas e não inclui subpastas. `inventory_scope` no contexto conserva o aviso após pastas múltiplas/vazias; biblioteca explícita limpa esse escopo. O filtro de filhos diretos no catálogo permanece igual. |
| Citações irrelevantes sem temas | Removido o fallback para todas as citações do inventário. O estágio `cite` respeita o conjunto intencionalmente vazio das estatísticas; sem esse ajuste ele reinjetava as fontes. Um inventário de 31 arquivos mantém todas as referências para o próximo turno e devolve zero citações quando a análise falha. Citações dos temas avaliados continuam presentes. |

Regressões novas: `backend/tests/unit/test_inventory_review_regressions.py` (**21 casos**).
Com a fixture anterior são **41 passed**, exit 0. Suíte ampla: **1.407 passed**, quatro avisos
de depreciação, 27,89 s, exit 0. Ruff nos dez módulos/testes do fluxo: **All checks passed**,
exit 0. Nenhuma chamada externa ou deploy. A revisão independente h-gw foi consultada
integralmente; estes fixes ainda não receberam uma segunda revisão independente.

Limites desta validação: PostgreSQL compilado, sem execução em um banco PostgreSQL real;
nenhum benchmark com modelo real. O banco ainda pode examinar/ordenar chunks para calcular
a janela, mas não transmite todos eles à aplicação. A validação estrutural da evidência pode
reduzir cobertura em arquivos muito curtos e não garante a correção semântica do tema.
O conjunto de citações temáticas mantém o comportamento anterior; apenas citações sem temas
são omitidas. Alterações próprias em produção limitadas a `agent.py`, `questions.py` e
`library/service.py`; a implementação h-gu e trabalhos concorrentes foram preservados.

Atualização de grafo após os fixes: `graphify update .`, exit 0, **7.545 nós / 20.896
arestas / 521 comunidades**. AST sem LLM; labels semânticos podem continuar desatualizados.
O workspace é compartilhado e teve mudanças concorrentes em frontend; elas não foram
editadas/revertidas por pane-422. A entrega local inclui os pré-requisitos de h-gu que ainda
estavam sem commit, com pathspec exclusivo do fluxo de IA, testes e relatório; alterações
de frontend, outros relatórios e graphify-out permanecem fora desse commit. Sem push/deploy.

## Diagnóstico confirmado

O exemplo fornecido tem três turnos: listar o Google Drive, contar e explicar temas, selecionar arquivos sobre currículo/carreira. O texto colado não contém identidades do catálogo nem telemetria: marcadores de fontes e nomes repetidos não provam quantos arquivos únicos existem. A afirmação anterior de que são exatamente 36 arquivos não foi adotada.

No código anterior, uma listagem sem pasta nem pesquisa nominal era rejeitada por `_list_files` e caía em retrieval semântico. `INTENTS` não continha contagem ou seleção temática; `summarize_files` resumia todo o conjunto, sem filtrar por tema. Contagem não deve depender de top-k, número de fontes, chunks ou nomes distintos. A síntese global limita fontes a 24; não serve como cobertura de um inventário completo.

Baseline reproduzido em cópia temporária isolada, restaurando os seis módulos de produção afetados a partir de HEAD e usando as mesmas fixtures sintéticas atuais. Os três testes `pasted_multiturn`, `stats_after_folder` e `topic_selection_after_folder` falharam (pytest exit 1): primeira listagem sem referências; contagem roteada para `ask_content`/fallback; seleção sem arquivos pertinentes. A mesma avaliação passa na implementação candidata. Não houve alteração temporária do código compartilhado para executar o baseline.

A hipótese de timeout nos resumos do exemplo original continua não comprovada: faltam logs reais. Não foram implementadas mudanças gerais de resumos, guardas editoriais ou renderização de citações com base nessa hipótese.

## Implementação e critérios

| Critério | Implementação / evidência |
|---|---|
| Listar sem pasta anexada | Inventário local autorizado, sem retrieval top-k; total e todas as referências retornadas até os limites explícitos. |
| Contar deterministicamente | `inventory_stats`, contagem por identidade do catálogo; arquivos sem conteúdo entram no total; estados de conteúdo relatados separadamente. |
| Explicar temas | Análise de arquivos em lotes de dez, seguida de agrupamento determinístico por tema principal. Toda evidência citada pertence ao arquivo avaliado. |
| Selecionar por tema | `select_files_by_topic`, retorno apenas de matches, prova textual validada em um dos chunks daquele arquivo e citações correspondentes. |
| Preservar contexto | Estatística conserva candidatos, ordem e pasta de origem; seleção conserva os matches; seleção vazia continua vazia no seguimento. |
| Completude honesta | Total, quantidade retornada e truncamento distintos; limites por itens/bytes explícitos; seguimento não transforma lista parcial em total atual do Drive. |
| Revalidar permissões | Catálogo atual, membership, provider, organização, estado do documento e pasta de origem verificados novamente; referência removida/movida/revogada falha fechada. Snapshots não leem documentos de pastas não admitidas. |
| Limitar custo e falhas | Um orçamento compartilhado de timeout para os lotes; sem novos lotes após expirar; falha/quote inválida/título isolado vira desconhecido, não negativo. Telemetria `file_topics` sem conteúdo. |
| Roteadores | Schema/prompt LLM e critérios Jev reconhecem os novos intents; avaliador preserva contexto de seleção vazia. |

Foram consultadas as três skills do projeto como referências de avaliação, segurança e estados de ingestão. `arquivio-rag-evaluation` orientou fixtures sintéticas e baseline/candidato; `arquivio-tenant-security`, revalidação e organizações/pastas adversárias; `arquivio-connectors-ingestion`, distinção entre arquivo presente, não indexado e retirado. Nenhum conector, OAuth, cursor, extração ou consentimento foi alterado. Contrato do pane: skills inline [oc-stamp].

## Validação

Fixtures novas em `backend/tests/unit/test_inventory_followups.py`: fluxo multi-turno, contagem após pasta, seleção após pasta, nomes repetidos, candidato após a 24ª fonte, chunk posterior, deindexação, título isolado, lista parcial por itens e bytes, quotes inventadas, timeout, seleção explícita, arquivo removido/movido, membership revogado, tenant adversário, pasta negada na mesma fonte, seleção vazia e contrato do adapter sem rede. São 20 testes locais.

Dataset do classificador: três casos adicionais em `backend/scripts/intent_eval_cases.json`. A execução com modelo real não foi feita; testes com saída de classificador fake verificam o contrato e o pipeline, não a acurácia do provedor real.

Comandos finais são executados a partir de `backend/` para pytest. A primeira tentativa ampla a partir da raiz carregou outro `.env` e caminhos relativos incorretos; foi descartada e reexecutada no diretório correto. Resultados finais e atualização AST do grafo constam da devolutiva do worker.

## Limitações e próximos checks

O catálogo é um instantâneo local, não uma consulta ao vivo ao Drive. O limite de 500 arquivos e o orçamento de bytes podem produzir listagens parciais. A análise temática usa snapshots existentes de até seis chunks / 6.000 caracteres; conteúdo relevante fora dessa janela pode não ser detectado. A resposta informa cobertura limitada. Rótulos temáticos e matches continuam semânticos: validação da quote prova procedência, não entailment ou classificação correta. Taxonomia entre lotes pode variar. Timeouts e dados insuficientes reduzem cobertura explicitamente.

Não foram medidos latência/tokens/custo reais, não foram usados dados de clientes em chamadas externas e não houve benchmark pago. A contagem pura hoje também tenta temas, usando o mesmo orçamento limitado. Na entrega original h-gu não houve teste em produção, deploy, commit ou entrega remota. A revisão independente h-gw e seus fixes estão registrados acima; uma avaliação pequena com provedor real em ambiente sintético continua a cargo do piloto antes de rollout.

O workspace já continha modificações de frontend, specs e graphify-out. As alterações de interface existentes não foram modificadas nem revertidas por esta tarefa. `graphify update .` atualiza o grafo AST; seus rótulos semânticos podem continuar desatualizados, pois não foi executado `graphify label` com LLM.

## Resultado observado na entrega h-gu (antes da revisão)

- `cd backend && .venv/bin/pytest tests/unit tests/api -q --tb=short`: **1.386 passed**, 4 avisos de depreciação, 30,93 s, exit 0.
- Fixture nova: **20 passed**, exit 0.
- Ruff nos nove módulos/testes afetados: **All checks passed**, exit 0.
- `git diff --check`: exit 0.
- `graphify update .`: exit 0; **7.556 nós, 20.893 arestas**, atualização AST sem LLM.
- Baseline isolado dos três cenários: **3 failed / 15 deselected**, pytest exit 1 esperado; candidato passa.
