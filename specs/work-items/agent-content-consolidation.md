# agent-content-consolidation

Owner: pane-273; branch: existing shared local main. Claimed before production edits.
Scope: questions.py, focused mocked regressions, replay script and reports.
Existing agent-flow and semantic-provenance tests are updated for the new factual
prompt and concise unavailable-provider response; their citation/link assertions remain.
Existing frontend/library changes and dirty graphify outputs are excluded from commits.

## Root cause before correction

The supplied transcript explicitly starts with the extractive fallback, not model-generated
file cards. Current main is c092cd1, with only two tracked frontend modifications; the
requested six earlier uncommitted files are no longer present in this state. Preserve
all existing work and ancestors, including 1b7de66/c9cebf0/3afc9bd/e983721/fb8003f/7d3df7e.

`docker compose logs backend --since 60m` reports `no such service: backend`.
Actual service `api` logs show request b5bb9b00: classifier 6251 ms, embedding 964 ms,
generation read_timeout 12899 ms and provider_unavailable_extractive_fallback.
The fallback copies four complete passages, headed by document names. The 7d3df7e
format instructions cannot govern that Python-built response. Content runs through
OpenAIQuestionProvider.answer, not synthesize_answer. Real replay also selects
ask_content/library and times out; no per-file intent exists in the closed schema.

Hypothesis: full-context generation with default reasoning exhausts the shared 25 s
budget, causing the uncapped excerpt fallback; document-labelled source wrappers also
lack an explicit shared evidence-pool contract and equivalent-content citation policy.
Keep complete evidence; strengthen concise consolidation and bound reasoning effort.

## Correção e replay

Consultas factuais recebem um pool de evidências entre documentos, grupos de passagens
literalmente equivalentes e instruções próprias de resposta curta; o vocabulário completo
de blocos permanece para inventário/resumos. Cada fato repetido usa uma fonte suficiente;
fatos complementares e divergências relevantes conservam fontes distintas. A deduplicação
determinística aceita só conteúdo idêntico, sem confundir nomes similares ou datas diferentes.
Índices válidos repetidos na saída do LLM são normalizados antes da validação existente;
índices fora do escopo continuam inválidos. Nenhuma regra por palavras da pergunta foi adicionada.

O primeiro replay posterior mostrou citações repetidas e abstenção por validação; o
segundo respondeu curto mas omitiu Allstacks presente na evidência. O catálogo geral de
blocos foi separado do prompt factual para eliminar a abertura obrigatória e a competição
com a instrução de consolidação. Replay final: quatro empresas, 289 caracteres,
Profile.pdf com link, 12,52 segundos; antes: fallback de 17.603 caracteres, 25,85 segundos.
As 28 passagens, hashes, ordem e 55.675 caracteres são idênticos antes/depois.

Durante a avaliação outro processo recriou api/worker/docling, encerrando um exec com
137 e apagando o /tmp do container. As capturas já estavam preservadas no host; o replay
final foi repetido numa cópia isolada do código. Este worker não parou/recriou serviços.

Detalhes: backend/scripts/reports/content-consolidation.md e relatórios JSON próximos.
Não fazer push. Rebuild/recriação de api e worker aplica o código final; sem migração
de banco ou mudança no frontend. O SHA do questions.py instalado difere do final validado.
